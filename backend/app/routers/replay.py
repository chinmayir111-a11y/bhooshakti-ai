"""Replay real past landslides — public, so judges can explore it.
Everything here is REAL data: NASA GLC / curated events and ERA5 weather."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import history, replay

router = APIRouter(prefix="/replay", tags=["backtest"])


@router.get("/summary", summary="Backtest results (counts, not accuracy claims)")
def summary() -> dict:
    r = replay.results()
    if r is None:
        raise HTTPException(404, "No backtest yet — run scripts/backtest.py")
    return {k: r[k] for k in ("generated_at", "model_version", "threshold", "test_year",
                              "definitions", "summary", "demo_events", "data")}


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
