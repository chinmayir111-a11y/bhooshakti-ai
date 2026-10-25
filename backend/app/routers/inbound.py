"""Inbound SMS and missed-call / IVR — reporting with no smartphone and no data.

    POST /api/inbound/sms    Twilio (form: From, Body) or MSG91 (sender/mobile, content/message)
    POST /api/inbound/ivr    Exotel-style call events (CallSid, From, Digits, RecordingUrl)

A Twilio webhook is answered in TwiML, so Twilio delivers the reply itself.
Anything else is answered with JSON and the reply goes out through the SMS
channel (a logged stub until SMS_PROVIDER is configured).
"""
from __future__ import annotations

import logging
from typing import Any
from xml.sax.saxutils import escape

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Principal, audit
from ..models import Subscriber, Zone
from ..notify import templates
from ..notify.channels import VOICE_LOCALE, SmsChannel, VoiceChannel
from ..services import sms_keywords, spatial
from ..services.media import save_audio, save_audio_bytes
from . import reports

log = logging.getLogger("bhooshakti.inbound")
router = APIRouter(prefix="/api/inbound", tags=["offline channels"])

INBOUND = Principal(user_id=None, username="inbound", role="public")


async def _fields(request: Request) -> dict[str, Any]:
    ctype = request.headers.get("content-type", "")
    data: dict[str, Any] = dict(request.query_params)
    if "json" in ctype:
        try:
            body = await request.json()
            if isinstance(body, dict):
                data.update(body)
        except Exception:
            pass
    elif "form" in ctype:
        form = await request.form()
        data.update({k: v for k, v in form.items() if isinstance(v, str)})
    return data


def _first(d: dict, *keys: str) -> str:
    for k in keys:
        if d.get(k):
            return str(d[k]).strip()
    return ""


def _zone_severity(db: Session, zone_id: int | None) -> tuple[str | None, str | None]:
    if not zone_id:
        return None, None
    row = db.execute(text("""
        SELECT z.name, r.severity::text AS severity FROM zones z
        LEFT JOIN LATERAL (SELECT severity FROM zone_risk WHERE zone_id = z.id
                           ORDER BY computed_at DESC, id DESC LIMIT 1) r ON TRUE
        WHERE z.id = :z
    """), {"z": zone_id}).mappings().first()
    return (row["severity"], row["name"]) if row else (None, None)


def _locate(db: Session, loc: dict) -> tuple[float, float, int | None]:
    """Place coordinates, snapped into the pincode's zone when the post office
    itself sits just outside the polygon — the report is about that zone."""
    lat, lon = float(loc["lat"]), float(loc["lon"])
    found = spatial.locate_point(db, lat, lon)
    if found["zone_id"]:
        return lat, lon, found["zone_id"]
    if loc.get("zone_id"):
        z = db.get(Zone, loc["zone_id"])
        return z.centroid_lat, z.centroid_lon, z.id
    return lat, lon, None


def handle_sms(db: Session, sender: str, body: str) -> str:
    """Parse, act, and return the reply text. Shared by every gateway format."""
    cmd = sms_keywords.parse(body)
    reply: str
    detail: dict[str, Any] = {"from": sender, "intent": cmd.intent, "body": body[:300]}

    if cmd.intent == "help":
        reply = sms_keywords.HELP_TEXT
    elif cmd.intent == "unknown":
        reply = "Sorry, not understood. " + sms_keywords.HELP_TEXT
    elif cmd.intent == "stop":
        n = db.query(Subscriber).filter(Subscriber.phone == sender, Subscriber.active.is_(True)) \
              .update({Subscriber.active: False})
        reply = ("BHOOSHAKTI [DEMO]: alerts stopped." if n else
                 "BHOOSHAKTI [DEMO]: this number was not subscribed.")
    else:
        loc = sms_keywords.resolve(db, cmd)
        if loc is None:
            where = cmd.pincode or cmd.place or "(none)"
            reply = (f"BHOOSHAKTI [DEMO]: place '{where}' not found. Send a 6-digit pincode, "
                     f"e.g. {cmd.raw.split()[0].upper() if cmd.raw else 'LS'} 734101.")
        else:
            lat, lon, zone_id = _locate(db, loc)
            detail.update({"pincode": loc.get("pincode"), "place": loc["place"], "zone_id": zone_id})
            if cmd.intent == "safe":
                sev, _ = _zone_severity(db, zone_id)
                reply = "BHOOSHAKTI [DEMO]: " + templates.safety_line(sev, loc["place"])
            elif cmd.intent == "join":
                if not zone_id:
                    reply = f"BHOOSHAKTI [DEMO]: {loc['place']} is not in a monitored zone yet."
                else:
                    sub = db.query(Subscriber).filter(Subscriber.phone == sender,
                                                      Subscriber.zone_id == zone_id).first()
                    if sub is None:
                        sub = Subscriber(phone=sender, zone_id=zone_id, source="sms")
                        db.add(sub)
                    sub.active = True
                    sub.pincode = loc.get("pincode") or ""
                    sub.language = cmd.language or sub.language or "en"
                    reply = (f"BHOOSHAKTI [DEMO]: registered for landslide alerts near "
                             f"{loc['place']}. Reply STOP to end.")
            else:   # report
                r = reports.submit(
                    db, issue_type="landslide", lat=lat, lon=lon,
                    description=f"[SMS] {cmd.detail}".strip(), phone=sender,
                    channel="sms", principal=INBOUND, signs=cmd.signs,
                )
                reply = (f"BHOOSHAKTI [DEMO]: report #{r.id} near {loc['place']} received. "
                         f"Officers alerted. If in danger move away from the slope. Call 112.")
                detail["report_id"] = r.id

    detail["reply"] = reply
    audit(db, INBOUND, "inbound_sms", "sms", sender, detail=detail, commit=False)
    db.commit()
    return reply


@router.post("/sms", summary="Inbound keyword SMS (Twilio / MSG91 webhook)")
async def inbound_sms(request: Request, db: Session = Depends(get_db)):
    data = await _fields(request)
    sender = _first(data, "From", "from", "sender", "mobile", "msisdn")
    body = _first(data, "Body", "body", "content", "message", "text")
    if not sender:
        return JSONResponse({"error": "no sender number"}, status_code=400)

    reply = handle_sms(db, sender, body)

    if "MessageSid" in data or "SmsSid" in data or "From" in data:
        twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(reply)}</Message></Response>'
        return Response(twiml, media_type="application/xml")
    delivery = SmsChannel().send_text(sender, reply)
    return {"reply": reply, "delivery": {"status": delivery.status, "detail": delivery.detail},
            "demo_data": True}


# ---------------------------------------------------------------------------
# Missed call / IVR
# ---------------------------------------------------------------------------


def _say(text_: str, lang: str = "en") -> str:
    return f'<Say language="{VOICE_LOCALE.get(lang, "en-IN")}">{escape(text_)}</Say>'


def _xml(inner: str) -> Response:
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>',
                    media_type="application/xml")


def _subscriber(db: Session, phone: str) -> Subscriber | None:
    return db.query(Subscriber).filter(Subscriber.phone == phone, Subscriber.active.is_(True)) \
             .order_by(Subscriber.id.desc()).first()


def callback_script(db: Session, sub: Subscriber) -> str:
    zone = db.get(Zone, sub.zone_id)
    sev, _ = _zone_severity(db, sub.zone_id)
    place = zone.name if zone else "your area"
    return (templates.safety_line(sev, place, sub.language) +
            " To report a landslide, press 1 after this message.")


@router.post("/ivr", summary="Missed call / IVR events (Exotel-style webhook)")
async def inbound_ivr(request: Request, db: Session = Depends(get_db)):
    """One endpoint for the whole call flow, switched on what the provider sends:

      no Digits, no recording  -> missed call: call back with the zone's risk
      Digits=1                 -> prompt and record a 20 s voice note
      RecordingUrl / recording_base64 -> store the note as a citizen report
    """
    data = await _fields(request)
    caller = _first(data, "From", "CallFrom", "from", "caller")
    event = _first(data, "event").lower()
    digits = _first(data, "Digits", "digits").strip('"')
    recording_url = _first(data, "RecordingUrl", "recording_url")
    recording_b64 = _first(data, "recording_base64")
    call_sid = _first(data, "CallSid", "call_sid")
    sub = _subscriber(db, caller) if caller else None

    if recording_url or recording_b64 or event == "recording":
        path = ""
        if recording_b64:
            path = save_audio(recording_b64, prefix="ivr")
        elif recording_url.startswith(("http://", "https://")):
            try:
                auth = ((settings.exotel_api_key, settings.exotel_api_token)
                        if settings.exotel_api_key else None)
                r = httpx.get(recording_url, auth=auth, timeout=20, follow_redirects=True)
                r.raise_for_status()
                path = save_audio_bytes(r.content, prefix="ivr")
            except Exception as exc:
                log.warning("could not fetch IVR recording %s: %s", recording_url, exc)
        if sub is None:
            audit(db, INBOUND, "inbound_ivr", "ivr", caller,
                  detail={"event": "recording", "registered": False, "call_sid": call_sid})
            return _xml(_say("This number is not registered. Send J O I N and your pincode by SMS."))
        zone = db.get(Zone, sub.zone_id)
        report = reports.submit(
            db, issue_type="voice_report", lat=zone.centroid_lat, lon=zone.centroid_lon,
            description="[IVR voice report] located by the caller's registered zone",
            phone=caller, language=sub.language, voice_path=path, channel="ivr",
            principal=INBOUND,
        )
        audit(db, INBOUND, "inbound_ivr", "ivr", caller,
              detail={"event": "recording", "report_id": report.id, "voice": path,
                      "call_sid": call_sid})
        return _xml(_say(f"Thank you. Your report number {report.id} has been sent to the "
                         f"district officers. If you are in danger, move away from the slope.",
                         sub.language))

    if digits == "1" or event == "digits":
        action = f"{settings.public_api_url}/api/inbound/ivr?event=recording"
        audit(db, INBOUND, "inbound_ivr", "ivr", caller,
              detail={"event": "digits", "digits": digits, "call_sid": call_sid})
        lang = sub.language if sub else "en"
        return _xml(_say("After the beep, say where the landslide is and what you see. "
                         "You have twenty seconds.", lang)
                    + f'<Record maxLength="20" playBeep="true" action="{escape(action)}"/>')

    # Missed call.
    if sub is None:
        reply = ("BHOOSHAKTI [DEMO]: this number is not registered for alerts. "
                 "SMS JOIN <pincode> to register, then give a missed call to hear your risk.")
        delivery = SmsChannel().send_text(caller, reply) if caller else None
        audit(db, INBOUND, "inbound_ivr", "ivr", caller,
              detail={"event": "missed_call", "registered": False, "call_sid": call_sid})
        return {"action": "sms", "reply": reply,
                "delivery": delivery.status if delivery else None, "demo_data": True}

    script = callback_script(db, sub)
    result = VoiceChannel([caller]).call(caller, script, sub.language)
    audit(db, INBOUND, "inbound_ivr", "ivr", caller,
          detail={"event": "missed_call", "registered": True, "zone_id": sub.zone_id,
                  "script": script, "callback": result.status, "call_sid": call_sid})
    return {"action": "callback", "script": script, "language": sub.language,
            "callback": {"status": result.status, "detail": result.detail},
            "next": f"{settings.public_api_url}/api/inbound/ivr/callback?phone={caller}",
            "demo_data": True}


@router.get("/ivr/callback", summary="Call-back script (risk + press 1 to report)")
def ivr_callback(phone: str, db: Session = Depends(get_db)):
    sub = _subscriber(db, phone)
    if sub is None:
        return _xml(_say("This number is not registered for alerts."))
    action = f"{settings.public_api_url}/api/inbound/ivr?event=digits"
    return _xml(f'<Gather numDigits="1" timeout="8" action="{escape(action)}">'
                f'{_say(callback_script(db, sub), sub.language)}</Gather>')


@router.get("/ivr/say", summary="Speak arbitrary alert text (outbound voice flow)")
def ivr_say(text: str, lang: str = "en"):
    return _xml(_say(text[:600], lang) + '<Pause length="1"/>' + _say(text[:600], lang))
