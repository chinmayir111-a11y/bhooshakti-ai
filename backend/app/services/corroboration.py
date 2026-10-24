"""Corroboration score for citizen reports: how much independent evidence
backs a public report up, 0-100, with the plain-language reasons.

The score is not a probability that the report is true. It is a count of
independent signals that point the same way, weighted by how hard each one
is to fake:

    report falls inside a zone currently HIGH/CRITICAL            +30
    24h observed rainfall (Open-Meteo) above the zone threshold   +20
    a sensor node within 2 km shows a tilt or saturation anomaly
      in the last 6h                                              +25
    >=3 independent reports (different phone numbers) within
      1.5 km and 60 min                                           +25
    photo attached                                                 +5
    location outside every monitored zone (geo_valid false)       -30

`score_evidence` is pure and unit-tested; `gather_evidence` is the PostGIS
side that fills it in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

POINTS = {
    "zone_at_risk": 30,
    "rain_above_threshold": 20,
    "sensor_anomaly": 25,
    "report_cluster": 25,
    "photo": 5,
    "outside_zones": -30,
}

SENSOR_RADIUS_M = 2000.0
SENSOR_WINDOW_H = 6
CLUSTER_RADIUS_M = 1500.0
CLUSTER_WINDOW_MIN = 60
CLUSTER_MIN_PHONES = 3

# A tilt reading is an anomaly when the node has rotated this far within the
# window, or sits past the absolute limit. A soil reading is an anomaly at
# field saturation. Thresholds are typical of inclinometer early-warning
# practice for shallow slides; they are configuration, not physics.
TILT_DELTA_DEG = 0.5
TILT_ABS_DEG = 1.5
SOIL_SATURATION_PCT = 90.0

# Zone rainfall threshold: the 90th percentile of the zone's own rolling 24h
# totals over the cached history, floored so a dry month cannot make a
# drizzle look extreme. Without history the fallback applies.
RAIN_THRESHOLD_FLOOR_MM = 40.0
RAIN_THRESHOLD_FALLBACK_MM = 60.0


@dataclass
class Evidence:
    zone_name: str | None = None
    zone_severity: str | None = None
    rain_24h_mm: float | None = None
    rain_threshold_mm: float | None = None
    sensor_anomalies: list[dict[str, Any]] = field(default_factory=list)
    independent_phones: int = 0
    has_photo: bool = False
    geo_valid: bool = True


def score_evidence(e: Evidence) -> tuple[float, list[dict[str, Any]]]:
    """Pure: evidence -> (score 0-100, reasons). Every reason carries its points."""
    reasons: list[dict[str, Any]] = []

    def add(key: str, text_: str) -> None:
        reasons.append({"key": key, "points": POINTS[key], "text": text_})

    if e.zone_severity in ("HIGH", "CRITICAL"):
        add("zone_at_risk", f"Inside {e.zone_name or 'a zone'}, currently rated {e.zone_severity}")
    if (e.rain_24h_mm is not None and e.rain_threshold_mm is not None
            and e.rain_24h_mm > e.rain_threshold_mm):
        add("rain_above_threshold",
            f"{e.rain_24h_mm:.0f} mm of rain in the last 24h (Open-Meteo) — above this "
            f"zone's {e.rain_threshold_mm:.0f} mm threshold")
    if e.sensor_anomalies:
        a = e.sensor_anomalies[0]
        more = f" (+{len(e.sensor_anomalies) - 1} more)" if len(e.sensor_anomalies) > 1 else ""
        add("sensor_anomaly",
            f"Sensor {a['node_id']} {a['distance_km']:.1f} km away shows {a['what']} "
            f"in the last {SENSOR_WINDOW_H}h{more}")
    if e.independent_phones >= CLUSTER_MIN_PHONES:
        add("report_cluster",
            f"{e.independent_phones} independent reports (different phone numbers) within "
            f"{CLUSTER_RADIUS_M / 1000:.1f} km in {CLUSTER_WINDOW_MIN} min")
    if e.has_photo:
        add("photo", "Photo attached")
    if not e.geo_valid:
        add("outside_zones", "Location is outside every monitored zone")

    total = sum(r["points"] for r in reasons)
    return float(max(0, min(100, total))), reasons


# ---------------------------------------------------------------------------
# Evidence from the database
# ---------------------------------------------------------------------------


def zone_rain_threshold(db: Session, zone_id: int) -> float:
    row = db.execute(text("""
        WITH hourly AS (
            SELECT DISTINCT ON (ts) ts, rainfall_mm
            FROM rainfall_readings
            WHERE zone_id = :z AND NOT is_forecast
              AND ts > NOW() - INTERVAL '30 days'
            ORDER BY ts, source
        ), rolling AS (
            SELECT SUM(rainfall_mm) OVER (ORDER BY ts ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS r24,
                   COUNT(*) OVER () AS n
            FROM hourly
        )
        SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY r24) AS p90, MAX(n) AS n FROM rolling
    """), {"z": zone_id}).mappings().first()
    if not row or row["p90"] is None or (row["n"] or 0) < 48:
        return RAIN_THRESHOLD_FALLBACK_MM
    return round(max(RAIN_THRESHOLD_FLOOR_MM, float(row["p90"])), 1)


def observed_rain_24h(db: Session, zone_id: int, now: datetime) -> float | None:
    row = db.execute(text("""
        SELECT SUM(rainfall_mm) AS mm, COUNT(*) AS n FROM (
            SELECT DISTINCT ON (ts) ts, rainfall_mm FROM rainfall_readings
            WHERE zone_id = :z AND NOT is_forecast
              AND ts > :now - INTERVAL '24 hours' AND ts <= :now
            ORDER BY ts, source
        ) h
    """), {"z": zone_id, "now": now}).mappings().first()
    if not row or not row["n"]:
        return None
    return round(float(row["mm"] or 0.0), 1)


def sensor_anomalies(db: Session, lat: float, lon: float, now: datetime) -> list[dict[str, Any]]:
    rows = db.execute(text("""
        SELECT n.node_id,
               ST_Distance(n.geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) / 1000.0 AS km,
               MAX(r.tilt_deg) AS tilt_max, MIN(r.tilt_deg) AS tilt_min,
               MAX(r.soil_moisture_pct) AS soil_max
        FROM sensor_nodes n
        JOIN sensor_readings r ON r.node_id = n.node_id
        WHERE ST_DWithin(n.geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius)
          AND r.ts > :since AND r.ts <= :now
        GROUP BY n.node_id, n.geom
        ORDER BY km
    """), {"lat": lat, "lon": lon, "radius": SENSOR_RADIUS_M,
           "since": now - timedelta(hours=SENSOR_WINDOW_H), "now": now}).mappings().all()

    out = []
    for r in rows:
        tilt_max, tilt_min, soil = r["tilt_max"], r["tilt_min"], r["soil_max"]
        what = None
        if tilt_max is not None and tilt_min is not None and (tilt_max - tilt_min) >= TILT_DELTA_DEG:
            what = f"tilt change of {tilt_max - tilt_min:.1f}°"
        elif tilt_max is not None and tilt_max >= TILT_ABS_DEG:
            what = f"tilt of {tilt_max:.1f}°"
        elif soil is not None and soil >= SOIL_SATURATION_PCT:
            what = f"soil saturation of {soil:.0f}%"
        if what:
            out.append({"node_id": r["node_id"], "distance_km": round(float(r["km"]), 2), "what": what})
    return out


def independent_phones(db: Session, lat: float, lon: float, at: datetime) -> int:
    """Distinct non-empty phone numbers reporting within the cluster window.
    A report with no number cannot be shown to be independent, so it does not
    count — that is what stops one person submitting five times."""
    return int(db.execute(text("""
        SELECT COUNT(DISTINCT phone) FROM citizen_reports
        WHERE phone <> ''
          AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius)
          AND created_at BETWEEN :start AND :end
    """), {"lat": lat, "lon": lon, "radius": CLUSTER_RADIUS_M,
           "start": at - timedelta(minutes=CLUSTER_WINDOW_MIN),
           "end": at + timedelta(minutes=CLUSTER_WINDOW_MIN)}).scalar() or 0)


def _zone_state(db: Session, zone_id: int) -> tuple[str | None, str | None]:
    row = db.execute(text("""
        SELECT z.name, r.severity::text AS severity FROM zones z
        LEFT JOIN LATERAL (
            SELECT severity FROM zone_risk WHERE zone_id = z.id
            ORDER BY computed_at DESC, id DESC LIMIT 1
        ) r ON TRUE
        WHERE z.id = :z
    """), {"z": zone_id}).mappings().first()
    return (row["name"], row["severity"]) if row else (None, None)


def gather_evidence(db: Session, report, now: datetime | None = None) -> Evidence:
    now = now or datetime.now(timezone.utc)
    created = report.created_at or now
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    e = Evidence(has_photo=bool(report.photo_path), geo_valid=bool(report.geo_valid))
    if report.zone_id:
        e.zone_name, e.zone_severity = _zone_state(db, report.zone_id)
        e.rain_24h_mm = observed_rain_24h(db, report.zone_id, now)
        e.rain_threshold_mm = zone_rain_threshold(db, report.zone_id)
    e.sensor_anomalies = sensor_anomalies(db, report.lat, report.lon, now)
    e.independent_phones = independent_phones(db, report.lat, report.lon, created)
    return e


def score_report(db: Session, report, now: datetime | None = None) -> tuple[float, list[dict]]:
    """Score and store on the report. Returns (score, reasons)."""
    score, reasons = score_evidence(gather_evidence(db, report, now))
    report.corroboration_score = score
    report.corroboration_reasons = reasons
    return score, reasons
