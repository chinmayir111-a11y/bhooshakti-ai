"""Gaon Prahari: the R 45 keyword, the village levels, stale gauges, and the
whole loop from an SMS to a reply, a siren and a blended zone risk."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.services.sms_keywords import parse
from app.services.volunteers import is_stale, level_for

from .conftest import requires_db


def test_r_keyword_reads_the_gauge():
    assert parse("R 45").intent == "rain" and parse("R 45").mm == 45
    assert parse("r 12.5").mm == 12.5
    assert parse("RAIN 30mm").mm == 30
    assert parse("R").mm is None and parse("R lots").mm is None


def test_village_levels_follow_the_zone_threshold():
    assert level_for(40, 100) == "none"
    assert level_for(70, 100) == "watch"        # 70 % of the threshold
    assert level_for(99.9, 100) == "watch"
    assert level_for(100, 100) == "alert"
    assert level_for(500, 0) == "none"          # no threshold, no guess


def test_stale_only_when_raining_and_quiet_for_twelve_hours():
    now = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
    assert not is_stale(now - timedelta(hours=30), raining=False, now=now)
    assert not is_stale(now - timedelta(hours=11), raining=True, now=now)
    assert is_stale(now - timedelta(hours=13), raining=True, now=now)
    assert is_stale(None, raining=True, now=now)


@requires_db
def test_sms_reading_to_alert_siren_and_blended_risk(tx_db, no_siren, monkeypatch):
    from app.models import Volunteer, Zone
    from app.routers.inbound import handle_sms
    from app.services import corroboration, risk_service

    monkeypatch.setattr(corroboration, "zone_rain_threshold", lambda db, z: 60.0)
    zone = tx_db.query(Zone).filter(Zone.code == "DJ-04").one()
    v = Volunteer(name="Test Volunteer", phone="+919999988877", zone_id=zone.id, place="Testgaon",
                  lat=zone.centroid_lat, lon=zone.centroid_lon, safe_place="Test School", simulated=True)
    tx_db.add(v); tx_db.flush()

    assert "saved 20 mm" in handle_sms(tx_db, v.phone, "R 20")
    watch = handle_sms(tx_db, v.phone, "R 25")                 # 45 mm in 24 h >= 70 % of 60
    assert watch.startswith("BHOOSHAKTI [DEMO] WATCH") and "night watch" in watch
    alert = handle_sms(tx_db, v.phone, "R 20")                 # 65 mm >= 60
    assert "ALERT" in alert and "Move to Test School now" in alert
    assert [t for t, _ in no_siren] == [f"bhooshakti/siren/{zone.id}"], "one siren, on the rise to ALERT"
    handle_sms(tx_db, v.phone, "R 5")                          # still ALERT: no second siren
    assert len(no_siren) == 1

    reasons = risk_service.compute_zone_risk(tx_db, zone, raise_alerts=False)["contributing_factors"]
    assert reasons[0]["key"] == "volunteer_gauge" and "Village gauge at Testgaon: 70 mm in 24 h" in reasons[0]["text"]

    assert "not registered" in handle_sms(tx_db, "+910000000000", "R 30")
