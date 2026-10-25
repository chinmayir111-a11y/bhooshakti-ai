"""Gaon Prahari — village volunteers with a manual rain gauge.

GSI's Darjeeling community pilot showed that one trained villager with a cheap
rain gauge, a threshold chart and a whistle can warn a village faster than any
official. This digitises that loop:

    volunteer texts  R 45   (mm since the last reading)
      -> reading stored (source "volunteer gauge"), 24 h total computed
      -> compared with the zone's own rainfall threshold (the one corroboration
         already uses: the zone's 90th-percentile 24 h total, floored)
            below 70 %   reply: reading saved
            >= 70 %      reply: WATCH — keep essentials ready, keep night watch
            >= 100 %     reply: ALERT — move to <safe place> now; the zone's
                         siren topic is triggered and the control room told
      -> a fresh reading is blended into the zone's risk (risk_service)

`level_for` and `is_stale` are pure and unit-tested.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Volunteer, VolunteerRainReading, Zone
from . import corroboration

log = logging.getLogger(__name__)

WATCH_FRACTION = 0.7
FRESH_HOURS = 6          # a reading this recent is blended into the zone's risk
STALE_HOURS = 12         # no reading for this long while it is raining -> grey icon
RAINING_MM_12H = 5.0     # Open-Meteo rain in the zone's last 12 h that counts as "raining"
MAX_READING_MM = 500.0   # anything bigger is a typing mistake, not rain


def level_for(total_24h: float, threshold_mm: float) -> str:
    if threshold_mm <= 0:
        return "none"
    if total_24h >= threshold_mm:
        return "alert"
    if total_24h >= WATCH_FRACTION * threshold_mm:
        return "watch"
    return "none"


def is_stale(last_reading_at: datetime | None, raining: bool, now: datetime) -> bool:
    """Grey icon: it is raining and the volunteer has gone quiet."""
    if not raining:
        return False
    return last_reading_at is None or now - last_reading_at > timedelta(hours=STALE_HOURS)


def normalise_phone(phone: str) -> str:
    """'+91 98765 43210', ' 919876543210' (a form-encoded '+' arrives as a
    space) and '919876543210' all mean +919876543210."""
    p = (phone or "").strip()
    digits = "".join(c for c in p if c.isdigit())
    if not digits:
        return ""
    return "+" + digits if p.startswith("+") or len(digits) >= 12 else digits


def by_phone(db: Session, phone: str) -> Volunteer | None:
    p = normalise_phone(phone)
    if not p:
        return None
    return db.query(Volunteer).filter(Volunteer.phone == p, Volunteer.active.is_(True)).first()


def safe_place_for(db: Session, v: Volunteer) -> str:
    """Where the village goes on ALERT: the volunteer's agreed place, else the
    nearest shelter an officer has not marked unsafe (Task 3), else a fallback."""
    if v.safe_place:
        return v.safe_place
    try:
        row = db.execute(text("""
            SELECT name FROM shelters WHERE NOT unsafe
            ORDER BY ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
            LIMIT 1
        """), {"lat": v.lat, "lon": v.lon}).scalar()
    except Exception:
        db.rollback()
        row = None
    return row or "the nearest safe building away from the slope"


def total_24h(db: Session, volunteer_id: int, at: datetime) -> float:
    return float(db.execute(text("""
        SELECT COALESCE(SUM(mm), 0) FROM volunteer_rain_readings
        WHERE volunteer_id = :v AND read_at > :since AND read_at <= :at
    """), {"v": volunteer_id, "since": at - timedelta(hours=24), "at": at}).scalar() or 0.0)


def zone_raining(db: Session, zone_id: int, now: datetime) -> bool:
    mm = db.execute(text("""
        SELECT COALESCE(SUM(rainfall_mm), 0) FROM rainfall_readings
        WHERE zone_id = :z AND NOT is_forecast AND ts > :since AND ts <= :now
    """), {"z": zone_id, "since": now - timedelta(hours=12), "now": now}).scalar() or 0.0
    return float(mm) >= RAINING_MM_12H


def record(db: Session, v: Volunteer, mm: float, *, channel: str = "sms",
           read_at: datetime | None = None, client_uuid: str | None = None) -> dict[str, Any]:
    """Store one reading, work out the village level, act on it. Returns the
    reading, the level and the SMS reply text."""
    from ..deps import audit
    from ..ws import manager
    from .escalation import SYSTEM

    now = datetime.now(timezone.utc)
    if client_uuid:
        dup = db.query(VolunteerRainReading).filter(VolunteerRainReading.client_uuid == client_uuid).first()
        if dup is not None:                      # offline replay of a reading already stored
            return {"reading": serialise_reading(dup), "level": dup.level, "reply": "Reading already saved.",
                    "duplicate": True}
    if not (0 <= mm <= MAX_READING_MM):
        return {"reading": None, "level": "none",
                "reply": f"BHOOSHAKTI: {mm:g} mm does not look right. Send R and the mm in the gauge, e.g. R 45."}

    read_at = min(read_at or now, now)
    previous = (db.query(VolunteerRainReading).filter(VolunteerRainReading.volunteer_id == v.id)
                .order_by(VolunteerRainReading.read_at.desc()).first())
    reading = VolunteerRainReading(volunteer_id=v.id, zone_id=v.zone_id, mm=round(mm, 1), read_at=read_at,
                                   channel=channel, client_uuid=client_uuid)
    db.add(reading)
    db.flush()
    total = round(total_24h(db, v.id, read_at), 1)
    threshold = corroboration.zone_rain_threshold(db, v.zone_id)
    level = level_for(total, threshold)
    reading.total_24h, reading.level = total, level
    zone = db.get(Zone, v.zone_id)
    place = v.place or (zone.name if zone else "your village")

    # Act only when the level rises (or the previous reading is a day old), so
    # a volunteer reading every hour through one storm is one siren, not ten.
    prev_level = previous.level if previous and now - previous.read_at < timedelta(hours=24) else "none"
    rank = {"none": 0, "watch": 1, "alert": 2}
    rising = rank[level] > rank[prev_level]

    siren = None
    if level == "alert":
        shelter = safe_place_for(db, v)
        reply = (f"BHOOSHAKTI [DEMO] ALERT: {total:.0f} mm in 24 h at {place} (danger level {threshold:.0f} mm). "
                 f"Move to {shelter} now. Blow the whistle. Control room informed.")
        if rising and zone is not None:
            from ..mqtt_client import ingest
            siren = ingest.publish(f"{settings.mqtt_siren_prefix}/{zone.id}", {
                "zone_id": zone.id, "zone_code": zone.code, "action": "sound", "duration_s": 120,
                "source": "volunteer gauge", "volunteer": v.name, "rain_24h_mm": total,
                "issued_at": now.isoformat(), "demo_data": True,
            })
            manager.activity(f"Village gauge ALERT — {place}: {total:.0f} mm in 24 h ({v.name}). "
                             f"Siren {'sounded' if siren else 'NOT sent (broker down)'}.",
                             kind="warning", zone_id=v.zone_id, lat=v.lat, lon=v.lon)
    elif level == "watch":
        reply = (f"BHOOSHAKTI [DEMO] WATCH: {total:.0f} mm in 24 h at {place} "
                 f"(danger level {threshold:.0f} mm). Keep essentials ready, keep night watch.")
        if rising:
            manager.activity(f"Village gauge WATCH — {place}: {total:.0f} mm in 24 h ({v.name})",
                             kind="advisory", zone_id=v.zone_id, lat=v.lat, lon=v.lon)
    else:
        reply = (f"BHOOSHAKTI [DEMO]: saved {mm:g} mm. {total:.0f} mm in 24 h at {place}; "
                 f"watch at {WATCH_FRACTION * threshold:.0f} mm, danger at {threshold:.0f} mm.")
        manager.activity(f"Village gauge — {place}: {mm:g} mm ({v.name})", kind="sensor",
                         zone_id=v.zone_id, lat=v.lat, lon=v.lon)

    audit(db, SYSTEM, "volunteer_reading", "volunteer", v.id,
          detail={"mm": mm, "total_24h": total, "threshold_mm": threshold, "level": level,
                  "channel": channel, "siren": siren}, commit=False)
    db.commit()

    # The zone's risk picks the gauge up straight away.
    if zone is not None:
        from .risk_service import compute_zone_risk
        try:
            compute_zone_risk(db, zone, trigger="volunteer-gauge", raise_alerts=True)
            db.commit()
        except Exception:
            log.exception("rescore after volunteer reading failed")
            db.rollback()
    return {"reading": serialise_reading(reading), "level": level, "reply": reply,
            "threshold_mm": threshold, "total_24h": total, "siren": siren}


def fresh_gauge(db: Session, zone_id: int, now: datetime | None = None) -> dict[str, Any] | None:
    """The newest volunteer 24 h total in this zone, if read in the last FRESH_HOURS."""
    now = now or datetime.now(timezone.utc)
    row = db.execute(text("""
        SELECT r.total_24h, r.read_at, v.name, v.place
        FROM volunteer_rain_readings r JOIN volunteers v ON v.id = r.volunteer_id
        WHERE r.zone_id = :z AND r.read_at > :since AND v.active
        ORDER BY r.read_at DESC LIMIT 1
    """), {"z": zone_id, "since": now - timedelta(hours=FRESH_HOURS)}).mappings().first()
    return dict(row) if row else None


def serialise_reading(r: VolunteerRainReading) -> dict[str, Any]:
    return {"id": r.id, "volunteer_id": r.volunteer_id, "zone_id": r.zone_id, "mm": r.mm,
            "read_at": r.read_at.isoformat(), "total_24h": r.total_24h, "level": r.level,
            "channel": r.channel, "source": r.source}


def listing(db: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    """Every active volunteer with their last reading and stale flag, for the map."""
    now = now or datetime.now(timezone.utc)
    out = []
    for v in db.query(Volunteer).filter(Volunteer.active.is_(True)).order_by(Volunteer.id).all():
        last = (db.query(VolunteerRainReading).filter(VolunteerRainReading.volunteer_id == v.id)
                .order_by(VolunteerRainReading.read_at.desc()).first())
        zone = db.get(Zone, v.zone_id)
        raining = zone_raining(db, v.zone_id, now)
        out.append({
            "id": v.id, "name": v.name, "phone_last4": v.phone[-4:], "zone_id": v.zone_id,
            "zone_name": zone.name if zone else None, "place": v.place, "lat": v.lat, "lon": v.lon,
            "safe_place": v.safe_place, "simulated": v.simulated,
            "last_mm": last.mm if last else None, "last_at": last.read_at.isoformat() if last else None,
            "total_24h": round(total_24h(db, v.id, now), 1), "level": last.level if last else "none",
            "raining": raining, "stale": is_stale(last.read_at if last else None, raining, now),
        })
    return out


def zone_readings(db: Session, zone_id: int, hours: int = 72) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (db.query(VolunteerRainReading).filter(VolunteerRainReading.zone_id == zone_id,
                                                  VolunteerRainReading.read_at > since)
            .order_by(VolunteerRainReading.read_at).all())
    return [serialise_reading(r) for r in rows]
