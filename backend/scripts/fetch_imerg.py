#!/usr/bin/env python3
"""Fetch NASA GPM IMERG daily rain for the demo events' weeks into the cache.

    python scripts/fetch_imerg.py            # Aizawl 2024 first, then Noney 2022

Seven days before the event to the day after, at the event's 0.1° cell. Two
requests at a time (NASA's server is slow, ~1-2 min each, and blocks floods).
Re-running fetches only the days still missing. If the login is missing or
NASA refuses, it says why and the replay page simply hides the chart.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import ensure_schema_additions, session_scope  # noqa: E402
from app.services import history, imerg  # noqa: E402

DEMO = ("aizawl-melthum-2024", "noney-tupul-2022")


def main() -> int:
    ensure_schema_additions()
    try:
        opener = imerg._opener()
    except imerg.NotConfigured as exc:
        print(f"  skipped: {exc}")
        return 1
    with session_scope() as db:
        events = db.execute(text("SELECT id, source_event_id, occurred_on, lat, lon FROM historical_events "
                                 "WHERE source_event_id = ANY(:ids)"), {"ids": list(DEMO)}).mappings().all()
        events = sorted(events, key=lambda e: DEMO.index(e["source_event_id"]))
        todo = []
        for e in events:
            d0 = e["occurred_on"].astimezone(history.IST).date()
            have = {r[0].date() for r in db.execute(text("SELECT day FROM satellite_rain WHERE event_id = :e"), {"e": e["id"]})}
            todo += [(e, d0 + timedelta(days=k)) for k in range(-7, 2) if d0 + timedelta(days=k) not in have]
    print(f"  {len(todo)} day(s) to fetch")

    def one(job):
        e, day = job
        try:
            return e, day, imerg.daily_mm(day, e["lat"], e["lon"], opener=opener), None
        except Exception as exc:
            return e, day, None, f"{type(exc).__name__}: {str(exc)[:80]}"

    failed = 0
    with ThreadPoolExecutor(2) as pool:
        for e, day, mm, err in pool.map(one, todo):
            if err:
                failed += 1; print(f"  {e['source_event_id']} {day}  FAILED  {err}"); continue
            _, _, glat, glon = imerg.cell(e["lat"], e["lon"])
            with session_scope() as db:
                db.execute(text("""
                    INSERT INTO satellite_rain (event_id, day, mm, grid_lat, grid_lon, source)
                    VALUES (:e, :d, :mm, :la, :lo, 'NASA GPM IMERG Final V07 (daily, 0.1°)')
                    ON CONFLICT ON CONSTRAINT uq_satrain_event_day DO UPDATE SET mm = EXCLUDED.mm
                """), {"e": e["id"], "d": datetime(day.year, day.month, day.day, tzinfo=timezone.utc), "mm": mm,
                       "la": glat, "lo": glon})
                db.commit()
            print(f"  {e['source_event_id']} {day}  {mm:6.1f} mm")
    print(f"  done, {failed} failed")
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
