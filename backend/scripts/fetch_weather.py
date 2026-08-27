#!/usr/bin/env python3
"""Refresh the cached Open-Meteo weather for every zone.

    python scripts/fetch_weather.py              # pull archive + forecast
    python scripts/fetch_weather.py --status     # what is cached right now
    python scripts/fetch_weather.py --calibrate  # re-derive the VWC reference

Run it whenever you want fresher weather. The demo does not need it: once the
data is in the database it stays there, which is what lets the whole system run
with no network.

Real telemetry is never overwritten — hours already carrying a sensor reading
are left alone, so a refresh cannot disturb a running demo.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json  # noqa: E402

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.services import openmeteo  # noqa: E402


def show_status() -> int:
    with session_scope() as db:
        status = openmeteo.cache_status(db)
    print("=" * 74)
    print("BHOOSHAKTI AI — cached weather")
    print("=" * 74)
    print(f"  provider           : {status['provider']}")
    print(f"  latest observation : {status['latest_observation'] or '—'}")
    print()
    print(f"  {'SOURCE':<14}{'OBSERVED':>10}{'FORECAST':>10}   WINDOW")
    for c in status["coverage"]:
        window = f"{(c['from'] or '')[:16]} .. {(c['to'] or '')[:16]}"
        print(f"  {c['source']:<14}{c['observed_hours']:>10,}{c['forecast_hours']:>10,}   {window}")
    print()
    print("  recent fetches:")
    for f in status["recent_fetches"]:
        flag = "ok " if f["ok"] else "FAIL"
        print(f"    {flag} {f['endpoint']:<9} {(f['fetched_at'] or '')[:19]}  "
              f"{f['hours_written']:>6,} rows  {f['detail'][:44]}")
    print()
    print(f"  {status['attribution']}")
    return 0


def calibrate() -> int:
    """Re-derive the VWC dry/saturated anchors from what is actually cached."""
    with session_scope() as db:
        values = [float(r[0]) for r in db.execute(text(
            "SELECT vwc_0_7cm FROM soil_moisture_readings "
            "WHERE vwc_0_7cm IS NOT NULL ORDER BY vwc_0_7cm"
        ))]
    if len(values) < 100:
        print("  Not enough cached volumetric readings. Run without --calibrate first.")
        return 1

    def q(p: float) -> float:
        return values[min(len(values) - 1, int(p * (len(values) - 1)))]

    print("=" * 74)
    print("Observed 0-7 cm volumetric water content across all monitored zones")
    print("=" * 74)
    print(f"  samples : {len(values):,}")
    for label, p in (("min", 0.0), ("p2", .02), ("p5", .05), ("median", .5),
                     ("p95", .95), ("p98", .98), ("max", 1.0)):
        print(f"  {label:<8}: {q(p):.3f} m3/m3")
    print()
    print(f"  currently configured : VWC_DRY={openmeteo.VWC_DRY}  "
          f"VWC_SATURATED={openmeteo.VWC_SATURATED}")
    print(f"  suggested from data  : VWC_DRY={q(.02):.2f}  VWC_SATURATED={q(.98):.2f}")
    print()
    print("  Under the current setting, that distribution maps to:")
    for label, p in (("p5", .05), ("median", .5), ("p95", .95)):
        print(f"    {label:<8}: {openmeteo.vwc_to_saturation_pct(q(p)):.0f} % saturation")
    print()
    print("  Edit VWC_DRY / VWC_SATURATED in app/services/openmeteo.py to change this.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh cached Open-Meteo weather")
    ap.add_argument("--status", action="store_true", help="show what is cached and exit")
    ap.add_argument("--calibrate", action="store_true", help="re-derive the VWC reference points")
    ap.add_argument("--history-days", type=int, default=settings.weather_history_days)
    ap.add_argument("--forecast-days", type=int, default=settings.weather_forecast_days)
    args = ap.parse_args()

    if args.status:
        return show_status()
    if args.calibrate:
        return calibrate()

    print("=" * 74)
    print("BHOOSHAKTI AI — refreshing weather from Open-Meteo")
    print("=" * 74)
    print(f"  archive  : {settings.openmeteo_archive_url}")
    print(f"  forecast : {settings.openmeteo_forecast_url}")
    print(f"  window   : {args.history_days} days back, {args.forecast_days} days ahead")
    print()

    with session_scope() as db:
        result = openmeteo.refresh(db, history_days=args.history_days,
                                   forecast_days=args.forecast_days)

    print(f"  zones          : {result['zones']}")
    print(f"  archive rows   : {result['archive_rows']:,}")
    print(f"  forecast rows  : {result['forecast_rows']:,}")
    if result["errors"]:
        for e in result["errors"]:
            print(f"  ! {e}")
    print()
    if result["ok"]:
        print("  Cached. The demo now runs from the database with no network needed.")
        print("  Next: python scripts/train.py   (real weather changes the feature scale)")
        return 0
    print(f"  {result.get('detail', 'Fetch failed.')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
