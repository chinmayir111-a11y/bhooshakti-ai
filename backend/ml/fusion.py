"""Risk fusion.

Combines the XGBoost susceptibility probability with live rainfall pressure,
soil saturation, the 24-hour rainfall outlook and sensor availability into a
single decision-support figure:

    risk_score (0-100), severity, confidence (0-1), contributing_factors[]

Design rules this module exists to enforce:

  * The output is DECISION SUPPORT, never a guaranteed prediction. Every
    result carries a confidence and a ranked, plain-language explanation.
  * Confidence falls when the evidence is thin — failed sensors, stale
    telemetry, or the model disagreeing with what the rain gauges say.
  * No model accuracy figure is ever produced here. Confidence is about
    *this* estimate, not about the model's historical performance.

Pure functions only: no database, no I/O. Tested in tests/test_fusion.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .features import LAND_COVER_LABELS, LITHOLOGY_LABELS

# ---------------------------------------------------------------------------
# Tunables (single source of truth — tests import these, never re-declare them)
# ---------------------------------------------------------------------------

SEVERITY_BANDS: list[tuple[float, str]] = [
    (75.0, "CRITICAL"),
    (50.0, "HIGH"),
    (25.0, "MODERATE"),
    (0.0, "LOW"),
]

WEIGHTS = {
    "model": 0.55,
    "rainfall": 0.18,
    "saturation": 0.14,
    "forecast": 0.13,
}

SATURATION_FLOOR_PCT = 55.0     # below this, soil contributes nothing
SATURATION_CEILING_PCT = 90.0   # at/above this, soil contributes fully
RAIN_RATIO_FLOOR = 0.6          # x seasonal normal
RAIN_RATIO_CEILING = 2.2
FORECAST_CEILING_MM = 120.0

# A field officer standing on the slope is the strongest single piece of
# evidence the system can have. A confirmation raises the hazard and the
# confidence; a denial lowers the hazard but does NOT lower confidence — a
# checked slope is better understood than an unchecked one either way.
VERIFICATION_UPLIFT = 0.25
VERIFICATION_DENIAL = -0.16
VERIFICATION_FRESH_HOURS = 12.0

CONFIDENCE_BASE = 0.90
CONFIDENCE_MIN = 0.15
CONFIDENCE_MAX = 0.95
STALE_TELEMETRY_MINUTES = 180.0

# Static terrain propensity, used only for explanation text (the model already
# consumes slope / lithology / land cover as features — no double counting).
LITHOLOGY_WEAKNESS = {
    "phyllite_schist": 1.00, "sandstone_shale": 0.92, "alluvium_terrace": 0.70,
    "gneiss": 0.60, "quartzite": 0.55, "limestone": 0.50, "granite": 0.35,
}
LAND_COVER_WEAKNESS = {
    "barren_rock": 0.95, "built_up": 0.90, "scrub_grassland": 0.80,
    "terrace_agriculture": 0.70, "tea_plantation": 0.60,
    "open_forest": 0.50, "dense_forest": 0.30,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _ramp(value: float, floor: float, ceiling: float) -> float:
    """Linear 0→1 ramp between floor and ceiling."""
    if ceiling <= floor:
        return 0.0
    return _clamp((value - floor) / (ceiling - floor))


# ---------------------------------------------------------------------------
# I/O types
# ---------------------------------------------------------------------------


@dataclass
class FusionInput:
    zone_code: str
    zone_name: str

    model_probability: float            # 0-1, from the XGBoost pipeline

    rainfall_24h: float                 # mm
    rainfall_72h: float                 # mm
    antecedent_rain_15d: float          # mm
    soil_moisture_pct: float            # 0-100
    forecast_24h_mm: float              # mm, from the rainfall trend model
    seasonal_normal_72h: float          # mm, this zone's own 72h baseline

    slope_deg: float
    elevation_m: float
    lithology: str
    land_cover: str

    sensors_total: int = 0
    sensors_active: int = 0
    minutes_since_last_reading: float | None = None
    failed_node_ids: list[str] = field(default_factory=list)

    # Ground truth from a field officer, when one has been on the slope
    # recently. CONFIRMED / DENIED / None.
    field_verdict: str | None = None
    verification_age_hours: float | None = None
    verified_by: str = ""


@dataclass
class ContributingFactor:
    key: str
    text: str
    weight: float                 # 0-1 share of the hazard total
    direction: str                # "increases" | "reduces" | "lowers_confidence"

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "text": self.text,
            "weight": round(self.weight, 3),
            "direction": self.direction,
        }


@dataclass
class FusionResult:
    risk_score: float
    severity: str
    confidence: float
    contributing_factors: list[dict]
    components: dict
    sensor_health: float

    def as_dict(self) -> dict:
        return {
            "risk_score": self.risk_score,
            "severity": self.severity,
            "confidence": self.confidence,
            "contributing_factors": self.contributing_factors,
            "components": self.components,
            "sensor_health": self.sensor_health,
        }


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def severity_for(risk_score: float) -> str:
    for threshold, label in SEVERITY_BANDS:
        if risk_score >= threshold:
            return label
    return "LOW"


def sensor_health_of(total: int, active: int) -> float:
    """Fraction of a zone's nodes reporting. No nodes at all is not 'healthy'."""
    if total <= 0:
        return 0.5
    return _clamp(active / total)


def fuse(inp: FusionInput) -> FusionResult:
    model_p = _clamp(inp.model_probability)

    normal = max(inp.seasonal_normal_72h, 1.0)
    rain_ratio = inp.rainfall_72h / normal

    rain_pressure = _ramp(rain_ratio, RAIN_RATIO_FLOOR, RAIN_RATIO_CEILING)
    saturation_pressure = _ramp(inp.soil_moisture_pct, SATURATION_FLOOR_PCT, SATURATION_CEILING_PCT)
    forecast_pressure = _ramp(inp.forecast_24h_mm, 0.0, FORECAST_CEILING_MM)

    contributions = {
        "model": WEIGHTS["model"] * model_p,
        "rainfall": WEIGHTS["rainfall"] * rain_pressure,
        "saturation": WEIGHTS["saturation"] * saturation_pressure,
        "forecast": WEIGHTS["forecast"] * forecast_pressure,
    }
    hazard = sum(contributions.values())

    verification = _verification_adjustment(inp)
    hazard = _clamp(hazard + verification)

    risk_score = round(hazard * 100.0, 1)
    severity = severity_for(risk_score)

    health = sensor_health_of(inp.sensors_total, inp.sensors_active)
    confidence = _confidence(inp, model_p, rain_pressure, saturation_pressure, health, rain_ratio)

    factors = _explain(
        inp,
        contributions=contributions,
        hazard=hazard,
        rain_ratio=rain_ratio,
        rain_pressure=rain_pressure,
        saturation_pressure=saturation_pressure,
        forecast_pressure=forecast_pressure,
        model_p=model_p,
        health=health,
        verification=verification,
    )

    return FusionResult(
        risk_score=risk_score,
        severity=severity,
        confidence=confidence,
        contributing_factors=[f.as_dict() for f in factors],
        components={
            "model_probability": round(model_p, 4),
            "rain_pressure": round(rain_pressure, 3),
            "saturation_pressure": round(saturation_pressure, 3),
            "forecast_pressure": round(forecast_pressure, 3),
            "rain_ratio_vs_normal": round(rain_ratio, 2),
            "verification_adjustment": round(verification, 3),
            "hazard": round(hazard, 4),
        },
        sensor_health=round(health, 3),
    )


def _verification_adjustment(inp: FusionInput) -> float:
    """Hazard shift from a recent on-site check, decaying as it ages."""
    if not inp.field_verdict or inp.field_verdict == "UNCERTAIN":
        return 0.0
    age = inp.verification_age_hours if inp.verification_age_hours is not None else 0.0
    if age > VERIFICATION_FRESH_HOURS * 4:
        return 0.0
    # Full weight while fresh, tapering to zero over four times that window.
    decay = _clamp(1.0 - max(0.0, age - VERIFICATION_FRESH_HOURS)
                   / (VERIFICATION_FRESH_HOURS * 3))
    base = VERIFICATION_UPLIFT if inp.field_verdict == "CONFIRMED" else VERIFICATION_DENIAL
    return base * decay


def _confidence(
    inp: FusionInput,
    model_p: float,
    rain_pressure: float,
    saturation_pressure: float,
    health: float,
    rain_ratio: float,
) -> float:
    """Confidence in *this* estimate. Never a statement about model accuracy."""
    conf = CONFIDENCE_BASE

    # Thin or missing sensor coverage is the biggest single penalty.
    conf *= 0.62 + 0.38 * health

    # Stale or absent telemetry.
    mins = inp.minutes_since_last_reading
    if mins is None or mins > STALE_TELEMETRY_MINUTES:
        conf *= 0.85

    # Model vs. environment disagreement — if the gauges are screaming and the
    # model is calm (or vice versa) we are less sure of the fused answer.
    environment = (rain_pressure + saturation_pressure) / 2.0
    conf *= 1.0 - 0.30 * abs(model_p - environment)

    # Rainfall far outside anything in the training range is extrapolation.
    if rain_ratio > 3.0:
        conf *= 0.92

    # Someone has actually looked at the slope. Whichever way the verdict went,
    # this estimate rests on more than telemetry.
    if inp.field_verdict in ("CONFIRMED", "DENIED"):
        age = inp.verification_age_hours or 0.0
        if age <= VERIFICATION_FRESH_HOURS * 4:
            conf = 1.0 - (1.0 - conf) * 0.72

    return round(_clamp(conf, CONFIDENCE_MIN, CONFIDENCE_MAX), 3)


def _explain(
    inp: FusionInput,
    *,
    contributions: dict,
    hazard: float,
    rain_ratio: float,
    rain_pressure: float,
    saturation_pressure: float,
    forecast_pressure: float,
    model_p: float,
    health: float,
    verification: float = 0.0,
) -> list[ContributingFactor]:
    """Ranked plain-language factors. Highest contribution first."""
    total = max(hazard, 1e-6)
    out: list[ContributingFactor] = []

    litho = LITHOLOGY_LABELS.get(inp.lithology, inp.lithology.replace("_", " "))
    cover = LAND_COVER_LABELS.get(inp.land_cover, inp.land_cover.replace("_", " "))

    # --- field verification (ground truth outranks everything) -----------
    if abs(verification) > 1e-6:
        who = f" by {inp.verified_by}" if inp.verified_by else ""
        if inp.field_verdict == "CONFIRMED":
            text_ = (f"Slope movement CONFIRMED on site{who} — ground truth, "
                     f"escalated above the modelled estimate")
        else:
            text_ = (f"Field check{who} found no active movement — "
                     f"modelled estimate revised down")
        out.append(ContributingFactor(
            key="field_verification",
            text=text_,
            weight=abs(verification) / total,
            direction="increases" if verification > 0 else "reduces",
        ))

    # --- rainfall --------------------------------------------------------
    if rain_pressure > 0.02:
        out.append(ContributingFactor(
            key="rainfall_72h",
            text=(f"72h rainfall {inp.rainfall_72h:.0f} mm — "
                  f"{rain_ratio:.1f}× the seasonal normal for this zone"),
            weight=contributions["rainfall"] / total,
            direction="increases",
        ))

    # --- soil saturation --------------------------------------------------
    if saturation_pressure > 0.02:
        out.append(ContributingFactor(
            key="soil_moisture",
            text=(f"Soil moisture {inp.soil_moisture_pct:.0f}% — "
                  + ("at or past the saturation threshold, so new rain runs off onto the slope"
                     if inp.soil_moisture_pct >= SATURATION_CEILING_PCT
                     else f"above the {SATURATION_FLOOR_PCT:.0f}% wet-antecedent threshold")),
            weight=contributions["saturation"] / total,
            direction="increases",
        ))

    # --- model / terrain --------------------------------------------------
    terrain_weak = (
        LITHOLOGY_WEAKNESS.get(inp.lithology, 0.6) + LAND_COVER_WEAKNESS.get(inp.land_cover, 0.6)
    ) / 2.0
    if model_p >= 0.5:
        model_text = (
            f"Slope {inp.slope_deg:.0f}° on {litho} under {cover} at {inp.elevation_m:.0f} m — "
            f"terrain closely matches past failure conditions in this belt"
        )
    else:
        model_text = (
            f"Slope {inp.slope_deg:.0f}° on {litho} under {cover} — "
            f"terrain signature only weakly matches past failures"
        )
    out.append(ContributingFactor(
        key="terrain_susceptibility",
        text=model_text,
        weight=contributions["model"] / total,
        direction="increases" if model_p >= 0.35 else "reduces",
    ))

    if terrain_weak >= 0.85 and model_p >= 0.5:
        out.append(ContributingFactor(
            key="lithology",
            text=f"{litho.capitalize()} weathers to a weak regolith that fails readily when saturated",
            weight=0.12 * contributions["model"] / total,
            direction="increases",
        ))

    # --- forecast ---------------------------------------------------------
    if forecast_pressure > 0.02:
        out.append(ContributingFactor(
            key="forecast_24h",
            text=f"24h outlook: a further {inp.forecast_24h_mm:.0f} mm forecast for this zone",
            weight=contributions["forecast"] / total,
            direction="increases",
        ))

    # --- antecedent -------------------------------------------------------
    if inp.antecedent_rain_15d > 250:
        out.append(ContributingFactor(
            key="antecedent_rain",
            text=(f"15-day antecedent rainfall {inp.antecedent_rain_15d:.0f} mm — "
                  f"the slope entered this event already wet"),
            weight=0.10,
            direction="increases",
        ))

    # Rank by contribution, but never let a factor that argues *against* risk
    # head the list — an operator reading the top line should see what is
    # driving the score, not what is holding it down.
    out.sort(key=lambda f: (f.direction == "reduces", -f.weight))

    # --- sensor caveats always ride at the end, ranked separately ---------
    if inp.sensors_total == 0:
        out.append(ContributingFactor(
            key="no_sensors",
            text="No sensor node is installed in this zone — estimate rests on modelled rainfall only, confidence reduced",
            weight=0.0,
            direction="lowers_confidence",
        ))
    elif health < 1.0:
        failed = inp.sensors_total - inp.sensors_active
        nodes = ", ".join(inp.failed_node_ids[:3])
        suffix = f" ({nodes})" if nodes else ""
        out.append(ContributingFactor(
            key="sensor_failure",
            text=(f"{failed} of {inp.sensors_total} sensor nodes in this zone are not reporting{suffix} — "
                  f"confidence reduced accordingly"),
            weight=0.0,
            direction="lowers_confidence",
        ))

    mins = inp.minutes_since_last_reading
    if mins is not None and mins > STALE_TELEMETRY_MINUTES:
        out.append(ContributingFactor(
            key="stale_telemetry",
            text=f"Most recent telemetry is {mins / 60:.1f} h old — confidence reduced",
            weight=0.0,
            direction="lowers_confidence",
        ))

    return out
