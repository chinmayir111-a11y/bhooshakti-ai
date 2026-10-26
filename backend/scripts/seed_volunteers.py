#!/usr/bin/env python3
"""Seed three DEMO village volunteers (Gaon Prahari). Idempotent.

    python scripts/seed_volunteers.py

They are SIMULATED people with made-up numbers (+91 90000 1000x), marked
`simulated` so every screen labels them. Kurseong/Giddapahar is where GSI ran
its community rain-gauge pilot; the other two sit in the demo districts.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import ensure_schema_additions, session_scope  # noqa: E402
from app.models import Volunteer, Zone  # noqa: E402

DEMO = [
    ("DJ-02", "Giddapahar", "R. Tamang", "+919000010001"),
    ("DJ-04", "Paglajhora", "S. Rai", "+919000010002"),
    ("MZ-01", "Melthum", "L. Lalremruata", "+919000010003"),
]


def main() -> int:
    ensure_schema_additions()
    with session_scope() as db:
        for code, place, name, phone in DEMO:
            zone = db.query(Zone).filter(Zone.code == code).first()
            if zone is None or db.query(Volunteer).filter(Volunteer.phone == phone).first():
                continue
            db.add(Volunteer(name=name, phone=phone, zone_id=zone.id, place=place,
                             lat=zone.centroid_lat, lon=zone.centroid_lon,
                             registered_by="seed", simulated=True))
            print(f"  volunteer {name} ({phone}) -> {zone.code} {zone.name}, gauge at {place}  [SIMULATED]")
        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
