"""Zones, zone detail and per-zone risk."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, audit, current_principal
from ..models import Zone
from ..services import risk_service, spatial

router = APIRouter(tags=["zones"])


@router.get("/zones", summary="All monitored zones as GeoJSON, with latest risk")
def list_zones(request: Request, db: Session = Depends(get_db),
               principal: Principal = Depends(current_principal)) -> dict:
    audit(db, principal, "read", "zones", "", request)
    fc = spatial.zones_geojson(db)
    fc["demo_data"] = True
    return fc


@router.get("/zones/summary", summary="Dashboard top-strip counters")
def zones_summary(db: Session = Depends(get_db)) -> dict:
    return {**spatial.dashboard_summary(db), "demo_data": True}


@router.get("/zones/{zone_id}", summary="Full zone detail for the dashboard drawer")
def get_zone(zone_id: int, request: Request, db: Session = Depends(get_db),
             principal: Principal = Depends(current_principal)) -> dict:
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if zone is None:
        raise HTTPException(404, f"No zone with id {zone_id}")
    audit(db, principal, "read", "zone", zone_id, request, {"code": zone.code})
    return risk_service.zone_detail(db, zone)


@router.get("/zones/{zone_id}/risk", summary="Latest risk for one zone, with history")
def get_zone_risk(zone_id: int, history: int = 24, request: Request = None,
                  db: Session = Depends(get_db),
                  principal: Principal = Depends(current_principal)) -> dict:
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if zone is None:
        raise HTTPException(404, f"No zone with id {zone_id}")

    rows = [dict(r) for r in db.execute(text("""
        SELECT risk_score, severity::text AS severity, confidence,
               contributing_factors, computed_at, model_version, trigger,
               rainfall_24h, rainfall_72h, soil_moisture_pct, forecast_24h_mm,
               sensor_health, model_probability
        FROM zone_risk WHERE zone_id = :z
        ORDER BY computed_at DESC, id DESC LIMIT :n
    """), {"z": zone_id, "n": max(1, min(history, 500))}).mappings()]
    for r in rows:
        r["computed_at"] = r["computed_at"].isoformat()

    audit(db, principal, "read", "zone_risk", zone_id, request)
    return {
        "zone_id": zone.id,
        "zone_code": zone.code,
        "zone_name": zone.name,
        "current": rows[0] if rows else None,
        "history": rows,
        "demo_data": True,
    }
