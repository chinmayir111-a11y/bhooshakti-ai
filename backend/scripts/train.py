#!/usr/bin/env python3
"""Train the landslide model on REAL past landslides.

    python scripts/train.py                 # real events (run import_landslides.py first)
    python scripts/train.py --test-year 2016

Positives   every NASA GLC event in North-East India BEFORE the test year,
            with features computed from ERA5 at the end of the event day.
Negatives   the same places at times with no reported landslide:
              * the same calendar window in a year with no catalogued event
                within 50 km (hard negatives: monsoon rain that did NOT end
                in a reported slide)
              * quiet days 12-25 days before each event.
Held out    every event from the test year on, plus the curated 2022/2024
            events. They are never seen in training; scripts/backtest.py
            replays them.

Only hydro-meteorological features are learned (24h / 72h / 15-day rain,
soil saturation). Catalogue points carry no terrain survey, and positives and
negatives share locations, so terrain columns would be noise; terrain stays in
the fusion layer's explanation instead.

Held-out metrics go to the console and ml/artifacts/model_metrics.json —
never to the API or UI. The honest skill statement is the backtest's counts.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.calibration import CalibratedClassifierCV  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sqlalchemy import text  # noqa: E402
from xgboost import XGBClassifier  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.services import history  # noqa: E402
from ml.features import FeatureRow, build_frame  # noqa: E402
from ml.rainfall_trend import window_totals  # noqa: E402
from scripts.import_landslides import Event, non_event_year  # noqa: E402

MODEL_VERSION = "v2.0-xgb-real"
HYDRO_FEATURES = ["rainfall_24h", "rainfall_72h", "antecedent_rain_15d", "soil_moisture_pct"]
NON_EVENT_SAMPLES = 6
QUIET_SAMPLES = 2
SPLIT_FILE = "ml/artifacts/split.json"


def load_events(db) -> list[dict]:
    return [dict(r) for r in db.execute(text("""
        SELECT id, source, source_event_id, occurred_on, time_known, lat, lon, state, title
        FROM historical_events ORDER BY occurred_on
    """)).mappings()]


def as_event(e: dict) -> Event:
    return Event(e["source"], e["source_event_id"], e["occurred_on"].astimezone(history.IST).date(),
                 e["lat"], e["lon"], e["state"], e["title"], "", 0, "", "")


def features_at(series: list[dict], i: int) -> FeatureRow | None:
    if i < 24 * 15 or i >= len(series):
        return None
    rain = [s["rain"] for s in series[: i + 1]]
    soil = next((s["soil"] for s in reversed(series[: i + 1]) if s["soil"] is not None), None)
    if soil is None:
        return None
    t = window_totals(rain)
    return FeatureRow(t["rainfall_24h"], t["rainfall_72h"], t["antecedent_rain_15d"], soil,
                      30.0, 180.0, 1000.0, "unknown", "unknown")


def window_series(db, ev: dict, day) -> list[dict]:
    s, e = history.window_for(day)
    return history.series(db, ev["lat"], ev["lon"],
                          datetime.combine(s, datetime.min.time(), timezone.utc),
                          datetime.combine(e + timedelta(days=1), datetime.min.time(), timezone.utc))


def index_of(series: list[dict], ts: datetime) -> int | None:
    for i, s in enumerate(series):
        if s["ts"] >= ts:
            return i
    return None


def build(db, events: list[dict], rng: random.Random, catalogue: list[Event]) -> tuple[list, list, dict]:
    rows, labels = [], []
    stats = {"positives": 0, "non_event_negatives": 0, "quiet_negatives": 0, "skipped_no_weather": 0}
    years = sorted({c.day.year for c in catalogue if c.source == "NASA GLC"})
    for ev in events:
        day = ev["occurred_on"].astimezone(history.IST).date()
        series = window_series(db, ev, day)
        end = history.event_day_end(ev["occurred_on"]) - timedelta(hours=1)
        i = index_of(series, ev["occurred_on"] if ev["time_known"] else end)
        row = features_at(series, i) if i is not None else None
        if row is None:
            stats["skipped_no_weather"] += 1
            continue
        rows.append(row); labels.append(1); stats["positives"] += 1

        for _ in range(QUIET_SAMPLES):
            j = i - rng.randint(12 * 24, 25 * 24) if i else None
            r = features_at(series, j) if j else None
            if r:
                rows.append(r); labels.append(0); stats["quiet_negatives"] += 1

        y = non_event_year(as_event(ev), catalogue, years, random.Random(26001 + ev["id"]))
        if y is None:
            continue
        try:
            nday = day.replace(year=y)
        except ValueError:
            nday = day.replace(year=y, day=28)
        ns = window_series(db, ev, nday)
        lo, hi = 24 * 18, min(len(ns) - 1, 24 * 32)
        if hi <= lo:
            continue
        for _ in range(NON_EVENT_SAMPLES):
            r = features_at(ns, rng.randint(lo, hi))
            if r:
                rows.append(r); labels.append(0); stats["non_event_negatives"] += 1
    return rows, labels, stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Train on real NE-India landslides")
    ap.add_argument("--test-year", type=int, default=2016)
    args = ap.parse_args()
    rng = random.Random(settings.seed_random_state)

    print("=" * 74)
    print("BHOOSHAKTI AI — training on REAL landslides (NASA GLC) + ERA5 weather")
    print("=" * 74)

    with session_scope() as db:
        events = load_events(db)
        if not events:
            raise SystemExit("No real events. Run `python scripts/import_landslides.py` first.")
        catalogue = [as_event(e) for e in events]
        train_ev = [e for e in events if e["source"] == "NASA GLC"
                    and e["occurred_on"].astimezone(history.IST).year < args.test_year]
        test_ev = [e for e in events if e not in train_ev]
        print(f"  events: {len(events)} real — train {len(train_ev)} (before {args.test_year}), "
              f"held out {len(test_ev)} ({args.test_year}+ and curated)")

        X_rows, y, stats = build(db, train_ev, rng, catalogue)
        Xt_rows, yt, tstats = build(db, test_ev, random.Random(7), catalogue)

    print(f"  training samples : {stats}")
    print(f"  held-out samples : {tstats}")
    if stats["positives"] < 20:
        raise SystemExit("Too few events with cached weather — let import_landslides.py finish.")

    X, y = build_frame(X_rows), np.asarray(y)
    pre = ColumnTransformer([("num", "passthrough", HYDRO_FEATURES)], remainder="drop")
    clf = XGBClassifier(
        n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.85,
        colsample_bytree=1.0, min_child_weight=3, reg_lambda=2.0,
        objective="binary:logistic", eval_metric="logloss",
        # Monotone: more rain or wetter soil can never LOWER the probability.
        monotone_constraints="(1,1,1,1)",
        random_state=settings.seed_random_state, n_jobs=4, tree_method="hist",
    )
    pipe = Pipeline([("pre", pre), ("clf", CalibratedClassifierCV(estimator=clf, method="sigmoid", cv=3))])
    print("\n  fitting XGBoost (monotone in every rainfall/soil feature) + Platt calibration ...")
    pipe.fit(X, y)

    metrics: dict = {"n_train": int(len(y)), "train_positives": int(y.sum())}
    if Xt_rows and len(set(yt)) == 2:
        p = pipe.predict_proba(build_frame(Xt_rows))[:, 1]
        metrics.update({"heldout_roc_auc": float(roc_auc_score(yt, p)),
                        "heldout_average_precision": float(average_precision_score(yt, p)),
                        "heldout_brier": float(brier_score_loss(yt, p)),
                        "n_heldout": int(len(yt)), "heldout_positives": int(sum(yt))})
    print("\n  ---- held-out metrics (console + model_metrics.json only, never the UI) ----")
    for k, v in metrics.items():
        print(f"  {k:<26} {v:.4f}" if isinstance(v, float) else f"  {k:<26} {v}")

    settings.model_file.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, settings.model_file)
    meta = {
        "model_version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "features": HYDRO_FEATURES,
        "numeric_features": HYDRO_FEATURES,
        "categorical_features": [],
        "n_samples": int(len(y)),
        "data_provenance": (f"REAL — {stats['positives']} NASA Global Landslide Catalog events in "
                            f"North-East India before {args.test_year}, ERA5 weather via Open-Meteo"),
        "test_year": args.test_year,
        "calibration": "sigmoid (Platt), 3-fold cross-validated inside the pipeline",
        "monotone": True,
    }
    settings.model_meta_file.write_text(json.dumps(meta, indent=2))
    (settings.model_meta_file.parent / "model_metrics.json").write_text(json.dumps(metrics, indent=2))
    (settings.model_file.parent / "split.json").write_text(json.dumps({
        "test_year": args.test_year,
        "train_event_ids": [e["id"] for e in train_ev],
        "test_event_ids": [e["id"] for e in test_ev],
    }, indent=2))
    print(f"\n  model -> {settings.model_file}\n  split -> ml/artifacts/split.json")
    print("\n  Next: python scripts/backtest.py, then python scripts/calibrate_demo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
