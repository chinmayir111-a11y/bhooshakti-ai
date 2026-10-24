"""End to end: a citizen submits a report through the public API, nobody
acknowledges it, and 20 minutes later the ladder issues an ADVISORY that is
dispatched on every channel — officials by email/SMS/websocket/push/console,
the zone's registered public by SMS and a voice call."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from .conftest import requires_db

pytestmark = requires_db

PNG_1PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
           "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def test_unacknowledged_report_becomes_an_advisory_on_all_channels(client, tx_db, no_siren):
    from app.models import Alert, SensorReading, Severity, ZoneRisk
    from app.services import escalation

    zone = tx_db.execute(text("SELECT id, centroid_lat AS lat, centroid_lon AS lon FROM zones "
                              "WHERE code = 'DJ-04'")).mappings().one()
    now = datetime.now(timezone.utc)

    # Evidence worth 60 points: zone HIGH (+30), a tilting sensor nearby (+25),
    # a photo (+5). Not enough for the immediate (85) advisory.
    tx_db.add(ZoneRisk(zone_id=zone["id"], risk_score=62, severity=Severity.HIGH, confidence=0.7,
                       contributing_factors=[], computed_at=now))
    for minutes, tilt in ((120, 0.2), (20, 1.1)):
        tx_db.add(SensorReading(node_id="KB-01", zone_id=zone["id"],
                                ts=now - timedelta(minutes=minutes), tilt_deg=tilt))
    tx_db.flush()

    r = client.post("/reports", json={
        "issue_type": "landslide", "lat": zone["lat"], "lon": zone["lon"],
        "phone": "+919876500000", "photo_base64": PNG_1PX, "language": "en"})
    assert r.status_code == 201, r.text
    body = r.json()
    report_id = body["id"]
    assert body["corroboration_score"] == 60
    assert {x["key"] for x in body["corroboration_reasons"]} == {"zone_at_risk", "sensor_anomaly", "photo"}
    assert body["escalation"]["level"] == 1, "T+0: on-duty moderator already notified"
    assert body["escalation"]["advisory_alert_id"] is None

    created = datetime.fromisoformat(body["created_at"])
    assert escalation.tick(tx_db, now=created + timedelta(minutes=19)) == [
        {"report_id": report_id, "action": "escalate", "level": 1}]

    actions = escalation.tick(tx_db, now=created + timedelta(minutes=20, seconds=5))
    advisory_id = next(a["alert_id"] for a in actions if a["action"] == "advisory")
    alert = tx_db.get(Alert, advisory_id)

    assert alert.tier == "ADVISORY"
    channels = {d.channel for d in alert.deliveries}
    assert channels >= {"console", "websocket", "email", "sms", "push", "voice"}, channels

    public = {"+919800000001", "+919800000002", "+919800000003"}      # DJ-04 subscribers
    assert public <= {d.recipient for d in alert.deliveries if d.channel == "sms"}
    assert public <= {d.recipient for d in alert.deliveries if d.channel == "voice"}
    langs = {d.language for d in alert.deliveries if d.channel == "voice"}
    assert langs == {"en", "hi", "ne"}, "each subscriber hears their own language"
    assert all(d.status.value in ("SENT", "SIMULATED") for d in alert.deliveries)

    trail = [row[0] for row in tx_db.execute(text(
        "SELECT action FROM audit_log WHERE resource = 'citizen_report' AND resource_id = :i ORDER BY id"
    ), {"i": str(report_id)})]
    assert trail[:3] == ["create", "corroboration_score", "notify_moderator"]
    assert "escalate" in trail and trail[-1] == "auto_advisory"
    detail = tx_db.execute(text(
        "SELECT detail FROM audit_log WHERE action = 'auto_advisory' AND resource_id = :i"
    ), {"i": str(report_id)}).scalar()
    assert detail["corroboration_score"] == 60 and len(detail["reasons"]) == 3

    # The public panel and CAP feed both see it.
    esc = client.get("/reports/escalations").json()
    assert any(x["id"] == report_id and x["escalation"]["advisory_alert_id"] == advisory_id for x in esc)
    assert f"bhooshakti-alert-{advisory_id}" in client.get("/api/cap/alerts.xml").text

    from app.config import settings
    (settings.upload_dir / body["photo_path"].rsplit("/", 1)[-1]).unlink(missing_ok=True)
