#!/usr/bin/env python3
"""Train the landslide susceptibility model on the seeded (simulated) data.

    python scripts/train.py

Positives  : the 120 seeded historical events, with their feature values as of
             occurrence.
Negatives  : zone-hours sampled from the seeded 30-day hourly series, including
             near-miss hours — heavy rain that did not bring the slope down.
             Those are the negatives that stop the model concluding that heavy
             rain always means failure.

Metrics are printed to the console and written to ml/artifacts/model_metrics.json.
They are NEVER exposed through the API or shown in the UI: accuracy figures from
a synthetic dataset would be misleading to a judge or an operator.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from sklearn.calibration import CalibratedClassifierCV  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score,
    brier_score_loss,
    classification_report,
    confusion_matrix,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import OneHotEncoder  # noqa: E402
from xgboost import XGBClassifier  # noqa: E402

import joblib  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import HistoricalLandslide, RainfallReading, SoilMoistureReading, Zone  # noqa: E402
from ml.features import (  # noqa: E402
    ALL_FEATURES,
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    FeatureRow,
    build_frame,
)
from ml.rainfall_trend import window_totals  # noqa: E402

MODEL_VERSION = "v1.0-xgb"
NEGATIVES_PER_POSITIVE = 4
NEAR_MISS_EXCLUSION_QUANTILE = 0.90


def _one_hot() -> OneHotEncoder:
    """sklearn renamed `sparse` to `sparse_output` in 1.2."""
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:  # pragma: no cover - older sklearn
        return OneHotEncoder(handle_unknown="ignore", sparse=False)


def load_training_set(rng: random.Random) -> tuple[list[FeatureRow], list[int], dict]:
    rows: list[FeatureRow] = []
    labels: list[int] = []
    stats = {"positives": 0, "negatives": 0, "near_miss_negatives": 0, "zones": 0}

    with session_scope() as db:
        zones = db.query(Zone).order_by(Zone.id).all()
        stats["zones"] = len(zones)
        if not zones:
            raise SystemExit("No zones found — run `python scripts/seed.py --reset` first.")

        # ---- positives --------------------------------------------------
        for ev in db.query(HistoricalLandslide).all():
            rows.append(FeatureRow(
                rainfall_24h=ev.rainfall_24h,
                rainfall_72h=ev.rainfall_72h,
                antecedent_rain_15d=ev.antecedent_rain_15d,
                soil_moisture_pct=ev.soil_moisture_pct,
                slope_deg=ev.slope_deg,
                aspect_deg=ev.aspect_deg,
                elevation_m=ev.elevation_m,
                lithology=ev.lithology,
                land_cover=ev.land_cover,
            ))
            labels.append(1)
        stats["positives"] = len(rows)

        target_negatives = stats["positives"] * NEGATIVES_PER_POSITIVE
        per_zone = max(1, target_negatives // max(len(zones), 1))

        # ---- negatives, sampled from the observed hourly series ----------
        for z in zones:
            rain = [r.rainfall_mm for r in db.query(RainfallReading)
                    .filter(RainfallReading.zone_id == z.id)
                    .order_by(RainfallReading.ts).all()]
            soil = [s.moisture_pct for s in db.query(SoilMoistureReading)
                    .filter(SoilMoistureReading.zone_id == z.id)
                    .order_by(SoilMoistureReading.ts).all()]
            if len(rain) < 24 * 16 or len(soil) != len(rain):
                continue

            arr = np.asarray(rain, dtype=float)
            cumulative = np.concatenate(([0.0], np.cumsum(arr)))
            rolling72 = cumulative[72:] - cumulative[:-72]
            cutoff = float(np.quantile(rolling72, NEAR_MISS_EXCLUSION_QUANTILE))

            candidates = list(range(24 * 15, len(rain)))
            rng.shuffle(candidates)
            taken = 0
            for h in candidates:
                if taken >= per_zone:
                    break
                if rolling72[h - 72] > cutoff:
                    # A near-miss: heavy rain that did NOT bring the slope down.
                    # These are the most informative negatives there are — they
                    # are what stops the model concluding that heavy rain always
                    # means failure. Kept, and counted so the console shows how
                    # many made it into the negative pool.
                    stats["near_miss_negatives"] += 1
                totals = window_totals(rain[:h + 1])
                rows.append(FeatureRow(
                    rainfall_24h=totals["rainfall_24h"],
                    rainfall_72h=totals["rainfall_72h"],
                    antecedent_rain_15d=totals["antecedent_rain_15d"],
                    soil_moisture_pct=soil[h],
                    slope_deg=z.slope_deg,
                    aspect_deg=z.aspect_deg,
                    elevation_m=z.elevation_m,
                    lithology=z.lithology,
                    land_cover=z.land_cover,
                ))
                labels.append(0)
                taken += 1
        stats["negatives"] = len(rows) - stats["positives"]

    return rows, labels, stats


def main() -> int:
    rng = random.Random(settings.seed_random_state)
    np.random.seed(settings.seed_random_state)

    print("=" * 74)
    print("BHOOSHAKTI AI — training susceptibility model   [SIMULATED DATA]")
    print("=" * 74)

    rows, labels, stats = load_training_set(rng)
    X = build_frame(rows)
    y = np.asarray(labels, dtype=int)

    print(f"\n  zones            : {stats['zones']}")
    print(f"  positives        : {stats['positives']}")
    print(f"  negatives        : {stats['negatives']}")
    print(f"  of which near-miss (heavy rain, no failure): {stats['near_miss_negatives']}")
    print(f"  features         : {', '.join(ALL_FEATURES)}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=settings.seed_random_state, stratify=y
    )

    pre = ColumnTransformer(
        transformers=[
            ("num", "passthrough", NUMERIC_FEATURES),
            ("cat", _one_hot(), CATEGORICAL_FEATURES),
        ],
        remainder="drop",
    )
    clf = XGBClassifier(
        n_estimators=320,
        max_depth=4,
        learning_rate=0.06,
        subsample=0.85,
        colsample_bytree=0.85,
        min_child_weight=2,
        reg_lambda=1.4,
        objective="binary:logistic",
        eval_metric="logloss",
        scale_pos_weight=float((y_train == 0).sum()) / max(float((y_train == 1).sum()), 1.0),
        random_state=settings.seed_random_state,
        n_jobs=4,
        tree_method="hist",
    )
    # Raw boosted-tree scores are poorly calibrated, and the fused risk score
    # treats this output as a probability — so the classifier is wrapped in
    # cross-validated Platt scaling *inside* the pipeline. Calibrating within
    # the pipeline (rather than on a prefit estimator) keeps the whole training
    # set available and leaves one artefact to persist.
    calibrated_clf = CalibratedClassifierCV(estimator=clf, method="sigmoid", cv=3)
    pipe = Pipeline([("pre", pre), ("clf", calibrated_clf)])

    print("\n  fitting XGBoost with 3-fold Platt calibration ...")
    pipe.fit(X_train, y_train)

    # ---------------------------------------------------------------- metrics
    proba = pipe.predict_proba(X_test)[:, 1]
    pred = (proba >= 0.5).astype(int)
    metrics = {
        "roc_auc": float(roc_auc_score(y_test, proba)),
        "average_precision": float(average_precision_score(y_test, proba)),
        "brier_score": float(brier_score_loss(y_test, proba)),
        "n_train": int(len(y_train)),
        "n_test": int(len(y_test)),
    }

    print("\n  ---- held-out metrics (console only, never surfaced in the UI) ----")
    for k in ("roc_auc", "average_precision", "brier_score"):
        print(f"  {k:<20} {metrics[k]:.4f}")
    print(f"\n  confusion matrix (rows=true 0/1, cols=pred 0/1):\n{confusion_matrix(y_test, pred)}")
    print("\n" + classification_report(y_test, pred, target_names=["no-event", "event"], digits=3))

    # Feature importance, averaged over the calibration folds and mapped back
    # through the one-hot encoder.
    try:
        names = [n.split("__", 1)[-1] for n in pipe.named_steps["pre"].get_feature_names_out()]
        folds = [
            cc.estimator.feature_importances_
            for cc in pipe.named_steps["clf"].calibrated_classifiers_
            if hasattr(getattr(cc, "estimator", None), "feature_importances_")
        ]
        if folds:
            mean_importance = np.mean(np.vstack(folds), axis=0)
            ranked = sorted(zip(names, mean_importance), key=lambda t: -t[1])[:10]
            print("  top feature importances (gain-weighted, mean over folds):")
            for name, imp in ranked:
                print(f"    {name:<32} {imp:.4f}")
    except Exception as exc:  # pragma: no cover
        print(f"  (feature importance unavailable: {exc})")

    # ---------------------------------------------------------------- persist
    settings.model_file.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, settings.model_file)

    meta = {
        "model_version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "features": ALL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "n_samples": int(len(y)),
        "data_provenance": "SIMULATED — generated by scripts/seed.py, not an official dataset",
        "calibration": "sigmoid (Platt), 3-fold cross-validated inside the pipeline",
    }
    settings.model_meta_file.write_text(json.dumps(meta, indent=2))

    # Metrics live in their own file so no API response can accidentally
    # serialise them alongside the model metadata.
    metrics_path = settings.model_meta_file.parent / "model_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))

    print(f"\n  model  -> {settings.model_file}")
    print(f"  meta   -> {settings.model_meta_file}")
    print(f"  metrics-> {metrics_path}   (console/docs only — not served by the API)")
    print("\n" + "=" * 74)
    print("Training complete.  Next:  uvicorn app.main:app --reload")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
