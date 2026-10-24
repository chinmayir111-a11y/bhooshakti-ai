#!/usr/bin/env python3
"""Import REAL past landslides for North-East India.

    python scripts/import_landslides.py                  # NASA GLC + curated, then ERA5 weather
    python scripts/import_landslides.py --no-weather     # events only
    python scripts/import_landslides.py --gsi bhukosh.csv  # also a GSI Bhukosh inventory export

Sources
  NASA Global Landslide Catalog (GLC), 2007-2016 — rainfall-triggered events
  compiled from news and official reports. Catalogue page:
  https://catalog.data.gov/dataset/global-landslide-catalog-export-75464
  Filtered to Assam, Meghalaya, Manipur, Mizoram, Nagaland, Sikkim,
  Arunachal Pradesh and Tripura.

  data/curated_events.csv — documented events after the GLC ends (Noney
  2022, Aizawl 2024), each with its press/official source URL. Stored with
  source='Curated', never mixed up with the NASA record.

  --gsi FILE — a GSI Bhukosh landslide inventory exported to CSV with
  columns: id,date,lat,lon,state,title,trigger,fatalities,source_url

Then, for every event, 30 days of ERA5 hourly rainfall + soil moisture before
it (plus two days after) is cached, and so is a NON-EVENT window at the same
place: the same calendar dates in a year with no catalogued landslide within
50 km. Held-out (test) events also get a DRY-SEASON window (same place,
February) for the replay page's "dry week".
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
import unicodedata
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GLC_URL = ("https://data.nasa.gov/docs/legacy/Global_Landslide_Catalog_Export/"
           "Global_Landslide_Catalog_Export_rows.csv")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
CURATED = DATA_DIR / "curated_events.csv"

NE_STATES = ("Assam", "Meghalaya", "Manipur", "Mizoram", "Nagaland", "Sikkim",
             "Arunachal Pradesh", "Tripura")
# Rough NE-India bounding box, as a guard against mis-tagged admin divisions.
NE_BBOX = (21.5, 29.6, 87.9, 97.5)      # lat_min, lat_max, lon_min, lon_max (Sikkim starts ~88.0 E)
IST = timezone(timedelta(hours=5, minutes=30))
NON_EVENT_RADIUS_KM = 50
NON_EVENT_DAYS = 30


@dataclass
class Event:
    source: str
    source_event_id: str
    day: date
    lat: float
    lon: float
    state: str
    title: str
    trigger: str
    fatalities: int
    location_accuracy: str
    source_url: str
    time_ist: str | None = None          # "HH:MM" when the record gives one

    @property
    def occurred_on(self) -> datetime:
        if self.time_ist:
            hh, mm = (int(x) for x in self.time_ist.split(":"))
            return datetime(self.day.year, self.day.month, self.day.day, hh, mm, tzinfo=IST)
        return datetime(self.day.year, self.day.month, self.day.day, tzinfo=IST)


# ---------------------------------------------------------------------------
# Parsing (pure — tested in tests/test_backtest.py)
# ---------------------------------------------------------------------------


def normalise_state(name: str) -> str:
    """'Nāgāland' -> 'Nagaland', 'Arunāchal Pradesh' -> 'Arunachal Pradesh'."""
    return unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().strip()


def _int(v: str) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def parse_glc_row(row: dict) -> Event | None:
    try:
        lat, lon = float(row["latitude"]), float(row["longitude"])
        day = datetime.strptime(row["event_date"].split(" ")[0], "%m/%d/%Y").date()
    except (KeyError, ValueError):
        return None
    return Event(
        source="NASA GLC", source_event_id=str(row.get("event_id") or row.get("event_import_id")),
        day=day, lat=lat, lon=lon, state=normalise_state(row.get("admin_division_name", "")),
        title=(row.get("event_title") or row.get("location_description") or "").strip()[:500],
        trigger=(row.get("landslide_trigger") or "").strip(),
        fatalities=_int(row.get("fatality_count", "")),
        location_accuracy=(row.get("location_accuracy") or "").strip(),
        source_url=(row.get("source_link") or "").strip(),
    )


def filter_ne_india(rows: Iterable[dict]) -> list[Event]:
    """India + one of the eight NE states + inside the NE bounding box."""
    out = []
    for row in rows:
        if (row.get("country_name") or "").strip() != "India":
            continue
        if normalise_state(row.get("admin_division_name", "")) not in NE_STATES:
            continue
        ev = parse_glc_row(row)
        if ev is None:
            continue
        lat_min, lat_max, lon_min, lon_max = NE_BBOX
        if not (lat_min <= ev.lat <= lat_max and lon_min <= ev.lon <= lon_max):
            continue
        out.append(ev)
    return out


def parse_simple_csv(path: Path, source: str) -> list[Event]:
    """Curated / GSI Bhukosh rows: id,date,lat,lon,state,title,trigger,fatalities,source_url."""
    out = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(Event(
                source=source, source_event_id=row.get("source_event_id") or row["id"],
                day=date.fromisoformat(row["date"]), lat=float(row["lat"]), lon=float(row["lon"]),
                state=row.get("state", ""), title=row.get("title", ""),
                trigger=row.get("trigger", ""), fatalities=_int(row.get("fatalities", "")),
                location_accuracy=row.get("location_accuracy", ""),
                source_url=row.get("source_url", ""), time_ist=(row.get("time_ist") or None),
            ))
    return out


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt
    p1, p2 = radians(lat1), radians(lat2)
    a = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 12742 * asin(sqrt(a))


def non_event_year(ev: Event, catalogue: list[Event], years: list[int], rng: random.Random) -> int | None:
    """A year whose same calendar window had no catalogued event within 50 km.
    The GLC is incomplete, so this is "no REPORTED landslide", and the README
    says so."""
    candidates = [y for y in years if y != ev.day.year]
    rng.shuffle(candidates)
    for y in candidates:
        try:
            centre = ev.day.replace(year=y)
        except ValueError:                       # 29 Feb
            centre = ev.day.replace(year=y, day=28)
        clash = any(abs((o.day - centre).days) <= NON_EVENT_DAYS
                    and km_between(ev.lat, ev.lon, o.lat, o.lon) <= NON_EVENT_RADIUS_KM
                    for o in catalogue)
        if not clash:
            return y
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def download_glc() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / "nasa_glc.csv"
    if path.exists() and path.stat().st_size > 1_000_000:
        print(f"  using cached {path.relative_to(DATA_DIR.parent)}")
        return path
    print(f"  downloading {GLC_URL}")
    req = urllib.request.Request(GLC_URL, headers={"User-Agent": "BHOOSHAKTI-AI/1.0 (SIH 2026)"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    if not data.startswith(b"source_name"):
        raise SystemExit("  NASA returned something that is not the GLC CSV — check the URL.")
    path.write_bytes(data)
    return path


def store(db, events: list[Event]) -> int:
    from sqlalchemy import text
    n = 0
    for ev in events:
        db.execute(text("""
            INSERT INTO historical_events (source, source_event_id, occurred_on, time_known, lat, lon,
                geom, state, title, location_accuracy, trigger, fatalities, source_url)
            VALUES (:source, :sid, :occ, :tk, :lat, :lon, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                :state, :title, :acc, :trig, :fat, :url)
            ON CONFLICT ON CONSTRAINT uq_historical_source_id DO UPDATE SET
                occurred_on = EXCLUDED.occurred_on, time_known = EXCLUDED.time_known,
                lat = EXCLUDED.lat, lon = EXCLUDED.lon, geom = EXCLUDED.geom,
                state = EXCLUDED.state, title = EXCLUDED.title, trigger = EXCLUDED.trigger,
                fatalities = EXCLUDED.fatalities, source_url = EXCLUDED.source_url,
                location_accuracy = EXCLUDED.location_accuracy
        """), {"source": ev.source, "sid": ev.source_event_id, "occ": ev.occurred_on,
               "tk": ev.time_ist is not None, "lat": ev.lat, "lon": ev.lon, "state": ev.state,
               "title": ev.title, "acc": ev.location_accuracy, "trig": ev.trigger,
               "fat": ev.fatalities, "url": ev.source_url})
        n += 1
    db.commit()
    return n


def windows(events: list[Event], test_year: int, seed: int) -> list[tuple[str, Event, date, date]]:
    """Every (kind, event, start, end) weather window training/backtest needs."""
    from app.services.history import window_for
    rng = random.Random(seed)
    years = sorted({e.day.year for e in events if e.source == "NASA GLC"})
    out = []
    for ev in events:
        s, e = window_for(ev.day)
        out.append(("event", ev, s, e))
        y = non_event_year(ev, events, years, rng)
        if y is not None:
            d = ev.day.replace(year=y) if not (ev.day.month == 2 and ev.day.day == 29) else ev.day.replace(year=y, day=28)
            s2, e2 = window_for(d)
            out.append(("non_event", ev, s2, e2))
        if ev.day.year >= test_year:
            s3, e3 = window_for(date(ev.day.year, 2, 20))
            out.append(("dry", ev, s3, e3))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Import real NE-India landslides (NASA GLC + curated)")
    ap.add_argument("--glc", type=Path, help="local GLC CSV instead of downloading")
    ap.add_argument("--gsi", type=Path, help="GSI Bhukosh inventory CSV (same simple schema)")
    ap.add_argument("--no-curated", action="store_true")
    ap.add_argument("--no-weather", action="store_true")
    ap.add_argument("--test-year", type=int, default=2016,
                    help="events from this year on are held out for the backtest")
    ap.add_argument("--limit", type=int, default=0, help="only fetch weather for N events (debug)")
    ap.add_argument("--workers", type=int, default=6, help="parallel Open-Meteo requests")
    args = ap.parse_args()

    from app.db import session_scope
    from app.services import history

    print("=" * 74)
    print("BHOOSHAKTI AI — importing REAL landslide events")
    print("=" * 74)

    path = args.glc or download_glc()
    with path.open(encoding="utf-8", errors="replace") as f:
        all_rows = list(csv.DictReader(f))
    events = filter_ne_india(all_rows)
    print(f"  NASA GLC: {len(all_rows):,} rows worldwide -> {len(events)} in North-East India "
          f"({min(e.day for e in events)} .. {max(e.day for e in events)})")
    if not args.no_curated and CURATED.exists():
        cur = parse_simple_csv(CURATED, "Curated")
        print(f"  curated : {len(cur)} documented events ({', '.join(e.source_event_id for e in cur)})")
        events += cur
    if args.gsi:
        gsi = parse_simple_csv(args.gsi, "GSI Bhukosh")
        print(f"  GSI     : {len(gsi)} events from {args.gsi}")
        events += gsi

    with session_scope() as db:
        n = store(db, events)
    print(f"  stored  : {n} events in historical_events")

    if args.no_weather:
        return 0

    plan = windows(events, args.test_year, seed=26001)
    if args.limit:
        plan = plan[: args.limit]
    print(f"\n  ERA5 windows to cache: {len(plan)} "
          f"({sum(k == 'event' for k, *_ in plan)} event, "
          f"{sum(k == 'non_event' for k, *_ in plan)} non-event, {sum(k == 'dry' for k, *_ in plan)} dry)")
    stats = {"cached": 0, "fetched": 0, "failed": 0}

    def fetch(item):
        kind, ev, s, e = item
        # One session per worker; Open-Meteo is latency-bound, not CPU-bound.
        with session_scope() as wdb:
            return item, history.ensure_window(wdb, ev.lat, ev.lon, s, e, pause_s=0.5)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, ((kind, ev, s, e), result) in enumerate(pool.map(fetch, plan), 1):
            key = result.split(":")[0]
            stats[key] = stats.get(key, 0) + 1
            if key == "failed":
                print(f"    ! {kind} {ev.source_event_id} {s}..{e}: {result}")
            if i % 50 == 0 or i == len(plan):
                print(f"    {i:>4}/{len(plan)}  fetched {stats['fetched']}  cached {stats['cached']}  "
                      f"failed {stats['failed']}", flush=True)
    print("\n  Next:  python scripts/train.py   then   python scripts/backtest.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
