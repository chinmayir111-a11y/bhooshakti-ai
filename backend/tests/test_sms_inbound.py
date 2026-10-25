"""Keyword SMS parser, pincode lookup, and the inbound SMS / IVR webhooks."""
from __future__ import annotations

import base64

import pytest
from sqlalchemy import text

from app.services.sms_keywords import parse

from .conftest import requires_db

# ------------------------------------------------------------------ parser


@pytest.mark.parametrize("body,intent,pin,place,detail", [
    ("LS 734101 big crack on the road", "report", "734101", None, "big crack on the road"),
    ("ls,734101", "report", "734101", None, ""),
    ("Landslide 796001 houses buried", "report", "796001", None, "houses buried"),
    ("LS Mirik road blocked", "report", None, "Mirik road blocked", ""),
    ("SAFE 793001.", "safe", "793001", None, ""),
    ("safe  Gangtok", "safe", None, "Gangtok", ""),
    ("JOIN 734223", "join", "734223", None, ""),
    ("STOP", "stop", None, None, ""),
    ("help", "help", None, None, ""),
    ("", "help", None, None, ""),
    ("hello there", "unknown", None, None, ""),
])
def test_parse(body, intent, pin, place, detail):
    c = parse(body)
    assert (c.intent, c.pincode, c.place, c.detail) == (intent, pin, place, detail)


def test_join_takes_a_language_code():
    c = parse("JOIN 734223 NE")
    assert c.intent == "join" and c.pincode == "734223" and c.language == "ne"


def test_five_digit_number_is_not_a_pincode():
    c = parse("LS 73410 crack")
    assert c.pincode is None and c.place == "73410 crack"


# ---------------------------------------------------------- pincode lookup


@requires_db
def test_pincode_resolves_to_its_zone(tx_db):
    from app.services.sms_keywords import resolve
    loc = resolve(tx_db, parse("SAFE 734101"))
    zone = tx_db.execute(text("SELECT id FROM zones WHERE code = 'DJ-01'")).scalar()
    assert loc["place"] == "Darjeeling" and loc["zone_id"] == zone


@requires_db
def test_place_name_resolves_and_leaves_the_rest_as_detail(tx_db):
    from app.services.sms_keywords import resolve
    cmd = parse("LS mirik road blocked near school")
    loc = resolve(tx_db, cmd)
    assert loc["place"] == "Mirik"
    assert cmd.detail == "road blocked near school"


@requires_db
def test_unknown_pincode_resolves_to_nothing(tx_db):
    from app.services.sms_keywords import resolve
    assert resolve(tx_db, parse("SAFE 000000")) is None


@requires_db
def test_pincode_outside_zones_has_no_zone(tx_db):
    from app.services.sms_keywords import resolve
    loc = resolve(tx_db, parse("SAFE 797001"))
    assert loc["place"] == "Kohima" and loc["zone_id"] is None


@requires_db
def test_geo_check_offers_the_nearest_pincode_for_the_sms_fallback(client):
    r = client.get("/reports/geo-check?lat=26.852&lon=88.327").json()     # Tindharia post office
    assert r["nearest_pincode"] == "734223" and r["nearest_pincode_place"] == "Tindharia"
    far = client.get("/reports/geo-check?lat=15.0&lon=88.0").json()         # Bay of Bengal
    assert far["nearest_pincode"] is None


@requires_db
def test_public_pincode_risk_returns_coordinates_for_gps_less_reports(client):
    r = client.get("/public/pincode/734223").json()
    assert r["place"] == "Tindharia" and r["pincode"] == "734223"
    assert 26.8 < r["lat"] < 26.9 and 88.3 < r["lon"] < 88.4
    assert client.get("/public/pincode/000000").status_code == 404


# --------------------------------------------------------------- webhooks


@requires_db
def test_twilio_ls_creates_a_report_and_replies_in_twiml(client, tx_db, no_siren):
    r = client.post("/api/inbound/sms", data={"From": "+919811111111", "Body": "LS 734223 slope came down",
                                              "MessageSid": "SM123"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert "<Message>" in r.text and "received" in r.text
    row = tx_db.execute(text("""
        SELECT channel, phone, description, zone_id, corroboration_score
        FROM citizen_reports WHERE phone = '+919811111111'
    """)).mappings().one()
    assert row["channel"] == "sms" and "slope came down" in row["description"]
    assert row["zone_id"] is not None


def test_gps_coordinates_are_read_before_punctuation_is_stripped():
    c = parse("LS 26.95300,88.32100 big crack")
    assert (c.intent, c.lat, c.lon, c.pincode, c.detail) == ("report", 26.953, 88.321, None, "big crack")
    assert parse("JOIN 26.95,88.32 HI").language == "hi"
    # Not a place in India: treated as words, never as a location.
    assert parse("LS 1.5,2.5 x").lat is None


@requires_db
def test_offline_gps_sms_lands_in_the_right_zone(client, tx_db, no_siren):
    """The citizen app with no internet sends GPS, not a pincode."""
    r = client.post("/api/inbound/sms", json={"sender": "+919855555555", "message": "LS 26.95300,88.32100 Landslide"})
    assert "received" in r.json()["reply"] and "your location" in r.json()["reply"]
    row = tx_db.execute(text("""
        SELECT r.channel, z.code FROM citizen_reports r JOIN zones z ON z.id = r.zone_id
        WHERE r.phone = '+919855555555'
    """)).mappings().one()
    assert dict(row) == {"channel": "sms", "code": "DJ-04"}


@requires_db
def test_msg91_safe_replies_with_current_risk_as_json(client):
    r = client.post("/api/inbound/sms", json={"sender": "919822222222", "content": "SAFE 734101"})
    body = r.json()
    assert r.status_code == 200
    assert "Darjeeling" in body["reply"] and "risk" in body["reply"].lower()
    assert body["delivery"]["status"] in ("SIMULATED", "SENT")


@requires_db
def test_join_then_stop(client, tx_db):
    client.post("/api/inbound/sms", json={"from": "+919833333333", "text": "JOIN 796001 HI"})
    sub = tx_db.execute(text("SELECT language, active, source FROM subscribers WHERE phone = '+919833333333'")
                        ).mappings().one()
    assert dict(sub) == {"language": "hi", "active": True, "source": "sms"}
    r = client.post("/api/inbound/sms", json={"from": "+919833333333", "text": "STOP"})
    assert "stopped" in r.json()["reply"]
    assert tx_db.execute(text("SELECT active FROM subscribers WHERE phone = '+919833333333'")).scalar() is False


@requires_db
def test_join_outside_zones_is_refused_politely(client):
    r = client.post("/api/inbound/sms", json={"from": "+919844444444", "text": "JOIN 797001"})
    assert "not in a monitored zone" in r.json()["reply"]


@requires_db
def test_missed_call_from_registered_number_calls_back_with_risk(client):
    r = client.post("/api/inbound/ivr", data={"CallSid": "C1", "From": "+919800000003"})
    body = r.json()
    assert body["action"] == "callback"
    assert "press 1" in body["script"].lower()
    assert body["callback"]["status"] in ("SIMULATED", "SENT")


@requires_db
def test_missed_call_from_unknown_number_gets_join_instructions(client):
    r = client.post("/api/inbound/ivr", data={"CallSid": "C2", "From": "+919855555555"})
    assert r.json()["action"] == "sms" and "JOIN" in r.json()["reply"]


@requires_db
def test_press_1_prompts_a_20s_recording(client):
    r = client.post("/api/inbound/ivr", data={"CallSid": "C3", "From": "+919800000003", "Digits": "1"})
    assert '<Record maxLength="20"' in r.text


@requires_db
def test_voice_note_becomes_a_report_stored_like_a_photo(client, tx_db, no_siren):
    wav = b"RIFF" + b"\x00" * 40           # minimal RIFF container header
    r = client.post("/api/inbound/ivr", data={
        "CallSid": "C4", "From": "+919800000003",
        "recording_base64": base64.b64encode(wav).decode()})
    assert "Thank you" in r.text
    row = tx_db.execute(text("""
        SELECT issue_type, channel, voice_note_path FROM citizen_reports
        WHERE phone = '+919800000003' ORDER BY id DESC LIMIT 1
    """)).mappings().one()
    assert row["issue_type"] == "voice_report" and row["channel"] == "ivr"
    assert row["voice_note_path"].startswith("/uploads/ivr-") and row["voice_note_path"].endswith(".wav")
    from app.config import settings
    (settings.upload_dir / row["voice_note_path"].rsplit("/", 1)[-1]).unlink(missing_ok=True)


def test_public_risk_reports_last_observed_hour_of_rain(client):
    r = client.get("/public/pincode/734223").json()
    assert "rain_last_hour_mm" in r
    assert r["rain_last_hour_mm"] is None or r["rain_last_hour_mm"] >= 0


def test_warning_signs_are_read_from_an_sms_report():
    from app.services.sms_keywords import parse
    c = parse("LS 734101 crack, SPRING near school stones")
    assert c.intent == "report" and c.pincode == "734101"
    assert c.signs == ["crack", "spring", "stones"]
    assert parse("LS 26.95300,88.32100 SINK tilt").signs == ["tilt", "sinking"]
    assert parse("SAFE 734101 CRACK").signs == [], "only reports carry signs"


@requires_db
def test_one_phone_cannot_flood_the_gateway(tx_db, monkeypatch):
    from app.routers import inbound
    monkeypatch.setattr(inbound, "SMS_PER_HOUR", 3)
    phone = "+919811100099"
    for _ in range(3):
        assert "too many" not in inbound.handle_sms(tx_db, phone, "HELP")
    assert "too many messages" in inbound.handle_sms(tx_db, phone, "HELP")
