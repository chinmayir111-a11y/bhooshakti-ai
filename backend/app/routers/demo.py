"""Demo-mode control: run, reset, inspect the scripted monsoon timeline."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Principal, audit, require_authority
from ..schemas import DemoState as DemoStateOut, SimulateRequest
from ..services.demo_engine import STEP_LABELS, TOTAL_STEPS, engine

router = APIRouter(prefix="/demo", tags=["demo mode"])


@router.post("/simulate", summary="Run the scripted monsoon timeline")
async def simulate(body: SimulateRequest, request: Request,
                   db: Session = Depends(get_db),
                   principal: Principal = Depends(require_authority)) -> dict:
    """Eight visible steps pushed live over the WebSocket.

    Step 1 publishes genuine MQTT telemetry, which the API's own subscriber
    ingests — the demo drives the real pipeline rather than faking its output.
    """
    audit(db, principal, "simulate", "demo", "", request,
          {"speed": body.speed, "zones": body.zone_codes})
    result = await engine.start(speed=body.speed, zone_codes=body.zone_codes)
    return {
        **result,
        "steps": STEP_LABELS,
        "seconds_at_1x": settings.demo_timeline_seconds,
        "demo_data": True,
    }


@router.post("/reset", summary="Undo the timeline and return to the seeded baseline")
async def reset(request: Request, db: Session = Depends(get_db),
                principal: Principal = Depends(require_authority)) -> dict:
    audit(db, principal, "reset", "demo", "", request)
    return await engine.reset()


@router.post("/stop", summary="Halt a running timeline without resetting")
async def stop(request: Request, db: Session = Depends(get_db),
               principal: Principal = Depends(require_authority)) -> dict:
    audit(db, principal, "stop", "demo", "", request)
    return await engine.stop()


@router.get("/state", response_model=DemoStateOut, summary="Current timeline state")
def state() -> dict:
    return engine.state.as_dict()


@router.get("/steps", summary="The timeline script, for the presenter's own reference")
def steps() -> dict:
    return {
        "total_steps": TOTAL_STEPS,
        "seconds_at_1x": settings.demo_timeline_seconds,
        "steps": [{"step": i + 1, "label": label} for i, label in enumerate(STEP_LABELS)],
        "demo_data": True,
    }


@router.get("/response-plan", summary="The prioritised response list from step 8")
def response_plan(db: Session = Depends(get_db)) -> dict:
    rows = [dict(r) for r in db.execute(text("""
        SELECT ra.id, ra.priority, ra.action, ra.owner, ra.rationale, ra.status,
               z.code AS zone_code, z.name AS zone_name
        FROM response_actions ra LEFT JOIN zones z ON z.id = ra.zone_id
        ORDER BY ra.priority, ra.id
    """)).mappings()]
    return {"actions": rows, "demo_data": True}
