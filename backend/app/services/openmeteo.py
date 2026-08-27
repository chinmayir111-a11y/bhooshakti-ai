"""Real observed weather from Open-Meteo, cached in the database.

Open-Meteo is free, needs no API key, and publishes ERA5 reanalysis (archive)
plus operational model output (forecast). Two endpoints are needed because
neither covers the whole window on its own:

    archive-api.open-meteo.com/v1/archive   ERA5 reanalysis. Best-quality
                                            history, but lags real time by
                                            roughly two days.
    api.open-meteo.com/v1/forecast          Operational model. Serves
                                            `past_days` to cover the archive's
                                            lag, plus the actual forecast.

They are stitched with the archive taking precedence on any overlap, since a
reanalysis is a better estimate of what happened than a forecast model's own
analysis of the same hour.

--------------------------------------------------------------------------
Two details that are easy to get wrong
--------------------------------------------------------------------------

1.  SOIL MOISTURE LAYERS DIFFER BETWEEN THE ENDPOINTS. The forecast serves
    `soil_moisture_0_to_1cm` and `soil_moisture_1_to_3cm`; the ERA5 archive
    serves neither, offering `soil_moisture_0_to_7cm` instead. Mixing them
    would put a step change into the series exactly where the two sources
    join — at Darjeeling the 0-1 cm layer reads ~0.28 m3/m3 while 0-7 cm
    reads ~0.38 at the same instant, which would look like a sudden drying
    event that never happened. So 0-7 cm is the canonical layer (it is the
    only one both endpoints provide, and the deeper layer is the one that
    actually governs shallow slope failure). The two thin layers are still
    stored where the forecast provides them, for display.

2.  UNITS. Open-Meteo reports volumetric water content in m3/m3, not percent.
    Multiplying by 100 would cap the series near 50% and the saturation term
    in fusion would never engage. It is converted to a degree of saturation
    against the observed regional limits — see `vwc_to_saturation_pct`.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings

log = logging.getLogger("bhooshakti.weather")

ARCHIVE_SOIL_VAR = "soil_moisture_0_to_7cm"
FORECAST_SOIL_VARS = ("soil_moisture_0_to_7cm", "soil_moisture_0_to_1cm", "soil_moisture_1_to_3cm")

# --------------------------------------------------------------------------
# Volumetric water content -> degree of saturation
# --------------------------------------------------------------------------
# Calibrated from the actual 0-7 cm ERA5 distribution across all 25 monitored
# zones over a 30-day monsoon window:
#
#     min 0.282   p5 0.367   median 0.417   p95 0.504   max 0.526  m3/m3
#
# Anchoring the scale at 0.25 (dry) and 0.53 (saturated) puts the regional
# median near 60% and the p95 near 91%, which lands the real data across the
# 55% wet-antecedent and 90% saturation thresholds that fusion already uses.
# Re-derive these with scripts/fetch_weather.py --calibrate if the zone set
# changes; they are properties of these soils, not universal constants.
VWC_DRY = 0.25
VWC_SATURATED = 0.53


def vwc_to_saturation_pct(vwc: float | None) -> float | None:
    """m3/m3 -> 0-100 degree of saturation."""
    if vwc is None:
        return None
    frac = (float(vwc) - VWC_DRY) / (VWC_SATURATED - VWC_DRY)
    return round(max(0.0, min(1.0, frac)) * 100.0, 2)


# --------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ZonePoint:
    zone_id: int
    code: str
    lat: float
    lon: float


@dataclass
class HourlyRow:
    zone_id: int
    ts: datetime
    rainfall_mm: float | None
    vwc_0_7cm: float | None
    vwc_0_1cm: float | None
    vwc_1_3cm: float | None
    is_forecast: bool


class WeatherUnavailable(RuntimeError):
    """Raised when Open-Meteo cannot be reached. Callers fall back to cache."""


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def _get(url: str, params: dict[str, Any]) -> Any:
    query = urllib.parse.urlencode(params, safe=",")
    full = f"{url}?{query}"
    req = urllib.request.Request(full, headers={"User-Agent": "BHOOSHAKTI-AI/1.0 (SIH 2026 prototype)"})
    try:
        with urllib.request.urlopen(req, timeout=settings.weather_timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("reason", "")
        except Exception:
            pass
        raise WeatherUnavailable(f"HTTP {exc.code} from Open-Meteo{': ' + detail if detail else ''}") from exc
    except Exception as exc:
        raise WeatherUnavailable(f"{type(exc).__name__}: {exc}") from exc

    if isinstance(payload, dict) and payload.get("error"):
        raise WeatherUnavailable(str(payload.get("reason", "Open-Meteo returned an error")))
    # A single-location request returns an object; multi-location returns a list.
    return payload if isinstance(payload, list) else [payload]


def _chunks(items: Sequence[ZonePoint], size: int) -> Iterable[Sequence[ZonePoint]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _parse_block(zone: ZonePoint, block: dict, *, is_forecast_after: datetime | None) -> list[HourlyRow]:
    hourly = block.get("hourly") or {}
    times = hourly.get("time") or []
    precip = hourly.get("precipitation") or []
    sm07 = hourly.get("soil_moisture_0_to_7cm") or []
    sm01 = hourly.get("soil_moisture_0_to_1cm") or []
    sm13 = hourly.get("soil_moisture_1_to_3cm") or []

    def at(seq: list, i: int) -> float | None:
        v = seq[i] if i < len(seq) else None
        return float(v) if v is not None else None

    rows: list[HourlyRow] = []
    for i, iso in enumerate(times):
        try:
            ts = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        rows.append(HourlyRow(
            zone_id=zone.zone_id,
            ts=ts,
            rainfall_mm=at(precip, i),
            vwc_0_7cm=at(sm07, i),
            vwc_0_1cm=at(sm01, i),
            vwc_1_3cm=at(sm13, i),
            is_forecast=bool(is_forecast_after and ts > is_forecast_after),
        ))
    return rows


# --------------------------------------------------------------------------
# Fetchers
# --------------------------------------------------------------------------


def fetch_archive(zones: Sequence[ZonePoint], start: date, end: date) -> list[HourlyRow]:
    """ERA5 reanalysis. Observation only — nothing here is a forecast."""
    out: list[HourlyRow] = []
    for chunk in _chunks(zones, settings.weather_batch_size):
        blocks = _get(settings.openmeteo_archive_url, {
            "latitude": ",".join(f"{z.lat}" for z in chunk),
            "longitude": ",".join(f"{z.lon}" for z in chunk),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": f"precipitation,{ARCHIVE_SOIL_VAR}",
            "timezone": "UTC",
        })
        for zone, block in zip(chunk, blocks):
            out.extend(_parse_block(zone, block, is_forecast_after=None))
    log.info("open-meteo archive: %d zones, %d hourly rows (%s .. %s)",
             len(zones), len(out), start, end)
    return out


def fetch_forecast(zones: Sequence[ZonePoint], past_days: int, forecast_days: int) -> list[HourlyRow]:
    """Operational model: recent past (covering the archive lag) plus forecast."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    out: list[HourlyRow] = []
    for chunk in _chunks(zones, settings.weather_batch_size):
        blocks = _get(settings.openmeteo_forecast_url, {
            "latitude": ",".join(f"{z.lat}" for z in chunk),
            "longitude": ",".join(f"{z.lon}" for z in chunk),
            "hourly": "precipitation," + ",".join(FORECAST_SOIL_VARS),
            "past_days": str(max(0, min(past_days, 92))),
            "forecast_days": str(max(1, min(forecast_days, 16))),
            "timezone": "UTC",
        })
        for zone, block in zip(chunk, blocks):
            out.extend(_parse_block(zone, block, is_forecast_after=now))
    log.info("open-meteo forecast: %d zones, %d hourly rows (past %dd, ahead %dd)",
             len(zones), len(out), past_days, forecast_days)
    return out


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

# Real telemetry outranks a weather model, so an hour already carrying a sensor
# reading is never overwritten by a refresh. This is also what keeps a running
# demo storm intact when the weather cache is refreshed underneath it.
_RAIN_UPSERT = text("""
    INSERT INTO rainfall_readings (zone_id, ts, rainfall_mm, source, is_forecast)
    VALUES (:zone_id, :ts, :mm, :source, :is_forecast)
    ON CONFLICT ON CONSTRAINT uq_rainfall_zone_hour DO UPDATE
    SET rainfall_mm = EXCLUDED.rainfall_mm,
        source      = EXCLUDED.source,
        is_forecast = EXCLUDED.is_forecast
    WHERE rainfall_readings.source <> 'sensor'
""")

_SOIL_UPSERT = text("""
    INSERT INTO soil_moisture_readings
        (zone_id, ts, moisture_pct, source, is_forecast, vwc_0_7cm, vwc_0_1cm, vwc_1_3cm)
    VALUES (:zone_id, :ts, :pct, :source, :is_forecast, :v07, :v01, :v13)
    ON CONFLICT ON CONSTRAINT uq_soil_zone_hour DO UPDATE
    SET moisture_pct = EXCLUDED.moisture_pct,
        source       = EXCLUDED.source,
        is_forecast  = EXCLUDED.is_forecast,
        vwc_0_7cm    = EXCLUDED.vwc_0_7cm,
        vwc_0_1cm    = EXCLUDED.vwc_0_1cm,
        vwc_1_3cm    = EXCLUDED.vwc_1_3cm
    WHERE soil_moisture_readings.source <> 'sensor'
""")


def store(db: Session, rows: Iterable[HourlyRow], source: str = "open-meteo") -> int:
    written = 0
    for row in rows:
        if row.rainfall_mm is not None:
            db.execute(_RAIN_UPSERT, {
                "zone_id": row.zone_id, "ts": row.ts, "mm": row.rainfall_mm,
                "source": source, "is_forecast": row.is_forecast,
            })
            written += 1
        pct = vwc_to_saturation_pct(row.vwc_0_7cm)
        if pct is not None:
            db.execute(_SOIL_UPSERT, {
                "zone_id": row.zone_id, "ts": row.ts, "pct": pct,
                "source": source, "is_forecast": row.is_forecast,
                "v07": row.vwc_0_7cm, "v01": row.vwc_0_1cm, "v13": row.vwc_1_3cm,
            })
    return written


def zone_points(db: Session) -> list[ZonePoint]:
    return [
        ZonePoint(r["id"], r["code"], float(r["centroid_lat"]), float(r["centroid_lon"]))
        for r in db.execute(text(
            "SELECT id, code, centroid_lat, centroid_lon FROM zones ORDER BY id"
        )).mappings()
    ]


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def refresh(db: Session, *, history_days: int | None = None,
            forecast_days: int | None = None,
            zones: Sequence[ZonePoint] | None = None) -> dict[str, Any]:
    """Pull both endpoints and cache the result.

    Never raises on a network failure: whatever is already cached stays usable,
    which is what lets the demo run with no connection. The return value says
    plainly whether this call reached the network.
    """
    history_days = history_days or settings.weather_history_days
    forecast_days = forecast_days or settings.weather_forecast_days
    points = list(zones) if zones is not None else zone_points(db)
    if not points:
        return {"ok": False, "detail": "no zones", "rows": 0}

    today = datetime.now(timezone.utc).date()
    archive_end = today - timedelta(days=settings.weather_archive_lag_days)
    archive_start = today - timedelta(days=history_days)
    # Overlap the forecast's past window with the archive's tail so the join
    # cannot leave a gap if ERA5 is running further behind than usual.
    past_days = settings.weather_archive_lag_days + 2

    result: dict[str, Any] = {"ok": False, "archive_rows": 0, "forecast_rows": 0,
                              "zones": len(points), "errors": []}

    # Forecast first, archive second: the archive is authoritative on overlap,
    # so writing it last lets it win without any extra bookkeeping.
    for label, fn, kwargs in (
        ("forecast", fetch_forecast, {"past_days": past_days, "forecast_days": forecast_days}),
        ("archive", fetch_archive, {"start": archive_start, "end": archive_end}),
    ):
        try:
            rows = fn(points, **kwargs)
            written = store(db, rows, source="open-meteo")
            db.flush()
            result[f"{label}_rows"] = written
            result["ok"] = True
            _log_fetch(db, label, len(points), written, rows, ok=True, detail="")
        except WeatherUnavailable as exc:
            log.warning("open-meteo %s unavailable: %s", label, exc)
            result["errors"].append(f"{label}: {exc}")
            _log_fetch(db, label, len(points), 0, [], ok=False, detail=str(exc))

    db.commit()
    result["rows"] = result["archive_rows"] + result["forecast_rows"]
    if not result["ok"]:
        result["detail"] = ("Open-Meteo unreachable — serving whatever is already cached "
                            "in the database.")
    return result


def _log_fetch(db: Session, endpoint: str, zones: int, written: int,
               rows: Sequence[HourlyRow], *, ok: bool, detail: str) -> None:
    from ..models import WeatherFetch

    stamps = [r.ts for r in rows]
    db.add(WeatherFetch(
        endpoint=endpoint, zones=zones, hours_written=written,
        window_start=min(stamps) if stamps else None,
        window_end=max(stamps) if stamps else None,
        ok=ok, detail=detail[:2000],
    ))


def cache_status(db: Session) -> dict[str, Any]:
    """What the dashboard shows: how real and how fresh the weather is."""
    coverage = db.execute(text("""
        SELECT source,
               COUNT(*) FILTER (WHERE NOT is_forecast) AS observed,
               COUNT(*) FILTER (WHERE is_forecast)     AS forecast,
               MIN(ts) AS first_ts,
               MAX(ts) AS last_ts
        FROM rainfall_readings GROUP BY source ORDER BY source
    """)).mappings().all()

    last = db.execute(text("""
        SELECT endpoint, fetched_at, ok, hours_written, detail
        FROM weather_fetches ORDER BY fetched_at DESC, id DESC LIMIT 4
    """)).mappings().all()

    latest_observation = db.execute(text("""
        SELECT MAX(ts) FROM rainfall_readings WHERE NOT is_forecast
    """)).scalar()

    return {
        "provider": settings.weather_provider,
        "using_real_weather": settings.use_real_weather,
        "vwc_reference": {"dry": VWC_DRY, "saturated": VWC_SATURATED,
                          "note": "ERA5 m3/m3 converted to degree of saturation"},
        "latest_observation": latest_observation.isoformat() if latest_observation else None,
        "coverage": [{
            "source": r["source"],
            "observed_hours": int(r["observed"]),
            "forecast_hours": int(r["forecast"]),
            "from": r["first_ts"].isoformat() if r["first_ts"] else None,
            "to": r["last_ts"].isoformat() if r["last_ts"] else None,
        } for r in coverage],
        "recent_fetches": [{
            "endpoint": r["endpoint"],
            "fetched_at": r["fetched_at"].isoformat() if r["fetched_at"] else None,
            "ok": r["ok"], "hours_written": r["hours_written"],
            "detail": r["detail"],
        } for r in last],
        "attribution": "Weather data by Open-Meteo.com (CC BY 4.0). ERA5 reanalysis via ECMWF.",
        "demo_data": True,
    }
