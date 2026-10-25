"""Keep the rain current and act on it, with nobody at the desk.

Every WEATHER_REFRESH_MINUTES: pull the last few days and the forecast from
Open-Meteo (the 30-day history is left to `make weather`), then rescore every
zone with alerts on. compute_zone_risk only raises an alert when a zone's
severity rises, and raise_alert has a cooldown, so a steady storm is one
alert per zone, not one every half hour. If Open-Meteo is unreachable the
cached rain stays in use and the zones are still rescored.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from ..config import settings
from ..db import session_scope
from . import openmeteo, privacy, risk_service

log = logging.getLogger(__name__)

FIRST_RUN_DELAY_S = 60      # let the API finish starting before the first pull


def run_once() -> dict[str, Any]:
    out: dict[str, Any] = {"at": datetime.now(timezone.utc).isoformat()}
    with session_scope() as db:
        if settings.use_real_weather:
            fetched = openmeteo.refresh(db, history_days=settings.weather_archive_lag_days + 2)
            out["weather_ok"] = bool(fetched.get("ok"))
        results = risk_service.recompute_all(db, trigger="weather-refresh", raise_alerts=True)
        out["privacy"] = privacy.purge(db)
    out["zones"] = len(results)
    out["alerts"] = [r["alert_id"] for r in results if r.get("alert_id")]
    return out


class WeatherScheduler:
    """Runs `run_once` on a daemon thread, the same pattern as the escalation ladder."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.runs = 0
        self.last_run: dict[str, Any] | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        if settings.weather_refresh_minutes <= 0 or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="weather-refresh", daemon=True)
        self._thread.start()
        log.info("weather refresh + rescore every %s min", settings.weather_refresh_minutes)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _loop(self) -> None:
        wait = FIRST_RUN_DELAY_S
        while not self._stop.wait(wait):
            wait = settings.weather_refresh_minutes * 60
            try:
                self.last_run = run_once()
                self.runs += 1
                self.last_error = None
                log.info("weather refresh: %s", self.last_run)
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("weather refresh failed")


scheduler = WeatherScheduler()
