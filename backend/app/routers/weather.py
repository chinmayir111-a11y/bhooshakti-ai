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
