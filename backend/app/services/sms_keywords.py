"""Keyword SMS for people without a smartphone or a data connection.

    LS <pincode or village> [what you see]   report a landslide
    LS <lat>,<lon> [what you see]             same, from GPS (the citizen app fills
                                              this in when there is no internet)
    R 45                                      village volunteer: 45 mm in the gauge
                                              since the last reading
    LS 734101 CRACK SPRING                    with warning signs: CRACK SPRING TILT
                                              SOUND STONES SINK (+10 trust each)
    SAFE <pincode or village>                 ask the current risk
    JOIN <pincode or village> [EN|HI|AS|BN|NE]  get that zone's alerts
    STOP                                      stop alerts
    HELP                                      list the keywords

Keywords are case-insensitive and tolerate the punctuation feature-phone
keyboards add ("ls,734101", "Safe 793001."). `parse` is pure; `resolve`
does the database lookup from pincode / place name to a monitored zone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import signs

KEYWORDS = {
    "LS": "report", "LANDSLIDE": "report", "SLIDE": "report",
    "SAFE": "safe", "RISK": "safe",
    "JOIN": "join", "START": "join", "SUBSCRIBE": "join",
    "STOP": "stop", "UNSUBSCRIBE": "stop",
    "HELP": "help", "?": "help",
    "R": "rain", "RAIN": "rain",          # village volunteer gauge: R 45
}
LANG_CODES = {"EN": "en", "HI": "hi", "AS": "as", "BN": "bn", "NE": "ne"}
PINCODE = re.compile(r"^\d{6}$")
# "26.95300,88.32100" or "26.953 88.321": decimal degrees, as the citizen app
# writes them. Only points inside India's box count, so a stray number never does.
COORDS = re.compile(r"(-?\d{1,2}\.\d{2,7})\s*[,; ]\s*(-?\d{2,3}\.\d{2,7})")

HELP_TEXT = ("BHOOSHAKTI [DEMO]: LS <pincode> <what you see> = report landslide. "
             "Add signs: CRACK SPRING TILT SOUND STONES SINK. "
             "SAFE <pincode> = current risk. JOIN <pincode> = get alerts. STOP = stop. "
             "Emergency: call 112.")


@dataclass
class Command:
    intent: str                     # report | safe | join | stop | help | unknown
    pincode: str | None = None
    place: str | None = None        # free-text place when no pincode was given
    detail: str = ""                # the rest of the message
    language: str | None = None     # JOIN ... HI
    lat: float | None = None        # GPS sent instead of a pincode
    lon: float | None = None
    signs: list[str] = field(default_factory=list)   # LS 734101 CRACK SPRING
    mm: float | None = None                          # R 45: mm in the gauge since the last reading
    raw: str = ""


def parse(body: str) -> Command:
    raw = (body or "").strip()
    cleaned = re.sub(r"[,;:.!]+", " ", raw)
    tokens = cleaned.split()
    if not tokens:
        return Command("help", raw=raw)

    intent = KEYWORDS.get(tokens[0].upper())
    if intent is None:
        return Command("unknown", raw=raw)
    rest = tokens[1:]

    cmd = Command(intent, raw=raw)
    if intent == "rain":
        # Read from the raw text: stripping punctuation would turn 12.5 into 12.
        num = re.match(r"^\S+\s+(\d+(?:[.,]\d+)?)\s*(?:mm)?\b", raw, re.IGNORECASE)
        cmd.mm = float(num.group(1).replace(",", ".")) if num else None
        return cmd
    if intent == "report":
        cmd.signs = signs.from_words(rest)
    if intent in ("stop", "help") or not rest:
        return cmd

    # GPS coordinates, read before the punctuation is stripped.
    after = raw.split(None, 1)[1] if len(raw.split(None, 1)) > 1 else ""
    m = COORDS.match(after.strip())
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if 6.0 <= lat <= 37.5 and 68.0 <= lon <= 98.0:
            cmd.lat, cmd.lon = lat, lon
            rest = re.sub(r"[,;:.!]+", " ", after.strip()[m.end():]).split()
            if intent == "join" and rest and rest[-1].upper() in LANG_CODES:
                cmd.language = LANG_CODES[rest[-1].upper()]
                rest = rest[:-1]
            cmd.detail = " ".join(rest)
            return cmd

    if PINCODE.match(rest[0]):
        cmd.pincode = rest[0]
        rest = rest[1:]
    if intent == "join" and rest and rest[-1].upper() in LANG_CODES:
        cmd.language = LANG_CODES[rest[-1].upper()]
        rest = rest[:-1]

    if cmd.pincode:
        cmd.detail = " ".join(rest)
    else:
        # No pincode: the place is the leading words. Which words is decided
        # against the gazetteer in `resolve`, so keep them all for now.
        cmd.place = " ".join(rest)
    return cmd


def resolve(db: Session, cmd: Command) -> dict[str, Any] | None:
    """Pincode or place name -> {pincode, place, district, lat, lon, zone_id}.

    For a free-text place, the longest leading run of words (up to three) that
    names a known place wins, and whatever follows becomes the description:
    "LS Mirik road blocked near school" -> place Mirik, detail "road blocked…".
    """
    if cmd.lat is not None and cmd.lon is not None:
        # Name the spot after the nearest known place, for the reply.
        near = db.execute(text("""
            SELECT pincode, place, district FROM pincodes
            ORDER BY (lat - :la) * (lat - :la) + (lon - :lo) * (lon - :lo) LIMIT 1
        """), {"la": cmd.lat, "lo": cmd.lon}).mappings().first()
        return {"pincode": near["pincode"] if near else "", "place": f"your location (near {near['place']})" if near else "your location",
                "district": near["district"] if near else "", "lat": cmd.lat, "lon": cmd.lon, "zone_id": None}

    if cmd.pincode:
        row = db.execute(text("""
            SELECT pincode, place, district, lat, lon, zone_id FROM pincodes
            WHERE pincode = :p ORDER BY id LIMIT 1
        """), {"p": cmd.pincode}).mappings().first()
        return dict(row) if row else None

    if not cmd.place:
        return None
    words = cmd.place.split()
    for n in range(min(3, len(words)), 0, -1):
        name = " ".join(words[:n])
        row = db.execute(text("""
            SELECT pincode, place, district, lat, lon, zone_id FROM pincodes
            WHERE lower(place) = lower(:n) ORDER BY id LIMIT 1
        """), {"n": name}).mappings().first()
        if row is None:
            v = db.execute(text("""
                SELECT name AS place, district, ST_Y(geom) AS lat, ST_X(geom) AS lon
                FROM villages WHERE lower(name) = lower(:n) LIMIT 1
            """), {"n": name}).mappings().first()
            if v is not None:
                row = {"pincode": "", **dict(v), "zone_id": None}
        if row is not None:
            cmd.detail = " ".join(words[n:])
            return dict(row)
    return None
