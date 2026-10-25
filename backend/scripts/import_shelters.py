#!/usr/bin/env python3
"""Import safe places from OpenStreetMap: schools, colleges, hospitals,
clinics, community halls and town halls in and within 3 km of each zone.

    python scripts/import_shelters.py

One Overpass query per zone, a second apart. Re-running updates names and
positions but keeps any "unsafe" mark an officer has set. Data © OpenStreetMap
contributors, ODbL.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import ensure_schema_additions, session_scope  # noqa: E402

OVERPASS = "https://overpass-api.de/api/interpreter"
KINDS = "school|college|hospital|clinic|community_centre|townhall"
PAD_DEG = 0.03          # ~3 km around the zone's box
KEEP_KM = 3.0


def query(s: float, w: float, n: float, e: float) -> list[dict]:
    q = (f'[out:json][timeout:60];('
         f'node["amenity"~"^({KINDS})$"]["name"]({s},{w},{n},{e});'
         f'way["amenity"~"^({KINDS})$"]["name"]({s},{w},{n},{e}););out center tags;')
    req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(),
                                 headers={"User-Agent": "BHOOSHAKTI-AI SIH prototype (shelter import)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())["elements"]
        except Exception as exc:
            print(f"    overpass: {exc} — retrying")
            time.sleep(10 * (attempt + 1))
    return []


def main() -> int:
    ensure_schema_additions()
    total = 0
    with session_scope() as db:
        zones = db.execute(text("""
            SELECT id, code, name, ST_YMin(geom) s, ST_XMin(geom) w, ST_YMax(geom) n, ST_XMax(geom) e
            FROM zones ORDER BY code
        """)).mappings().all()
        for z in zones:
            els = query(z["s"] - PAD_DEG, z["w"] - PAD_DEG, z["n"] + PAD_DEG, z["e"] + PAD_DEG)
            kept = 0
            for el in els:
                lat = el.get("lat") or (el.get("center") or {}).get("lat")
                lon = el.get("lon") or (el.get("center") or {}).get("lon")
                tags = el.get("tags") or {}
                name = (tags.get("name:en") or tags.get("name") or "").strip()
                if lat is None or lon is None or not name:
                    continue
                near = db.execute(text("""
                    SELECT ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r),
                           ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                    FROM zones WHERE id = :z
                """), {"lat": lat, "lon": lon, "r": KEEP_KM * 1000, "z": z["id"]}).first()
                if not near or not near[0]:
                    continue
                # OSM often maps one school as several shapes with the same name.
                dup = db.execute(text("""
                    SELECT 1 FROM shelters WHERE lower(name) = lower(:n) AND osm_id <> :o
                      AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 300)
                """), {"n": name, "o": f"{el['type']}/{el['id']}", "lat": lat, "lon": lon}).first()
                if dup:
                    continue
                db.execute(text("""
                    INSERT INTO shelters (osm_id, name, kind, lat, lon, geom, zone_id, source)
                    VALUES (:o, :n, :k, :lat, :lon, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :z, 'OpenStreetMap')
                    ON CONFLICT (osm_id) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind,
                        lat = EXCLUDED.lat, lon = EXCLUDED.lon, geom = EXCLUDED.geom,
                        zone_id = COALESCE(EXCLUDED.zone_id, shelters.zone_id)
                """), {"o": f"{el['type']}/{el['id']}", "n": name[:200], "k": tags.get("amenity", ""),
                       "lat": lat, "lon": lon, "z": z["id"] if near[1] else None})
                kept += 1
            db.commit()
            total += kept
            print(f"  {z['code']:<6} {z['name'][:34]:<34} {kept:>4} places (of {len(els)} in the box)")
            time.sleep(1.0)
    print(f"\n  {total} safe places from OpenStreetMap (© OpenStreetMap contributors, ODbL)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
