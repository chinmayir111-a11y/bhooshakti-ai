"""Risk computation: model → forecast → fusion → persistence → alerting.

Pipeline per zone:
  1. pull the zone's hourly rainfall / soil-moisture series
  2. derive 24h / 72h / 15-day totals and the zone's own seasonal 72h normal
  3. XGBoost susceptibility probability from the feature contract
  4. 24h rainfall outlook
  5. sensor availability from sensor_nodes
  6. ml.fusion.fuse(...) -> score / severity / confidence / factors
  7. persist a zone_risk row, and raise an alert if the band crossed into
     HIGH or CRITICAL
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert, Severity, Zone, ZoneRisk
from ..notify import AlertPayload, dispatch
from ..ws import (
    EVENT_ALERT_DELIVERY,
    EVENT_ALERT_NEW,
    EVENT_RISK_UPDATE,
    EVENT_SUMMARY,
    manager,
)
from ml.features import FeatureRow, build_frame
from ml.fusion import FusionInput, fuse
from ml.rainfall_trend import forecast_24h, seasonal_normal_72h, window_totals
from . import spatial

log = logging.getLogger("bhooshakti.risk")

ALERT_SEVERITIES = {Severity.HIGH, Severity.CRITICAL}
# Don't re-alert the same zone at the same band within this window.
ALERT_COOLDOWN_MINUTES = 20


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------


class ModelRegistry:
    """Holds the trained pipeline. Loaded once at API startup."""

    def __init__(self) -> None:
        self.model: Any = None
        self.meta: dict = {}
        self.loaded = False
        self.load_error: str | None = None

    def load(self) -> None:
        import json

        import joblib

        path = settings.model_file
        if not path.exists():
            self.load_error = (
                f"No trained model at {path}. Run `python scripts/train.py`. "
                f"Falling back to a heuristic susceptibility estimate."
            )
            log.warning(self.load_error)
            return
        try:
            self.model = joblib.load(path)
            if settings.model_meta_file.exists():
                self.meta = json.loads(settings.model_meta_file.read_text())
            self.loaded = True
            log.info("susceptibility model loaded: %s (%s)",
                     self.meta.get("model_version", "?"), path.name)
        except Exception as exc:
            self.load_error = f"{type(exc).__name__}: {exc}"
            log.exception("failed to load model")

    def probability(self, row: FeatureRow) -> float:
        """P(slope failure) for one zone-instant."""
        if not self.loaded or self.model is None:
            return _heuristic_probability(row)
        try:
            frame = build_frame([row])
            return float(self.model.predict_proba(frame)[0, 1])
        except Exception:
            log.exception("model inference failed — using heuristic fallback")
            return _heuristic_probability(row)

    @property
    def version(self) -> str:
        return self.meta.get("model_version", "heuristic-fallback" if not self.loaded else "v1")


def _heuristic_probability(row: FeatureRow) -> float:
    """Transparent fallback so the API still runs before `train.py` is executed.

    Deliberately crude and clearly labelled — the model version reported
    alongside any risk computed this way is `heuristic-fallback`.
    """
    slope = min(max((row.slope_deg - 15.0) / 30.0, 0.0), 1.0)
    rain = min(row.rainfall_72h / 250.0, 1.0)
    soil = min(max((row.soil_moisture_pct - 50.0) / 40.0, 0.0), 1.0)
    ante = min(row.antecedent_rain_15d / 600.0, 1.0)
    return round(min(0.05 + 0.30 * slope + 0.36 * rain + 0.22 * soil + 0.12 * ante, 0.98), 4)


registry = ModelRegistry()


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------


def _zone_series(db: Session, zone_id: int, days: int = 30) -> tuple[list[float], list[float], datetime | None]:
    """Trailing OBSERVED series for a zone, oldest first.

    Forecast rows share these tables, so both filters below matter: without
    them a "trailing 24h rainfall" would include tomorrow's forecast and every
    risk score in the system would run hot.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # For each elapsed hour take the best estimate available: a real
    # observation if we have one, otherwise the forecast that was issued for
    # that hour. Forecasts age into the past between weather refreshes, and
    # excluding them outright leaves a widening hole at the recent end of the
    # series — precisely the hours that drive a 24h total — which makes every
    # risk score drift low. Preferring observations keeps the ordering right;
    # DISTINCT ON picks the first row per hour under that ordering.
    rain = [float(r[0]) for r in db.execute(text("""
        SELECT rainfall_mm FROM (
            SELECT DISTINCT ON (ts) ts, rainfall_mm
            FROM rainfall_readings
            WHERE zone_id = :z AND ts >= :since AND ts <= :now
            ORDER BY ts, is_forecast ASC
        ) best ORDER BY ts
    """), {"z": zone_id, "since": since, "now": now})]
    soil = [float(r[0]) for r in db.execute(text("""
        SELECT moisture_pct FROM (
            SELECT DISTINCT ON (ts) ts, moisture_pct
            FROM soil_moisture_readings
            WHERE zone_id = :z AND ts >= :since AND ts <= :now
            ORDER BY ts, is_forecast ASC
        ) best ORDER BY ts
    """), {"z": zone_id, "since": since, "now": now})]
    # Deliberately observations only: this feeds the staleness penalty on
    # confidence, so it must measure how old the real data is, not how far
    # the forecast reaches.
    last_ts = db.execute(text("""
        SELECT MAX(ts) FROM rainfall_readings
        WHERE zone_id = :z AND NOT is_forecast
    """), {"z": zone_id}).scalar()
    return rain, soil, last_ts


def _observed_forecast_24h(db: Session, zone_id: int) -> float | None:
    """Next 24h of rainfall from the cached Open-Meteo forecast.

    A real numerical weather forecast beats extrapolating our own rain gauge,
    so it is preferred whenever it is cached. Returns None when no forecast
    rows are stored, and the statistical nowcast takes over.
    """
    now = datetime.now(timezone.utc)
    row = db.execute(text("""
        SELECT COALESCE(SUM(rainfall_mm), 0) AS mm, COUNT(*) AS hours
        FROM rainfall_readings
        WHERE zone_id = :z AND is_forecast
          AND ts > :now AND ts <= :horizon
    """), {"z": zone_id, "now": now, "horizon": now + timedelta(hours=24)}).mappings().one()
    if int(row["hours"]) < 12:      # too sparse to trust as a 24h total
        return None
    return round(float(row["mm"]), 1)


def _sensor_state(db: Session, zone_id: int) -> dict[str, Any]:
    row = db.execute(text("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status = 'ACTIVE') AS active,
               MAX(last_seen) AS last_seen
        FROM sensor_nodes WHERE zone_id = :z
    """), {"z": zone_id}).mappings().one()
    failed = [r[0] for r in db.execute(text("""
        SELECT node_id FROM sensor_nodes
        WHERE zone_id = :z AND status <> 'ACTIVE' ORDER BY node_id
    """), {"z": zone_id})]

    minutes = None
    if row["last_seen"] is not None:
        last = row["last_seen"]
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60.0

    return {
        "total": int(row["total"]),
        "active": int(row["active"]),
        "failed_node_ids": failed,
        "minutes_since_last_reading": minutes,
    }


def _latest_verification(db: Session, zone_id: int) -> dict[str, Any]:
    """Most recent field verification for this zone, with its age."""
    row = db.execute(text("""
        SELECT verdict::text AS verdict, officer_name, observed_at
        FROM field_reports WHERE zone_id = :z
        ORDER BY observed_at DESC, id DESC LIMIT 1
    """), {"z": zone_id}).mappings().first()
    if row is None:
        return {"verdict": None, "age_hours": None, "officer": ""}

    observed = row["observed_at"]
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - observed).total_seconds() / 3600.0
    return {"verdict": row["verdict"], "age_hours": age, "officer": row["officer_name"] or ""}


def _latest_severity(db: Session, zone_id: int) -> Severity | None:
    row = db.execute(text("""
        SELECT severity::text FROM zone_risk
        WHERE zone_id = :z ORDER BY computed_at DESC, id DESC LIMIT 1
    """), {"z": zone_id}).first()
    return Severity(row[0]) if row else None


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------


def compute_zone_risk(db: Session, zone: Zone, trigger: str = "scheduled",
                      raise_alerts: bool = True) -> dict[str, Any]:
    rain, soil, last_ts = _zone_series(db, zone.id)
    totals = window_totals(rain)
    soil_now = soil[-1] if soil else 0.0
    real_forecast = _observed_forecast_24h(db, zone.id)
    if real_forecast is not None:
        forecast_mm, forecast_method = real_forecast, "open-meteo"
    else:
        forecast_mm, forecast_method = forecast_24h(rain)
    normal_72 = seasonal_normal_72h(rain)
    sensors = _sensor_state(db, zone.id)
    verification = _latest_verification(db, zone.id)

    row = FeatureRow(
        rainfall_24h=totals["rainfall_24h"],
        rainfall_72h=totals["rainfall_72h"],
        antecedent_rain_15d=totals["antecedent_rain_15d"],
        soil_moisture_pct=soil_now,
        slope_deg=zone.slope_deg,
        aspect_deg=zone.aspect_deg,
        elevation_m=zone.elevation_m,
        lithology=zone.lithology,
        land_cover=zone.land_cover,
    )
    probability = registry.probability(row)

    result = fuse(FusionInput(
        zone_code=zone.code,
        zone_name=zone.name,
        model_probability=probability,
        rainfall_24h=totals["rainfall_24h"],
        rainfall_72h=totals["rainfall_72h"],
        antecedent_rain_15d=totals["antecedent_rain_15d"],
        soil_moisture_pct=soil_now,
        forecast_24h_mm=forecast_mm,
        seasonal_normal_72h=normal_72,
        slope_deg=zone.slope_deg,
        elevation_m=zone.elevation_m,
        lithology=zone.lithology,
        land_cover=zone.land_cover,
        sensors_total=sensors["total"],
        sensors_active=sensors["active"],
        minutes_since_last_reading=sensors["minutes_since_last_reading"],
        failed_node_ids=sensors["failed_node_ids"],
        field_verdict=verification["verdict"],
        verification_age_hours=verification["age_hours"],
        verified_by=verification["officer"],
    ))

    previous = _latest_severity(db, zone.id)
    severity = Severity(result.severity)

    zr = ZoneRisk(
        zone_id=zone.id,
        risk_score=result.risk_score,
        severity=severity,
        confidence=result.confidence,
        contributing_factors=result.contributing_factors,
        model_probability=probability,
        rainfall_24h=totals["rainfall_24h"],
        rainfall_72h=totals["rainfall_72h"],
        antecedent_rain_15d=totals["antecedent_rain_15d"],
        soil_moisture_pct=soil_now,
        forecast_24h_mm=forecast_mm,
        sensor_health=result.sensor_health,
        model_version=registry.version,
        trigger=trigger,
    )
    db.add(zr)
    db.flush()

    payload = {
        "zone_id": zone.id,
        "zone_code": zone.code,
        "zone_name": zone.name,
        "district": zone.district,
        "state": zone.state,
        "risk_score": result.risk_score,
        "severity": result.severity,
        "previous_severity": previous.value if previous else None,
        "confidence": result.confidence,
        "contributing_factors": result.contributing_factors,
        "components": result.components,
        "rainfall_24h": totals["rainfall_24h"],
        "rainfall_72h": totals["rainfall_72h"],
        "antecedent_rain_15d": totals["antecedent_rain_15d"],
        "soil_moisture_pct": round(soil_now, 1),
        "forecast_24h_mm": forecast_mm,
        "forecast_method": forecast_method,
        "seasonal_normal_72h": round(normal_72, 1),
        "sensor_health": result.sensor_health,
        "field_verdict": verification["verdict"],
        "verified_by": verification["officer"],
        "sensors_total": sensors["total"],
        "sensors_active": sensors["active"],
        "model_version": registry.version,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "demo_data": True,
    }

    escalated = severity in ALERT_SEVERITIES and (previous is None or _rank(severity) > _rank(previous))
    if raise_alerts and escalated:
        alert = raise_alert(db, zone, result.risk_score, result.confidence,
                            severity, result.contributing_factors, source=trigger)
        payload["alert_id"] = alert.id if alert else None

    manager.publish_threadsafe(EVENT_RISK_UPDATE, payload)
    return payload


def _rank(sev: Severity) -> int:
    return {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}[sev.value]


def recompute_all(db: Session, trigger: str = "manual",
                  raise_alerts: bool = True) -> list[dict[str, Any]]:
    out = []
    for zone in db.query(Zone).order_by(Zone.id).all():
        out.append(compute_zone_risk(db, zone, trigger=trigger, raise_alerts=raise_alerts))
    db.commit()
    manager.publish_threadsafe(EVENT_SUMMARY, spatial.dashboard_summary(db))
    return out


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------


def _in_cooldown(db: Session, zone_id: int, severity: Severity) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ALERT_COOLDOWN_MINUTES)
    return db.execute(text("""
        SELECT 1 FROM alerts
        WHERE zone_id = :z AND severity = :sev AND created_at > :cutoff
        LIMIT 1
    """), {"z": zone_id, "sev": severity.value, "cutoff": cutoff}).first() is not None


def raise_alert(db: Session, zone: Zone, risk_score: float, confidence: float,
                severity: Severity, factors: list[dict], source: str = "auto",
                language: str = "en", force: bool = False) -> Alert | None:
    if not force and _in_cooldown(db, zone.id, severity):
        log.info("alert suppressed (cooldown): %s %s", zone.code, severity.value)
        return None

    roads = spatial.roads_intersecting_zone(db, zone.id)
    villages = spatial.villages_in_zone(db, zone.id)

    from ..notify import templates

    payload = AlertPayload(
        alert_id=None,
        zone_id=zone.id,
        zone_code=zone.code,
        zone_name=zone.name,
        district=zone.district,
        state=zone.state,
        severity=severity.value,
        risk_score=risk_score,
        confidence=confidence,
        contributing_factors=factors,
        language=language,
        deep_link=f"{settings.public_dashboard_url}/?zone={zone.id}",
        affected_roads=[r["name"] for r in roads[:4]],
        affected_villages=[v["name"] for v in villages[:6]],
        source=source,
    )
    payload.title = templates.subject(payload)
    payload.message = templates.plain_text(payload)

    alert = Alert(
        zone_id=zone.id,
        zone_name=zone.name,
        severity=severity,
        risk_score=risk_score,
        confidence=confidence,
        title=payload.title,
        message=payload.message,
        contributing_factors=factors,
        language=language,
        source=source,
    )
    db.add(alert)
    db.flush()

    results = dispatch(db, alert, payload)
    db.commit()

    manager.publish_threadsafe(EVENT_ALERT_NEW, {
        "id": alert.id,
        "zone_id": zone.id,
        "zone_code": zone.code,
        "zone_name": zone.name,
        "district": zone.district,
        "state": zone.state,
        "severity": severity.value,
        "risk_score": risk_score,
        "confidence": confidence,
        "contributing_factors": factors,
        "title": payload.title,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "affected_roads": payload.affected_roads,
        "affected_villages": payload.affected_villages,
        "source": source,
        "demo_data": True,
    })
    manager.publish_threadsafe(EVENT_ALERT_DELIVERY, {
        "alert_id": alert.id,
        "deliveries": [
            {"channel": r.channel, "recipient": r.recipient,
             "status": r.status, "detail": r.detail}
            for r in results
        ],
    })
    return alert


# ---------------------------------------------------------------------------
# Zone detail for the dashboard drawer
# ---------------------------------------------------------------------------


def zone_detail(db: Session, zone: Zone, sparkline_hours: int = 72) -> dict[str, Any]:
    latest = db.execute(text("""
        SELECT risk_score, severity::text AS severity, confidence, contributing_factors,
               rainfall_24h, rainfall_72h, antecedent_rain_15d, soil_moisture_pct,
               forecast_24h_mm, sensor_health, model_version, computed_at, trigger,
               model_probability
        FROM zone_risk WHERE zone_id = :z
        ORDER BY computed_at DESC, id DESC LIMIT 1
    """), {"z": zone.id}).mappings().first()

    spark = [
        {"ts": r["ts"].isoformat(), "rainfall_mm": float(r["rainfall_mm"]),
         "soil_moisture_pct": float(r["moisture_pct"]) if r["moisture_pct"] is not None else None}
        for r in db.execute(text("""
            SELECT r.ts, r.rainfall_mm, s.moisture_pct
            FROM rainfall_readings r
            LEFT JOIN soil_moisture_readings s
              ON s.zone_id = r.zone_id AND s.ts = r.ts
            WHERE r.zone_id = :z
            ORDER BY r.ts DESC LIMIT :n
        """), {"z": zone.id, "n": sparkline_hours}).mappings()
    ][::-1]

    risk = dict(latest) if latest else None
    if risk and risk.get("computed_at") is not None:
        risk["computed_at"] = risk["computed_at"].isoformat()

    return {
        "id": zone.id,
        "code": zone.code,
        "name": zone.name,
        "district": zone.district,
        "state": zone.state,
        "centroid": [zone.centroid_lat, zone.centroid_lon],
        "terrain": {
            "slope_deg": zone.slope_deg,
            "aspect_deg": zone.aspect_deg,
            "elevation_m": zone.elevation_m,
            "lithology": zone.lithology,
            "land_cover": zone.land_cover,
            "area_km2": zone.area_km2,
            "population": zone.population,
        },
        "risk": risk,
        "sparkline": spark,
        "roads": spatial.roads_intersecting_zone(db, zone.id),
        "villages": spatial.villages_in_zone(db, zone.id),
        "bridges": spatial.bridges_in_zone(db, zone.id),
        "sensors": spatial.sensors_in_zone(db, zone.id),
        "citizen_reports": spatial.reports_in_zone(db, zone.id),
        "field_reports": spatial.field_reports_in_zone(db, zone.id),
        "demo_data": True,
    }
