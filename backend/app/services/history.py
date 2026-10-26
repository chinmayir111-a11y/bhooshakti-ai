"""ERA5 weather around REAL historical landslides, cached in the database.

Training (scripts/train.py) and the backtest (scripts/backtest.py) both read
from `historical_weather`, so each window is downloaded once — through the
same Open-Meteo archive endpoint and the same m3/m3 -> saturation conversion
as the live system (app/services/openmeteo.py).

Windows are keyed by the event point rounded to 0.1 degree ("cell"). ERA5 is
a ~0.25 degree grid, so nearby events share cells and downloads.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from . import openmeteo

log = logging.getLogger("bhooshakti.history")

# How much history each replay/training window carries before the event day:
# enough for the 15-day antecedent total and the 30-day seasonal 72h normal
# the live risk pipeline computes.
HISTORY_DAYS = 30
AFTER_DAYS = 2
IST = timezone(timedelta(hours=5, minutes=30))


def cell_of(lat: float, lon: float) -> str:
    return f"{round(lat, 1):.1f},{round(lon, 1):.1f}"


def window_for(day: date) -> tuple[date, date]:
    return day - timedelta(days=HISTORY_DAYS), day + timedelta(days=AFTER_DAYS)


def cached_hours(db: Session, cell: str, start: date, end: date) -> int:
    return int(db.execute(text("""
        SELECT COUNT(*) FROM historical_weather
        WHERE cell = :c AND ts >= :s AND ts < :e AND rainfall_mm IS NOT NULL
    """), {"c": cell, "s": datetime.combine(start, datetime.min.time(), timezone.utc),
           "e": datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc)}).scalar())


def ensure_window(db: Session, lat: float, lon: float, start: date, end: date,
                  pause_s: float = 0.35) -> str:
    """Download [start, end] for the event's cell unless already cached.
    Returns 'cached' | 'fetched' | 'failed: ...'."""
    cell = cell_of(lat, lon)
    expected = ((end - start).days + 1) * 24
    if cached_hours(db, cell, start, end) >= expected:
        return "cached"
    clat, clon = (float(x) for x in cell.split(","))
    point = openmeteo.ZonePoint(zone_id=0, code=cell, lat=clat, lon=clon)
    grids: list = []
    for attempt in range(3):
        try:
            rows = openmeteo.fetch_archive([point], start, end, grids=grids)
            break
        except openmeteo.WeatherUnavailable as exc:
            if "429" in str(exc) or "limit" in str(exc).lower():
                time.sleep(20 * (attempt + 1))
                continue
            return f"failed: {exc}"
    else:
        return "failed: rate limited"
    glat = grids[0][2] if grids else None
    glon = grids[0][3] if grids else None
    for r in rows:
        db.execute(text("""
            INSERT INTO historical_weather (cell, ts, rainfall_mm, vwc_0_7cm, grid_lat, grid_lon)
            VALUES (:c, :ts, :mm, :v, :gla, :glo)
            ON CONFLICT ON CONSTRAINT uq_hist_weather_cell_ts DO UPDATE
            SET rainfall_mm = EXCLUDED.rainfall_mm, vwc_0_7cm = EXCLUDED.vwc_0_7cm,
                grid_lat = EXCLUDED.grid_lat, grid_lon = EXCLUDED.grid_lon
        """), {"c": cell, "ts": r.ts, "mm": r.rainfall_mm, "v": r.vwc_0_7cm, "gla": glat, "glo": glon})
    db.commit()
    time.sleep(pause_s)          # stay well inside Open-Meteo's free-tier rate limit
    return "fetched"


def series(db: Session, lat: float, lon: float, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Hourly rows [start, end) for the event's cell, oldest first, with soil
    moisture converted exactly as the live pipeline converts it."""
    rows = db.execute(text("""
        SELECT ts, rainfall_mm, vwc_0_7cm, grid_lat, grid_lon FROM historical_weather
        WHERE cell = :c AND ts >= :s AND ts < :e ORDER BY ts
    """), {"c": cell_of(lat, lon), "s": start, "e": end}).mappings().all()
    return [{"ts": r["ts"], "rain": float(r["rainfall_mm"] or 0.0),
             "soil": openmeteo.vwc_to_saturation_pct(r["vwc_0_7cm"]),
             "grid": (r["grid_lat"], r["grid_lon"])} for r in rows]


def event_reference(occurred_on: datetime, time_known: bool) -> datetime:
    """The moment lead time is measured against. With no time of day in the
    record, the START of the local (IST) event day is used — the conservative
    choice: a warning only counts as "before" if it beat the whole day."""
    if time_known:
        return occurred_on
    local = occurred_on.astimezone(IST)
    return datetime(local.year, local.month, local.day, tzinfo=IST).astimezone(timezone.utc)


def event_day_end(occurred_on: datetime) -> datetime:
    local = occurred_on.astimezone(IST)
    return (datetime(local.year, local.month, local.day, tzinfo=IST) + timedelta(days=1)).astimezone(timezone.utc)
