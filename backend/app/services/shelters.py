"""Nearest safe place: OpenStreetMap schools, community halls and hospitals,
minus any an officer has marked unsafe. `bearing` / `compass` / `metres` are
pure and unit-tested; the lookups are PostGIS."""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

KIND_LABEL = {"school": "school", "college": "college", "hospital": "hospital", "clinic": "clinic",
              "community_centre": "community hall", "townhall": "town hall", "shelter": "shelter"}
COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
MAX_KM = 15.0


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def compass(deg: float) -> str:
    return COMPASS[int(((deg % 360) + 22.5) // 45) % 8]


def rounded_metres(m: float) -> int:
    """How a person says it: 50 m steps under 1 km, 100 m steps beyond."""
    return int(round(m / 50.0) * 50) if m < 1000 else int(round(m / 100.0) * 100)


def _row(r, lat: float, lon: float) -> dict[str, Any]:
    deg = bearing(lat, lon, r["lat"], r["lon"])
    return {"id": r["id"], "name": r["name"], "kind": r["kind"], "kind_label": KIND_LABEL.get(r["kind"], r["kind"]),
            "lat": r["lat"], "lon": r["lon"], "distance_m": rounded_metres(float(r["m"])),
            "bearing_deg": round(deg), "direction": compass(deg), "source": "OpenStreetMap"}


def nearest(db: Session, lat: float, lon: float, max_km: float = MAX_KM) -> dict[str, Any] | None:
    """Nearest shelter not marked unsafe, preferring one outside every zone
    currently at HIGH/CRITICAL (you do not send people onto the moving slope)."""
    r = db.execute(text("""
        WITH here AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS g),
        hot AS (
            SELECT z.geom FROM zones z JOIN LATERAL (
                SELECT severity FROM zone_risk WHERE zone_id = z.id ORDER BY computed_at DESC, id DESC LIMIT 1
            ) r ON TRUE WHERE r.severity::text IN ('HIGH', 'CRITICAL'))
        SELECT s.id, s.name, s.kind, s.lat, s.lon, ST_Distance(s.geom::geography, here.g) AS m,
               EXISTS (SELECT 1 FROM hot WHERE ST_Contains(hot.geom, s.geom)) AS in_danger
        FROM shelters s, here
        WHERE NOT s.unsafe AND ST_DWithin(s.geom::geography, here.g, :r)
        ORDER BY in_danger, m LIMIT 1
    """), {"lat": lat, "lon": lon, "r": max_km * 1000}).mappings().first()
    return _row(r, lat, lon) if r else None


def for_zone(db: Session, zone_id: int) -> dict[str, Any] | None:
    """The safe place to name in a zone-wide alert: nearest to the zone's centre."""
    c = db.execute(text("SELECT centroid_lat, centroid_lon FROM zones WHERE id = :z"), {"z": zone_id}).first()
    return nearest(db, c[0], c[1]) if c else None


def in_zone(db: Session, zone_id: int, km: float = 3.0) -> list[dict[str, Any]]:
    """Shelters inside a zone or within `km` of it, for the officer's list."""
    rows = db.execute(text("""
        SELECT s.id, s.name, s.kind, s.lat, s.lon, s.unsafe, s.unsafe_note, s.unsafe_by,
               ST_Contains(z.geom, s.geom) AS inside,
               ST_Distance(s.geom::geography, ST_Centroid(z.geom)::geography) AS m
        FROM shelters s, zones z
        WHERE z.id = :z AND ST_DWithin(s.geom::geography, z.geom::geography, :r)
        ORDER BY s.unsafe, m LIMIT 40
    """), {"z": zone_id, "r": km * 1000}).mappings().all()
    return [{"id": r["id"], "name": r["name"], "kind_label": KIND_LABEL.get(r["kind"], r["kind"]),
             "lat": r["lat"], "lon": r["lon"], "unsafe": r["unsafe"], "unsafe_note": r["unsafe_note"],
             "unsafe_by": r["unsafe_by"], "inside_zone": r["inside"], "source": "OpenStreetMap"} for r in rows]
