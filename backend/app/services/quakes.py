"""Earthquake trigger. The North-East is India's highest seismic zone and
shaking weakens slopes before the rain arrives.

Every 15 min the free USGS GeoJSON feed (M4.5+, past week, no key) is fetched,
filtered to a box around the North-East and cached. In risk fusion, a quake of
M >= 4.5 within 50 km in the last 72 h adds a bounded boost that fades to
nothing over 72 h, with a plain reason. If the feed cannot be reached nothing
is invented: only quakes already cached count, and the health page says
"earthquake feed unavailable". `boost_points`, `km` are pure and tested.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import session_scope

log = logging.getLogger(__name__)

FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
BOX = (20.5, 30.5, 87.0, 98.5)        # lat min, lat max, lon min, lon max (NER + 50 km and neighbours)
MIN_MAG, RADIUS_KM, WINDOW_H = 4.5, 50.0, 72.0
MAX_BOOST = 15.0                       # risk points, at most, from one quake
INTERVAL_S = 15 * 60


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def boost_points(mag: float, distance_km: float, age_h: float) -> float:
    """Bigger and closer quakes count more; the effect fades linearly to zero
    at 72 h and is capped at MAX_BOOST risk points."""
    if mag < MIN_MAG or distance_km > RADIUS_KM or age_h < 0 or age_h > WINDOW_H:
        return 0.0
    size = min(1.0, 0.4 + 0.3 * (mag - MIN_MAG))            # M4.5 -> 0.4, M6.5+ -> 1.0
    near = 1.0 - 0.5 * (distance_km / RADIUS_KM)             # at 50 km half as strong
    fade = 1.0 - age_h / WINDOW_H
    return round(MAX_BOOST * size * near * fade, 1)


def _ago(hours: float) -> str:
    return f"{hours:.0f} h ago" if hours < 36 else f"{hours / 24:.0f} days ago"


def for_zone(db: Session, lat: float, lon: float, now: datetime | None = None) -> dict[str, Any] | None:
    """The strongest qualifying quake for a point: boost and the reason text."""
    now = now or datetime.now(timezone.utc)
    rows = db.execute(text("""
        SELECT usgs_id, mag, place, occurred_at, lat, lon, depth_km FROM earthquakes
        WHERE occurred_at > :since AND mag >= :m
          AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r)
    """), {"since": now - timedelta(hours=WINDOW_H), "m": MIN_MAG, "lat": lat, "lon": lon,
           "r": RADIUS_KM * 1000}).mappings().all()
    best = None
    for q in rows:
        d = km(lat, lon, q["lat"], q["lon"])
        age = (now - q["occurred_at"]).total_seconds() / 3600.0
        pts = boost_points(q["mag"], d, age)
        if pts > 0 and (best is None or pts > best["points"]):
            best = {"points": pts, "usgs_id": q["usgs_id"], "mag": q["mag"], "km": round(d), "age_h": age,
                    "text": f"M{q['mag']:.1f} earthquake {d:.0f} km away, {_ago(age)} — slopes may be weakened (USGS)"}
    return best


class Feed:
    def __init__(self) -> None:
        self.last_ok: datetime | None = None
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def fetch(self, opener=urllib.request.urlopen) -> int:
        """Pull the feed and upsert the quakes in the box. Never raises."""
        try:
            with opener(FEED, timeout=30) as r:
                data = json.loads(r.read())
        except Exception as exc:
            self.last_error = f"earthquake feed unavailable ({type(exc).__name__})"
            log.warning(self.last_error)
            return 0
        n = 0
        with session_scope() as db:
            for f in data.get("features", []):
                lon, lat, depth = (f.get("geometry") or {}).get("coordinates", [None, None, 0])[:3]
                p = f.get("properties") or {}
                if lat is None or p.get("mag") is None or not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]):
                    continue
                db.execute(text("""
                    INSERT INTO earthquakes (usgs_id, mag, place, occurred_at, lat, lon, depth_km, geom, url)
                    VALUES (:i, :m, :p, :t, :la, :lo, :d, ST_SetSRID(ST_MakePoint(:lo, :la), 4326), :u)
                    ON CONFLICT (usgs_id) DO UPDATE SET mag = EXCLUDED.mag, place = EXCLUDED.place,
                        lat = EXCLUDED.lat, lon = EXCLUDED.lon, depth_km = EXCLUDED.depth_km, geom = EXCLUDED.geom
                """), {"i": f.get("id"), "m": float(p["mag"]), "p": (p.get("place") or "")[:200],
                       "t": datetime.fromtimestamp(p["time"] / 1000, timezone.utc), "la": lat, "lo": lon,
                       "d": float(depth or 0), "u": (p.get("url") or "")[:300]})
                n += 1
            db.commit()
        self.last_ok, self.last_error = datetime.now(timezone.utc), None
        return n

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="usgs-quakes", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        wait = 20
        while not self._stop.wait(wait):
            wait = INTERVAL_S
            self.fetch()


feed = Feed()


def recent(db: Session, days: int = 7) -> list[dict[str, Any]]:
    rows = db.execute(text("""
        SELECT usgs_id, mag, place, occurred_at, lat, lon, depth_km, url FROM earthquakes
        WHERE occurred_at > NOW() - make_interval(days => :d) ORDER BY occurred_at DESC
    """), {"d": days}).mappings().all()
    return [{**dict(r), "occurred_at": r["occurred_at"].isoformat(), "source": "USGS"} for r in rows]


def health_check(db: Session) -> dict[str, Any]:
    if feed.last_error:
        status, detail = "red", feed.last_error
    elif feed.last_ok:
        status, detail = "green", "Fetched; M4.5+ in and around the North-East"
    else:
        status, detail = "amber", "Not fetched yet (first fetch ~20 s after start)"
    return {"key": "usgs", "label": "Earthquakes (USGS)", "status": status, "critical": False,
            "detail": detail, "last_ok": feed.last_ok.isoformat() if feed.last_ok else None}
