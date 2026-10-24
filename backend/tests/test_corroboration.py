"""Corroboration score: the pure scoring rules, then the PostGIS evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.corroboration import POINTS, Evidence, score_evidence

from .conftest import requires_db


def _keys(reasons):
    return {r["key"] for r in reasons}


def test_no_evidence_scores_zero():
    score, reasons = score_evidence(Evidence())
    assert score == 0 and reasons == []


def test_each_signal_adds_its_documented_points():
    cases = [
        (Evidence(zone_severity="HIGH", zone_name="Z"), "zone_at_risk", 30),
        (Evidence(zone_severity="CRITICAL", zone_name="Z"), "zone_at_risk", 30),
        (Evidence(rain_24h_mm=90, rain_threshold_mm=60), "rain_above_threshold", 20),
        (Evidence(sensor_anomalies=[{"node_id": "N1", "distance_km": 1.2, "what": "tilt change of 0.8°"}]),
         "sensor_anomaly", 25),
        (Evidence(independent_phones=3), "report_cluster", 25),
        (Evidence(has_photo=True), "photo", 5),
    ]
    for ev, key, pts in cases:
        score, reasons = score_evidence(ev)
        assert score == pts, key
        assert _keys(reasons) == {key}
        assert reasons[0]["points"] == pts == POINTS[key]
        assert reasons[0]["text"], "every reason must be readable"


def test_moderate_zone_and_rain_at_threshold_do_not_count():
    score, _ = score_evidence(Evidence(zone_severity="MODERATE", rain_24h_mm=60, rain_threshold_mm=60))
    assert score == 0


def test_two_phones_are_not_a_cluster():
    assert score_evidence(Evidence(independent_phones=2))[0] == 0


def test_outside_zones_subtracts_and_score_never_goes_negative():
    score, reasons = score_evidence(Evidence(geo_valid=False, has_photo=True))
    assert score == 0
    assert {r["points"] for r in reasons} == {5, -30}


def test_everything_together_is_capped_at_100():
    ev = Evidence(zone_severity="CRITICAL", zone_name="Z", rain_24h_mm=200, rain_threshold_mm=60,
                  sensor_anomalies=[{"node_id": "N1", "distance_km": 0.4, "what": "tilt of 2.0°"}],
                  independent_phones=4, has_photo=True)
    score, reasons = score_evidence(ev)
    assert score == 100
    assert sum(r["points"] for r in reasons) == 105


# --------------------------------------------------------------- database side


@requires_db
def test_cluster_counts_distinct_phones_within_radius_and_window(tx_db):
    from app.models import CitizenReport, ReportStatus
    from app.services import corroboration

    # A zone the scripted demo never touches, so no live demo reports sit nearby.
    zone = tx_db.execute(text("SELECT id, centroid_lat AS lat, centroid_lon AS lon FROM zones "
                              "WHERE code = 'AR-03'")).mappings().one()
    now = datetime.now(timezone.utc)

    def add(phone, dlat=0.0, minutes_ago=0):
        r = CitizenReport(issue_type="landslide", lat=zone["lat"] + dlat, lon=zone["lon"],
                          geom=f"SRID=4326;POINT({zone['lon']} {zone['lat'] + dlat})",
                          phone=phone, zone_id=zone["id"], geo_valid=True,
                          status=ReportStatus.PENDING, created_at=now - timedelta(minutes=minutes_ago))
        tx_db.add(r)
        tx_db.flush()
        return r

    add("+911111111111")
    add("+911111111111")                 # same phone twice: one witness
    add("+912222222222", dlat=0.005)     # ~550 m away
    add("", dlat=0.001)                  # anonymous: cannot be shown independent
    add("+913333333333", dlat=0.05)      # ~5.5 km — outside the 1.5 km radius
    add("+914444444444", minutes_ago=200)  # outside the 60 min window
    assert corroboration.independent_phones(tx_db, zone["lat"], zone["lon"], now) == 2

    add("+915555555555", dlat=-0.004)
    assert corroboration.independent_phones(tx_db, zone["lat"], zone["lon"], now) == 3


@requires_db
def test_sensor_tilt_anomaly_within_2km_is_found(tx_db):
    from app.models import SensorReading
    from app.services import corroboration

    node = tx_db.execute(text("""
        SELECT n.node_id, n.zone_id, ST_Y(n.geom) AS lat, ST_X(n.geom) AS lon
        FROM sensor_nodes n WHERE node_id = 'KB-01'
    """)).mappings().one()
    now = datetime.now(timezone.utc)
    for minutes, tilt in ((90, 0.1), (30, 0.9)):
        tx_db.add(SensorReading(node_id=node["node_id"], zone_id=node["zone_id"],
                                ts=now - timedelta(minutes=minutes), tilt_deg=tilt))
    tx_db.flush()

    near = corroboration.sensor_anomalies(tx_db, node["lat"] + 0.005, node["lon"], now)
    kb = next((a for a in near if a["node_id"] == "KB-01"), None)
    assert kb is not None and "tilt change" in kb["what"]

    far = corroboration.sensor_anomalies(tx_db, node["lat"] + 0.1, node["lon"], now)
    assert far == []


@requires_db
def test_zone_rain_threshold_is_floored(tx_db):
    from app.services import corroboration
    zone_id = tx_db.execute(text("SELECT id FROM zones ORDER BY id LIMIT 1")).scalar()
    assert corroboration.zone_rain_threshold(tx_db, zone_id) >= corroboration.RAIN_THRESHOLD_FLOOR_MM


def test_sos_is_top_priority_evidence():
    from app.services.corroboration import Evidence, score_evidence
    score, reasons = score_evidence(Evidence(is_sos=True, zone_severity="HIGH", zone_name="Z",
                                             rain_24h_mm=80, rain_threshold_mm=60))
    assert score >= 85                      # reaches the immediate-advisory line alone
    assert any(r["key"] == "sos" and r["points"] == 40 for r in reasons)
    plain, _ = score_evidence(Evidence(zone_severity="HIGH", zone_name="Z", rain_24h_mm=80, rain_threshold_mm=60))
    assert plain == score - 40
