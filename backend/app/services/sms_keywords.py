"""Keyword SMS for people without a smartphone or a data connection.

    LS <pincode or village> [what you see]   report a landslide
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
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

KEYWORDS = {
    "LS": "report", "LANDSLIDE": "report", "SLIDE": "report",
    "SAFE": "safe", "RISK": "safe",
    "JOIN": "join", "START": "join", "SUBSCRIBE": "join",
    "STOP": "stop", "UNSUBSCRIBE": "stop",
    "HELP": "help", "?": "help",
}
LANG_CODES = {"EN": "en", "HI": "hi", "AS": "as", "BN": "bn", "NE": "ne"}
PINCODE = re.compile(r"^\d{6}$")

HELP_TEXT = ("BHOOSHAKTI [DEMO]: LS <pincode> <what you see> = report landslide. "
             "SAFE <pincode> = current risk. JOIN <pincode> = get alerts. STOP = stop. "
             "Emergency: call 112.")


@dataclass
class Command:
    intent: str                     # report | safe | join | stop | help | unknown
    pincode: str | None = None
    place: str | None = None        # free-text place when no pincode was given
    detail: str = ""                # the rest of the message
    language: str | None = None     # JOIN ... HI
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
    if intent in ("stop", "help") or not rest:
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
