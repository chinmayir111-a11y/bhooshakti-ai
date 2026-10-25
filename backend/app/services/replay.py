"""Hour-by-hour replay of a real past event through the risk pipeline.
Shared by scripts/backtest.py and the /replay web page, so the page shows
exactly what the backtest scored."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from . import history, risk_service

REPLAY_DAYS_BEFORE = 7


def timeline(db: Session, lat: float, lon: float, centre_day: date, through: datetime) -> list[dict[str, Any]]:
    s, e = history.window_for(centre_day)
    series = history.series(db, lat, lon, datetime.combine(s, datetime.min.time(), timezone.utc),
                            datetime.combine(e + timedelta(days=1), datetime.min.time(), timezone.utc))
    if len(series) < 24 * 20:
        return []
    start = datetime.combine(centre_day - timedelta(days=REPLAY_DAYS_BEFORE), datetime.min.time(),
                             timezone.utc)
    hours = [i for i, row in enumerate(series) if start <= row["ts"] < through]
    scored = risk_service.assess_series([r["rain"] for r in series], [r["soil"] for r in series],
                                        hours=hours)
    for r in scored:
        r["ts"] = series[r["hour"]]["ts"]
        r["rain_mm"] = series[r["hour"]]["rain"]
        r["grid"] = series[r["hour"]]["grid"]
    return scored


def results() -> dict[str, Any] | None:
    path = settings.model_file.parent / "backtest_results.json"
    return json.loads(path.read_text()) if path.exists() else None


def earlier_results() -> list[dict[str, Any]]:
    """Summaries written by scripts/backtest_year.py (a model trained only on
    the years before the tested one), oldest first."""
    out = []
    for path in sorted(settings.model_file.parent.glob("backtest_[0-9][0-9][0-9][0-9].json")):
        r = json.loads(path.read_text())
        out.append({k: r[k] for k in ("test_year", "trained_on", "summary", "generated_at")})
    return out
