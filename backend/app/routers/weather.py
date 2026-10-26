"""Weather cache: status and refresh.

The dashboard uses `/weather/status` to state plainly how real and how fresh
the rainfall behind every risk score is.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Principal, audit, current_principal, require_authority
from ..services import openmeteo

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("/status", summary="How real and how fresh the cached weather is")
def status(db: Session = Depends(get_db)) -> dict:
    return openmeteo.cache_status(db)


@router.get("/zone/{zone_id}/provenance",
            summary="Source endpoint, model, grid cell and a verify-live URL for one zone")
def provenance(zone_id: int, db: Session = Depends(get_db)) -> dict:
    out = openmeteo.zone_provenance(db, zone_id)
    if out is None:
        from fastapi import HTTPException
        raise HTTPException(404, f"No zone with id {zone_id}")
    return out


@router.get("/rain-frames", summary="Hourly rainfall per zone for the animated overlay")
def rain_frames(hours: int = 48, db: Session = Depends(get_db)) -> dict:
    """Observed (and, for the next hours, forecast) Open-Meteo rainfall per zone,
    as frames for the dashboard's time slider."""
    from sqlalchemy import text
    hours = max(6, min(hours, 168))
    rows = db.execute(text("""
        SELECT zone_id, ts, rainfall_mm, is_forecast, source FROM (
            SELECT DISTINCT ON (zone_id, ts) zone_id, ts, rainfall_mm, is_forecast, source
            FROM rainfall_readings
            WHERE ts > NOW() - make_interval(hours => :h) AND ts <= NOW() + INTERVAL '24 hours'
            ORDER BY zone_id, ts, is_forecast ASC
        ) r ORDER BY ts, zone_id
    """), {"h": hours}).mappings().all()
    frames: dict[str, dict] = {}
    for r in rows:
        key = r["ts"].isoformat()
        f = frames.setdefault(key, {"ts": key, "forecast": bool(r["is_forecast"]), "zones": {}})
        f["zones"][r["zone_id"]] = round(float(r["rainfall_mm"]), 2)
        f["forecast"] = f["forecast"] and bool(r["is_forecast"])
    return {"frames": list(frames.values()), "source": "Open-Meteo (ERA5 + forecast), cached",
            "real": settings.use_real_weather}


@router.post("/refresh", summary="Re-pull Open-Meteo archive + forecast for every zone")
def refresh(request: Request, history_days: int | None = None,
            forecast_days: int | None = None,
            db: Session = Depends(get_db),
            principal: Principal = Depends(require_authority)) -> dict:
    """Never fails hard: if Open-Meteo is unreachable the cached data stays
    in use and the response says so."""
    result = openmeteo.refresh(db, history_days=history_days, forecast_days=forecast_days)
    audit(db, principal, "refresh", "weather", "", request,
          {"ok": result["ok"], "rows": result.get("rows", 0)})
    return {
        **result,
        "provider": settings.weather_provider,
        "attribution": "Weather data by Open-Meteo.com (CC BY 4.0). ERA5 reanalysis via ECMWF.",
    }
