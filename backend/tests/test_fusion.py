"""Risk fusion.

Fusion is where the model's probability becomes an operational decision, so
these tests pin the behaviour that matters operationally: bands, monotonicity,
what moves confidence, and whether the explanation is honest about it.
"""
from __future__ import annotations

import pytest

from ml.fusion import (
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    SATURATION_CEILING_PCT,
    VERIFICATION_FRESH_HOURS,
    FusionInput,
    fuse,
    sensor_health_of,
    severity_for,
)


def base(**overrides) -> FusionInput:
    """A quiet, well-instrumented zone. Tests move one thing at a time."""
    defaults = dict(
        zone_code="DJ-04", zone_name="Tindharia–Paglajhora",
        model_probability=0.05,
        rainfall_24h=4.0, rainfall_72h=12.0, antecedent_rain_15d=120.0,
        soil_moisture_pct=45.0, forecast_24h_mm=2.0, seasonal_normal_72h=80.0,
        slope_deg=39.0, elevation_m=860.0,
        lithology="sandstone_shale", land_cover="open_forest",
        sensors_total=3, sensors_active=3, minutes_since_last_reading=5.0,
    )
    defaults.update(overrides)
    return FusionInput(**defaults)


def storm(**overrides) -> FusionInput:
    return base(**{
        "model_probability": 0.92, "rainfall_24h": 210.0, "rainfall_72h": 280.0,
        "antecedent_rain_15d": 900.0, "soil_moisture_pct": 93.0,
        "forecast_24h_mm": 140.0, **overrides,
    })


# --------------------------------------------------------------------- bands


@pytest.mark.parametrize("score,expected", [
    (0.0, "LOW"), (24.9, "LOW"), (25.0, "MODERATE"), (49.9, "MODERATE"),
    (50.0, "HIGH"), (74.9, "HIGH"), (75.0, "CRITICAL"), (100.0, "CRITICAL"),
])
def test_severity_bands_are_inclusive_at_the_lower_bound(score, expected):
    assert severity_for(score) == expected


def test_quiet_conditions_are_low_and_a_storm_is_critical():
    assert fuse(base()).severity == "LOW"
    assert fuse(storm()).severity == "CRITICAL"


def test_risk_score_stays_inside_zero_to_one_hundred():
    extreme = fuse(storm(model_probability=1.0, rainfall_72h=5000.0,
                         soil_moisture_pct=100.0, forecast_24h_mm=999.0,
                         field_verdict="CONFIRMED", verification_age_hours=0.0))
    assert 0.0 <= extreme.risk_score <= 100.0
    assert extreme.severity == "CRITICAL"


# ------------------------------------------------------------- monotonicity


def test_more_rain_never_lowers_the_score():
    scores = [fuse(base(model_probability=0.4, rainfall_72h=mm)).risk_score
              for mm in (0, 40, 80, 160, 320)]
    assert scores == sorted(scores)


def test_wetter_soil_never_lowers_the_score():
    scores = [fuse(base(model_probability=0.4, soil_moisture_pct=pct)).risk_score
              for pct in (20, 50, 65, 80, 95)]
    assert scores == sorted(scores)


def test_a_higher_model_probability_raises_the_score():
    low = fuse(base(model_probability=0.10)).risk_score
    high = fuse(base(model_probability=0.80)).risk_score
    assert high > low


def test_saturated_soil_stops_adding_pressure_past_the_ceiling():
    at = fuse(base(soil_moisture_pct=SATURATION_CEILING_PCT)).risk_score
    beyond = fuse(base(soil_moisture_pct=SATURATION_CEILING_PCT + 8)).risk_score
    assert at == beyond


# ---------------------------------------------------------------- confidence


def test_failed_sensors_reduce_confidence_and_say_so():
    healthy = fuse(storm())
    degraded = fuse(storm(sensors_total=3, sensors_active=1,
                          failed_node_ids=["DJ-04-N01", "DJ-04-N02"]))

    assert degraded.confidence < healthy.confidence
    assert degraded.sensor_health == pytest.approx(1 / 3, abs=1e-3)

    caveats = [f for f in degraded.contributing_factors
               if f["direction"] == "lowers_confidence"]
    assert caveats, "a degraded sensor network must be stated in the factors"
    assert "DJ-04-N01" in caveats[0]["text"]
    assert "2 of 3" in caveats[0]["text"]


def test_a_zone_with_no_sensors_at_all_is_flagged():
    result = fuse(storm(sensors_total=0, sensors_active=0))
    assert result.sensor_health == 0.5
    assert any(f["key"] == "no_sensors" for f in result.contributing_factors)


def test_stale_telemetry_reduces_confidence():
    fresh = fuse(storm(minutes_since_last_reading=5.0))
    stale = fuse(storm(minutes_since_last_reading=600.0))
    assert stale.confidence < fresh.confidence
    assert any(f["key"] == "stale_telemetry" for f in stale.contributing_factors)


def test_model_disagreeing_with_the_gauges_reduces_confidence():
    """Model calm, rain gauges screaming — the fused answer is less certain."""
    agreeing = fuse(storm(model_probability=0.92))
    disagreeing = fuse(storm(model_probability=0.05))
    assert disagreeing.confidence < agreeing.confidence


def test_confidence_is_always_a_usable_probability():
    for case in (base(), storm(), storm(sensors_total=0, sensors_active=0),
                 storm(minutes_since_last_reading=99999.0, model_probability=0.0)):
        result = fuse(case)
        assert CONFIDENCE_MIN <= result.confidence <= CONFIDENCE_MAX


def test_confidence_never_reaches_certainty():
    """No configuration may claim a guaranteed prediction."""
    best = fuse(storm(field_verdict="CONFIRMED", verification_age_hours=0.0,
                      sensors_total=8, sensors_active=8,
                      minutes_since_last_reading=1.0))
    assert best.confidence < 1.0


# -------------------------------------------------------- field verification


def test_a_confirmed_field_check_raises_risk_and_confidence():
    telemetry_only = fuse(storm(model_probability=0.45))
    verified = fuse(storm(model_probability=0.45, field_verdict="CONFIRMED",
                          verification_age_hours=1.0, verified_by="T. Lepcha"))

    assert verified.risk_score > telemetry_only.risk_score
    assert verified.confidence > telemetry_only.confidence

    top = verified.contributing_factors[0]
    assert top["key"] == "field_verification"
    assert "CONFIRMED" in top["text"] and "T. Lepcha" in top["text"]


def test_a_denied_field_check_lowers_risk_but_still_raises_confidence():
    telemetry_only = fuse(storm(model_probability=0.45))
    denied = fuse(storm(model_probability=0.45, field_verdict="DENIED",
                        verification_age_hours=1.0))

    assert denied.risk_score < telemetry_only.risk_score
    # Someone looked. Either way we know more than we did.
    assert denied.confidence > telemetry_only.confidence


def test_a_stale_verification_stops_counting():
    fresh = fuse(storm(model_probability=0.45, field_verdict="CONFIRMED",
                       verification_age_hours=1.0))
    ageing = fuse(storm(model_probability=0.45, field_verdict="CONFIRMED",
                        verification_age_hours=VERIFICATION_FRESH_HOURS * 2))
    expired = fuse(storm(model_probability=0.45, field_verdict="CONFIRMED",
                         verification_age_hours=VERIFICATION_FRESH_HOURS * 9))
    none = fuse(storm(model_probability=0.45))

    assert fresh.risk_score > ageing.risk_score > none.risk_score
    assert expired.risk_score == none.risk_score


def test_an_uncertain_verdict_changes_nothing():
    assert (fuse(storm(field_verdict="UNCERTAIN", verification_age_hours=1.0)).risk_score
            == fuse(storm()).risk_score)


# --------------------------------------------------------------- explanation


def test_every_result_explains_itself_in_plain_language():
    result = fuse(storm())
    assert result.contributing_factors, "a risk score with no explanation is not decision support"
    for f in result.contributing_factors:
        assert f["text"] and not f["text"].endswith("_")
        assert "_" not in f["text"].split(" ")[0], "raw feature names must not leak into the UI"


def test_factors_are_ranked_and_never_led_by_a_mitigating_one():
    factors = fuse(storm(model_probability=0.30)).contributing_factors
    assert factors[0]["direction"] != "reduces"

    # Drivers rank by contribution among themselves; mitigating factors are
    # deliberately pushed below every driver rather than interleaved by weight.
    drivers = [f["weight"] for f in factors if f["direction"] == "increases"]
    assert drivers == sorted(drivers, reverse=True)

    directions = [f["direction"] for f in factors]
    if "reduces" in directions and "increases" in directions:
        assert directions.index("reduces") > max(
            i for i, d in enumerate(directions) if d == "increases")


def test_rainfall_factor_states_the_multiple_of_normal():
    result = fuse(storm(rainfall_72h=240.0, seasonal_normal_72h=80.0))
    rain = next(f for f in result.contributing_factors if f["key"] == "rainfall_72h")
    assert "240 mm" in rain["text"]
    assert "3.0×" in rain["text"]


def test_components_are_exposed_for_transparency():
    c = fuse(storm()).components
    for key in ("model_probability", "rain_pressure", "saturation_pressure",
                "forecast_pressure", "rain_ratio_vs_normal", "hazard"):
        assert key in c


# ------------------------------------------------------------- sensor health


@pytest.mark.parametrize("total,active,expected", [
    (4, 4, 1.0), (4, 2, 0.5), (4, 0, 0.0), (0, 0, 0.5),
])
def test_sensor_health_fraction(total, active, expected):
    assert sensor_health_of(total, active) == pytest.approx(expected)
