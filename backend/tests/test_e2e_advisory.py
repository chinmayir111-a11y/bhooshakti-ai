"""End to end: a citizen submits a report through the public API, nobody
acknowledges it, and 20 minutes later the ladder issues an ADVISORY that is
dispatched on every channel — officials by email/SMS/websocket/push/console,
the zone's registered public by SMS and a voice call."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from .conftest import requires_db

pytestmark = requires_db


@pytest.fixture(autouse=True)
def clean_advisories(tx_db):
    """Advisories left ACTIVE by a demo run would make a new report join them
    instead of issuing its own. Close them inside the test transaction."""
    # Open demo reports would be worked by tick() too and could issue the
    # advisory this test's report then joins: mark them seen for the test.
    tx_db.execute(text("UPDATE citizen_reports SET advisory_alert_id = NULL, acknowledged_at = NOW(), "
                       "acknowledged_by = 'test-fixture' WHERE status = 'PENDING' AND acknowledged_at IS NULL"))
    tx_db.execute(text("UPDATE alerts SET status = 'SUPERSEDED' WHERE tier = 'ADVISORY' AND status = 'ACTIVE'"))
    tx_db.flush()

PNG_1PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
           "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def test_unacknowledged_report_becomes_an_advisory_on_all_channels(client, tx_db, no_siren):
    from app.models import Alert, SensorReading, Severity, ZoneRisk
    from app.services import escalation

    # A zone the scripted demo never touches, with one of its own ACTIVE nodes
    # placed at the zone centroid for this test.
    zone = tx_db.execute(text("SELECT id, centroid_lat AS lat, centroid_lon AS lon FROM zones "
                              "WHERE code = 'AR-03'")).mappings().one()
    node = tx_db.execute(text("SELECT node_id FROM sensor_nodes WHERE zone_id = :z AND status = 'ACTIVE' "
                              "ORDER BY node_id LIMIT 1"), {"z": zone["id"]}).scalar()
    tx_db.execute(text("UPDATE sensor_nodes SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) WHERE node_id = :n"),
                  {"lon": zone["lon"], "lat": zone["lat"], "n": node})
    now = datetime.now(timezone.utc)

    # Evidence worth 60 points: zone HIGH (+30), a tilting sensor nearby (+25),
    # a photo (+5). Not enough for the immediate (85) advisory. Real rain in
    # the last 24 h may add +20; either way the T+20 rule applies.
    tx_db.add(ZoneRisk(zone_id=zone["id"], risk_score=62, severity=Severity.HIGH, confidence=0.7,
                       contributing_factors=[], computed_at=now))
    for minutes, tilt in ((120, 0.2), (20, 1.1)):
        tx_db.add(SensorReading(node_id=node, zone_id=zone["id"],
                                ts=now - timedelta(minutes=minutes), tilt_deg=tilt))
    tx_db.flush()

    from app.models import Subscriber
    tx_db.add_all([Subscriber(phone="+919800000011", zone_id=zone["id"], language="en", source="test"),
                   Subscriber(phone="+919800000012", zone_id=zone["id"], language="hi", source="test")])
    tx_db.flush()

    r = client.post("/reports", json={
        "issue_type": "landslide", "lat": zone["lat"], "lon": zone["lon"],
        "phone": "+919876500000", "photo_base64": PNG_1PX, "language": "en"})
    assert r.status_code == 201, r.text
    body = r.json()
    report_id = body["id"]
    assert body["corroboration_score"] in (60, 80)
    assert {x["key"] for x in body["corroboration_reasons"]} >= {"zone_at_risk", "sensor_anomaly", "photo"}
    assert body["escalation"]["level"] == 1, "T+0: on-duty moderator already notified"
    assert body["escalation"]["advisory_alert_id"] is None

    created = datetime.fromisoformat(body["created_at"])
    mine = lambda acts: [a for a in acts if a["report_id"] == report_id]  # noqa: E731
    assert mine(escalation.tick(tx_db, now=created + timedelta(minutes=19))) == [
        {"report_id": report_id, "action": "escalate", "level": 1}]

    actions = mine(escalation.tick(tx_db, now=created + timedelta(minutes=20, seconds=5)))
    advisory_id = next(a["alert_id"] for a in actions if a["action"] == "advisory")
    alert = tx_db.get(Alert, advisory_id)

    assert alert.tier == "ADVISORY"
    channels = {d.channel for d in alert.deliveries}
    assert channels >= {"console", "websocket", "email", "sms", "push", "voice"}, channels

    public = {"+919800000011", "+919800000012"}                          # AR-03 subscribers (below)
    assert public <= {d.recipient for d in alert.deliveries if d.channel == "sms"}
    assert public <= {d.recipient for d in alert.deliveries if d.channel == "voice"}
    langs = {d.language for d in alert.deliveries if d.channel == "voice"}
    assert langs == {"en", "hi"}, "each subscriber hears their own language"
    assert all(d.status.value in ("SENT", "SIMULATED") for d in alert.deliveries)

    trail = [row[0] for row in tx_db.execute(text(
        "SELECT action FROM audit_log WHERE resource = 'citizen_report' AND resource_id = :i ORDER BY id"
    ), {"i": str(report_id)})]
    assert trail[:3] == ["create", "corroboration_score", "notify_moderator"]
    assert "escalate" in trail and trail[-1] == "auto_advisory"
    detail = tx_db.execute(text(
        "SELECT detail FROM audit_log WHERE action = 'auto_advisory' AND resource_id = :i"
    ), {"i": str(report_id)}).scalar()
    assert detail["corroboration_score"] == body["corroboration_score"] and len(detail["reasons"]) >= 3

    # The public panel and CAP feed both see it.
    esc = client.get("/reports/escalations").json()
    assert any(x["id"] == report_id and x["escalation"]["advisory_alert_id"] == advisory_id for x in esc)
    assert f"bhooshakti-alert-{advisory_id}" in client.get("/api/cap/alerts.xml").text

    from app.config import settings
    (settings.upload_dir / body["photo_path"].rsplit("/", 1)[-1]).unlink(missing_ok=True)
