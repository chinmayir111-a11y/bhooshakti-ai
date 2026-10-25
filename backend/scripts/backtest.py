#!/usr/bin/env python3
"""Replay held-out REAL landslides hour by hour through the risk pipeline.

    python scripts/backtest.py

For every event in ml/artifacts/split.json's test set (never trained on):
replay from 7 days before to the end of the event day through
risk_service.assess_series, record the first HIGH, the lead time, or a miss.
Then replay the same place's non-event window (same dates, a year with no
reported landslide nearby) and dry-season window, and count false alarms.

Writes ml/artifacts/backtest_results.json — counts, not accuracy claims.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.services import history, risk_service  # noqa: E402
from app.services import replay as replay_service  # noqa: E402
from ml.backtest import HIGH, evaluate_event, evaluate_window, summarise  # noqa: E402
from scripts.import_landslides import non_event_year  # noqa: E402
from scripts.train import as_event, load_events  # noqa: E402

RESULTS = settings.model_file.parent / "backtest_results.json"
DEMO_EVENT_IDS = ("noney-tupul-2022", "aizawl-melthum-2024")


def replay(db, lat: float, lon: float, centre_day, through: datetime) -> list[dict]:
    return replay_service.timeline(db, lat, lon, centre_day, through)


def run_events(db, test: list[dict], catalogue, years: list[int], fetch: bool = False):
    """Replay each held-out event, its non-event window and its dry window.
    `fetch` downloads any weather window not cached yet (scripts/backtest_year.py)."""
    events_out, ne_out, dry_out = [], [], []

    def replay(db, lat, lon, centre_day, through):
        if fetch:
            history.ensure_window(db, lat, lon, *history.window_for(centre_day))
        return replay_service.timeline(db, lat, lon, centre_day, through)

    for ev in test:
        day = ev["occurred_on"].astimezone(history.IST).date()
        ref = history.event_reference(ev["occurred_on"], ev["time_known"])
        day_end = history.event_day_end(ev["occurred_on"])
        tl = replay(db, ev["lat"], ev["lon"], day, day_end + timedelta(hours=24))
        base = {"id": ev["id"], "source": ev["source"], "source_event_id": ev["source_event_id"],
                "title": ev["title"], "state": ev["state"], "date": day.isoformat(),
                "time_known": ev["time_known"], "lat": ev["lat"], "lon": ev["lon"]}
        if not tl:
            events_out.append({**base, "outcome": "no_weather"})
            continue
        res = evaluate_event([(r["ts"], r["risk_score"]) for r in tl], ref, day_end)
        events_out.append({**base, **res, "reference": ref.isoformat()})
        mark = {"warned_before": "WARNED", "same_day": "same-day", "missed": "missed"}[res["outcome"]]
        lead = f"{res['lead_hours']:>6.1f} h" if res["lead_hours"] is not None and res["outcome"] == "warned_before" else "       "
        print(f"  {day}  {ev['state'][:12]:<12} {mark:<9} {lead}  peak {res['peak_score']:>5.1f}  "
              f"{ev['title'][:44]}")

        y = non_event_year(as_event(ev), catalogue, years, __import__("random").Random(26001 + ev["id"]))
        if y is not None:
            try:
                nday = day.replace(year=y)
            except ValueError:
                nday = day.replace(year=y, day=28)
            ntl = replay(db, ev["lat"], ev["lon"], nday,
                         datetime.combine(nday + timedelta(days=1), datetime.min.time(), timezone.utc))
            if ntl:
                ne_out.append({"event_id": ev["id"], "date": nday.isoformat(),
                               **evaluate_window([(r["ts"], r["risk_score"]) for r in ntl])})
        dday = datetime(day.year, 2, 20).date()
        dtl = replay(db, ev["lat"], ev["lon"], dday,
                     datetime.combine(dday + timedelta(days=1), datetime.min.time(), timezone.utc))
        if dtl:
            dry_out.append({"event_id": ev["id"], "date": dday.isoformat(),
                            **evaluate_window([(r["ts"], r["risk_score"]) for r in dtl])})
    return events_out, ne_out, dry_out


def main() -> int:
    risk_service.registry.load()
    split_path = settings.model_file.parent / "split.json"
    if not split_path.exists():
        raise SystemExit("No ml/artifacts/split.json — run scripts/train.py first.")
    split = json.loads(split_path.read_text())

    print("=" * 74)
    print(f"BHOOSHAKTI AI — backtest on held-out REAL landslides  (model {risk_service.registry.version})")
    print("=" * 74)

    with session_scope() as db:
        events = load_events(db)
        catalogue = [as_event(e) for e in events]
        years = sorted({c.day.year for c in catalogue if c.source == "NASA GLC"})
        test = [e for e in events if e["id"] in set(split["test_event_ids"])]
        print(f"  held-out events: {len(test)}   alert threshold: risk >= {HIGH:.0f} (HIGH)")

        events_out, ne_out, dry_out = run_events(db, test, catalogue, years)

    scored = [e for e in events_out if e.get("outcome") in ("warned_before", "same_day", "missed")]
    summary = summarise(scored, ne_out, dry_out)
    summary["no_weather"] = sum(e.get("outcome") == "no_weather" for e in events_out)
    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": risk_service.registry.version,
        "threshold": HIGH,
        "test_year": split["test_year"],
        "definitions": {
            "reference": "event time if recorded, else start of the local (IST) event day",
            "warned_before": "risk reached HIGH at or before the reference",
            "same_day": "first HIGH during the event day, after its start (time of slide unknown)",
            "false_alarm": "window reached HIGH at any hour",
            "forecast_input": "statistical nowcast only — no archived NWP forecast, no future data",
        },
        "summary": summary,
        "demo_events": [e for e in events_out if e["source_event_id"] in DEMO_EVENT_IDS],
        "events": events_out,
        "non_event_windows": ne_out,
        "dry_windows": dry_out,
        "data": "REAL — NASA Global Landslide Catalog + curated press/official records; ERA5 via Open-Meteo",
    }
    RESULTS.write_text(json.dumps(results, indent=2, default=str))
    print("\n  " + summary["headline"])
    print(f"\n  -> {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
