#!/usr/bin/env python3
"""Backtest an EARLIER year, with a model trained only on the years before it.

    python scripts/backtest_year.py --year 2015

scripts/backtest.py scores the shipped model on 2016+. This repeats the test
one year earlier: the same training recipe (scripts/train.fit) on every NASA
GLC event before --year, then the same replay and scoring (scripts/backtest.
run_events) on that year's events. Nothing the year contains is seen in
training, and the shipped model files are not touched — the temporary model
lives in memory only.

Writes ml/artifacts/backtest_<year>.json, which /replay shows beside the main
result. Downloads any weather window not cached yet (Open-Meteo archive).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.services import history, risk_service  # noqa: E402
from ml.backtest import HIGH, summarise  # noqa: E402
from scripts.backtest import baseline, run_events  # noqa: E402
from scripts.train import MODEL_VERSION, as_event, build, fit, load_events  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest an earlier year with a model trained before it")
    ap.add_argument("--year", type=int, default=2015)
    args = ap.parse_args()

    print("=" * 74)
    print(f"BHOOSHAKTI AI — backtest {args.year} with a model trained only on earlier years")
    print("=" * 74)

    with session_scope() as db:
        events = load_events(db)
        catalogue = [as_event(e) for e in events]
        years = sorted({c.day.year for c in catalogue if c.source == "NASA GLC"})
        nasa = [e for e in events if e["source"] == "NASA GLC"]
        year_of = lambda e: e["occurred_on"].astimezone(history.IST).year  # noqa: E731
        train_ev = [e for e in nasa if year_of(e) < args.year]
        test_ev = [e for e in nasa if year_of(e) == args.year]
        print(f"  train on {len(train_ev)} events ({min(map(year_of, train_ev))}–{args.year - 1}), "
              f"test on {len(test_ev)} events from {args.year}")

        X_rows, y, stats = build(db, train_ev, random.Random(settings.seed_random_state), catalogue)
        print(f"  training samples: {stats}")
        risk_service.registry.load()                 # meta/version as shipped
        risk_service.registry.model = fit(X_rows, y)  # in memory only
        risk_service.registry.loaded = True

        events_out, ne_out, dry_out = run_events(db, test_ev, catalogue, years, fetch=True)
        base = baseline(db, train_ev, test_ev, catalogue, years, fetch=True)

    scored = [e for e in events_out if e.get("outcome") in ("warned_before", "same_day", "missed")]
    summary = summarise(scored, ne_out, dry_out)
    summary["no_weather"] = sum(e.get("outcome") == "no_weather" for e in events_out)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_recipe": MODEL_VERSION,
        "trained_on": f"{len(train_ev)} NASA GLC events before {args.year}",
        "threshold": HIGH,
        "test_year": args.year,
        "summary": summary,
        "baseline": base,
        "events": events_out,
        "non_event_windows": ne_out,
        "dry_windows": dry_out,
        "data": "REAL — NASA Global Landslide Catalog; ERA5 via Open-Meteo",
    }
    path = settings.model_file.parent / f"backtest_{args.year}.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print("\n  BHOOSHAKTI: " + summary["headline"])
    print(f"  Simple rule ({base['rule']['text']}): " + base["summary"]["headline"])
    print(f"\n  -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
