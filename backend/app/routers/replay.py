"""Replay real past landslides — public, so judges can explore it.
Everything here is REAL data: NASA GLC / curated events and ERA5 weather."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..config import settings
from ..services import history, replay

router = APIRouter(prefix="/replay", tags=["backtest"])


@router.get("/summary", summary="Backtest results (counts, not accuracy claims)")
def summary() -> dict:
    r = replay.results()
    if r is None:
        raise HTTPException(404, "No backtest yet — run scripts/backtest.py")
    return {**{k: r[k] for k in ("generated_at", "model_version", "threshold", "test_year",
                                 "definitions", "summary", "demo_events", "data")},
            "baseline": r.get("baseline"),
            "earlier": replay.earlier_results()}


@router.get("/events", summary="Real events that can be replayed (held-out first)")
def events(db: Session = Depends(get_db)) -> list[dict]:
    r = replay.results() or {}
    scored = {e["id"]: e for e in r.get("events", [])}
    rows = db.execute(text("""
        SELECT id, source, source_event_id, occurred_on, time_known, lat, lon, state, title,
               trigger, fatalities, source_url, location_accuracy
        FROM historical_events ORDER BY occurred_on DESC
    """)).mappings().all()
    out = []
    for row in rows:
        if row["id"] not in scored:          # replay only what the backtest held out
            continue
        b = scored[row["id"]]
        out.append({
            "id": row["id"], "source": row["source"], "source_event_id": row["source_event_id"],
            "date": row["occurred_on"].astimezone(history.IST).date().isoformat(),
            "time_known": row["time_known"], "lat": row["lat"], "lon": row["lon"],
            "state": row["state"], "title": row["title"], "trigger": row["trigger"],
            "fatalities": row["fatalities"], "source_url": row["source_url"],
            "location_accuracy": row["location_accuracy"],
            "outcome": b.get("outcome"), "lead_hours": b.get("lead_hours"),
            "demo": row["source"] == "Curated", "real": True,
        })
    out.sort(key=lambda e: (not e["demo"], e["outcome"] != "warned_before", e["date"]), reverse=False)
    return out


@router.get("/events/{event_id}", summary="Hourly replay of one real event (or its dry week)")
def replay_event(event_id: int, window: str = Query("event", pattern="^(event|dry)$"),
                 db: Session = Depends(get_db)) -> dict:
    ev = db.execute(text("""
        SELECT id, source, source_event_id, occurred_on, time_known, lat, lon, state, title,
               fatalities, source_url
        FROM historical_events WHERE id = :i
    """), {"i": event_id}).mappings().first()
    if ev is None:
        raise HTTPException(404, f"No event {event_id}")
    day = ev["occurred_on"].astimezone(history.IST).date()
    ref = history.event_reference(ev["occurred_on"], ev["time_known"])
    day_end = history.event_day_end(ev["occurred_on"])

    if window == "dry":
        centre = date(day.year, 2, 20)
        through = datetime.combine(centre + timedelta(days=1), datetime.min.time(), timezone.utc)
    else:
        centre, through = day, day_end + timedelta(hours=24)
    tl = replay.timeline(db, ev["lat"], ev["lon"], centre, through)
    if not tl:
        raise HTTPException(409, "Weather for this event is not cached — run scripts/import_landslides.py")

    from ml.backtest import HIGH, evaluate_event, evaluate_window
    pairs = [(r["ts"], r["risk_score"]) for r in tl]
    verdict = (evaluate_event(pairs, ref, day_end) if window == "event" else evaluate_window(pairs))
    grid = tl[0]["grid"]
    return {
        "event": {**{k: ev[k] for k in ("id", "source", "source_event_id", "time_known", "lat", "lon",
                                         "state", "title", "fatalities", "source_url")},
                  "date": day.isoformat(), "reference": ref.isoformat(), "day_end": day_end.isoformat()},
        "window": window,
        "threshold": HIGH,
        "verdict": verdict,
        "hours": [{"ts": r["ts"].isoformat(), "rain_mm": round(r["rain_mm"], 2),
                   "rainfall_24h": r["rainfall_24h"], "soil_moisture_pct": r["soil_moisture_pct"],
                   "risk_score": r["risk_score"], "severity": r["severity"]} for r in tl],
        "provenance": {
            "events": ev["source"], "weather": "ERA5 hourly reanalysis via Open-Meteo archive",
            "grid": {"lat": grid[0], "lon": grid[1]},
            "forecast_input": "statistical nowcast only (no future data used)",
            "real": True,
        },
    }


# ---------------------------------------------------------------------------
# Bring your own place and date
# ---------------------------------------------------------------------------


class CustomReplayRequest(BaseModel):
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    pincode: str | None = Field(None, pattern=r"^\d{6}$")
    date: date
    # Optional local time of the event (IST). Without it the start of the day
    # is the reference, so an alert only counts if it beat the whole day.
    time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    label: str = ""


@router.post("/custom", summary="Replay any place and past date through the pipeline")
def replay_custom(body: CustomReplayRequest, db: Session = Depends(get_db)) -> dict:
    """Fetches (and caches) 30 days of ERA5 before `date` for the point, then
    replays it exactly like a catalogued event. The given date is treated as
    the day being tested, so the verdict reads the same way: did risk reach
    HIGH before the start of that day?"""
    lat, lon, place = body.lat, body.lon, body.label
    if body.pincode:
        row = db.execute(text("SELECT place, lat, lon FROM pincodes WHERE pincode = :p LIMIT 1"),
                         {"p": body.pincode}).mappings().first()
        if row is None:
            raise HTTPException(404, f"Pincode {body.pincode} is not in the demo districts")
        lat, lon, place = row["lat"], row["lon"], place or f"{row['place']} ({body.pincode})"
    if lat is None or lon is None:
        raise HTTPException(422, "Give a pincode or a latitude and longitude")
    lag = settings.weather_archive_lag_days + 2
    if body.date > date.today() - timedelta(days=lag):
        raise HTTPException(422, f"ERA5 lags real time: pick a date at least {lag} days ago")
    if body.date < date(1950, 1, 1):
        raise HTTPException(422, "ERA5 starts in 1950")

    s, e = history.window_for(body.date)
    result = history.ensure_window(db, lat, lon, s, e)
    if result.startswith("failed"):
        raise HTTPException(502, f"Open-Meteo did not return weather for that window ({result})")

    hh, mm = (int(x) for x in body.time.split(":")) if body.time else (0, 0)
    if hh > 23 or mm > 59:
        raise HTTPException(422, "time must be HH:MM")
    day_start = datetime(body.date.year, body.date.month, body.date.day, tzinfo=history.IST)
    ref = day_start.replace(hour=hh, minute=mm).astimezone(timezone.utc)
    day_end = (day_start + timedelta(days=1)).astimezone(timezone.utc)
    tl = replay.timeline(db, lat, lon, body.date, day_end + timedelta(hours=24))
    if not tl:
        raise HTTPException(502, "Not enough hourly weather came back for that window")

    from ml.backtest import HIGH, evaluate_event
    verdict = evaluate_event([(r["ts"], r["risk_score"]) for r in tl], ref, day_end)
    grid = tl[0]["grid"]
    return {
        "event": {"id": 0, "source": "Your input", "source_event_id": "custom", "time_known": body.time is not None,
                  "lat": lat, "lon": lon, "state": "", "title": place or f"{lat:.4f}, {lon:.4f}",
                  "fatalities": 0, "source_url": "", "date": body.date.isoformat(),
                  "reference": ref.isoformat(), "day_end": day_end.isoformat()},
        "window": "event", "threshold": HIGH, "verdict": verdict,
        "hours": [{"ts": r["ts"].isoformat(), "rain_mm": round(r["rain_mm"], 2),
                   "rainfall_24h": r["rainfall_24h"], "soil_moisture_pct": r["soil_moisture_pct"],
                   "risk_score": r["risk_score"], "severity": r["severity"]} for r in tl],
        "provenance": {"events": "user-supplied place and date (not a catalogued landslide)",
                       "weather": "ERA5 hourly reanalysis via Open-Meteo archive, fetched for this request",
                       "grid": {"lat": grid[0], "lon": grid[1]},
                       "forecast_input": "statistical nowcast only (no future data used)", "real": True,
                       "weather_fetch": result},
    }
