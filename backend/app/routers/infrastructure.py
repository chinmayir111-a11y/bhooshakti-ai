"""Infrastructure layers and sensor status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, audit, current_principal
from ..services import spatial

router = APIRouter(tags=["infrastructure"])


@router.get("/infrastructure", summary="Roads, villages and bridges as GeoJSON")
def infrastructure(request: Request, db: Session = Depends(get_db),
                   principal: Principal = Depends(current_principal)) -> dict:
    audit(db, principal, "read", "infrastructure", "", request)
    return {
        "roads": spatial.roads_geojson(db),
        "villages": spatial.villages_geojson(db),
        "bridges": spatial.bridges_geojson(db),
        "cutoff_radius_m": spatial.CUTOFF_RADIUS_M,
        "demo_data": True,
    }


@router.get("/historical", summary="Historical landslide events as GeoJSON")
def historical(db: Session = Depends(get_db)) -> dict:
    fc = spatial.historical_geojson(db)
    fc["demo_data"] = True
    fc["provenance"] = "SIMULATED — 120 synthetic labelled events, not an official inventory"
    return fc


@router.get("/sensors", summary="Sensor nodes, status and latest telemetry")
def sensors(request: Request, db: Session = Depends(get_db),
            principal: Principal = Depends(current_principal)) -> dict:
    fc = spatial.sensors_geojson(db)

    latest = {
        r["node_id"]: {
            "ts": r["ts"].isoformat(),
            "rainfall_mm": float(r["rainfall_mm"]) if r["rainfall_mm"] is not None else None,
            "soil_moisture_pct": float(r["soil_moisture_pct"]) if r["soil_moisture_pct"] is not None else None,
            "tilt_deg": float(r["tilt_deg"]) if r["tilt_deg"] is not None else None,
        }
        for r in db.execute(text("""
            SELECT DISTINCT ON (node_id) node_id, ts, rainfall_mm,
                   soil_moisture_pct, tilt_deg
            FROM sensor_readings ORDER BY node_id, ts DESC
        """)).mappings()
    }
    for feature in fc["features"]:
        feature["properties"]["latest"] = latest.get(feature["properties"]["node_id"])

    counts = db.execute(text("""
        SELECT status::text AS status, COUNT(*) AS n FROM sensor_nodes GROUP BY status
    """)).mappings().all()

    audit(db, principal, "read", "sensors", "", request)
    return {
        **fc,
        "status_counts": {r["status"]: int(r["n"]) for r in counts},
        "demo_data": True,
    }


@router.get("/sensors/{node_id}/readings", summary="Recent telemetry for one node")
def node_readings(node_id: str, limit: int = Query(120, le=1000),
                  db: Session = Depends(get_db)) -> dict:
    rows = [
        {"ts": r["ts"].isoformat(),
         "rainfall_mm": float(r["rainfall_mm"]) if r["rainfall_mm"] is not None else None,
         "soil_moisture_pct": float(r["soil_moisture_pct"]) if r["soil_moisture_pct"] is not None else None,
         "tilt_deg": float(r["tilt_deg"]) if r["tilt_deg"] is not None else None,
         "battery_pct": float(r["battery_pct"]) if r["battery_pct"] is not None else None}
        for r in db.execute(text("""
            SELECT ts, rainfall_mm, soil_moisture_pct, tilt_deg, battery_pct
            FROM sensor_readings WHERE node_id = :n ORDER BY ts DESC LIMIT :l
        """), {"n": node_id, "l": limit}).mappings()
    ][::-1]
    return {"node_id": node_id, "readings": rows, "demo_data": True}
