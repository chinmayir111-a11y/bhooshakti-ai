#!/usr/bin/env python3
"""Measure what storm target lands each demo zone in which severity band.

    python scripts/calibrate_demo.py

Runs the REAL pipeline (model -> forecast -> fusion) over candidate 24h
rainfall targets and prints the resulting band, so the demo timeline's
ZONE_TARGET_24H_MM values are chosen from measurement rather than guesswork.
Read-only: nothing is written to the database.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import session_scope  # noqa: E402
from app.models import Zone  # noqa: E402
from app.services.demo_engine import DEFAULT_ZONE_CODES  # noqa: E402
from app.services.risk_service import registry  # noqa: E402
from ml.features import FeatureRow  # noqa: E402
from ml.fusion import FusionInput, fuse  # noqa: E402
from ml.rainfall_trend import forecast_24h, seasonal_normal_72h  # noqa: E402

# Real ERA5 seasonal normals in this region sit near 25-80 mm/72h, so the
# useful sweep is far lower than it was against synthetic weather.
TARGETS = [10, 18, 26, 34, 45, 60, 80, 110]
SOIL_LEVELS = [65.0, 78.0, 90.0]


def main() -> int:
    registry.load()
    print("=" * 78)
    print("BHOOSHAKTI AI — demo storm calibration   [SIMULATED DATA, read-only]")
    print("=" * 78)
    print(f"  model: {registry.version}\n")

    with session_scope() as db:
        for code in DEFAULT_ZONE_CODES:
            zone = db.query(Zone).filter(Zone.code == code).first()
            if zone is None:
                continue
            rain = [float(r[0]) for r in db.execute(text("""
                SELECT rainfall_mm FROM rainfall_readings
                WHERE zone_id = :z ORDER BY ts
            """), {"z": zone.id})]
            normal72 = seasonal_normal_72h(rain)
            antecedent = sum(rain[-24 * 15:])

            print(f"  {code} — {zone.name}")
            print(f"    slope {zone.slope_deg:.0f}°  {zone.lithology} / {zone.land_cover}  "
                  f"{zone.elevation_m:.0f} m   seasonal 72h normal {normal72:.0f} mm")
            header = "      24h/mm  " + "".join(f"{f'soil {s:.0f}%':>22}" for s in SOIL_LEVELS)
            print(header)

            for target in TARGETS:
                # Storm replayed over the last 15h, tail of the day unchanged.
                storm = [target * w / 15.0 for w in [1.0] * 15]
                series = rain[:-15] + storm if len(rain) > 15 else storm
                fcst, _ = forecast_24h(series)
                cells = []
                for soil in SOIL_LEVELS:
                    r72 = target * 1.25
                    p = registry.probability(FeatureRow(
                        target, r72, antecedent, soil, zone.slope_deg, zone.aspect_deg,
                        zone.elevation_m, zone.lithology, zone.land_cover))
                    res = fuse(FusionInput(
                        code, zone.name, p, target, r72, antecedent, soil, fcst, normal72,
                        zone.slope_deg, zone.elevation_m, zone.lithology, zone.land_cover,
                        2, 2, 5.0, []))
                    cells.append(f"{f'P={p:.2f} {res.risk_score:5.1f} {res.severity[:4]}':>22}")
                print(f"      {target:>6}  " + "".join(cells))
            print()

    print("  Pick targets whose band matches the scripted story, then set")
    print("  ZONE_TARGET_24H_MM / ZONE_TARGET_SOIL_PCT in app/services/demo_engine.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
