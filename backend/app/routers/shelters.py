"""Safe places (OpenStreetMap) for officers: list per zone, mark unsafe."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, audit, require_authority, require_roles
from ..models import Shelter
from ..services import shelters

router = APIRouter(prefix="/shelters", tags=["shelters"])


class UnsafeIn(BaseModel):
    unsafe: bool = True
    note: str = Field("", max_length=300)


@router.get("/zone/{zone_id}", summary="Safe places in and around a zone (officers)")
def in_zone(zone_id: int, db: Session = Depends(get_db),
            _: Principal = Depends(require_roles("authority", "field_officer"))) -> list[dict]:
    return shelters.in_zone(db, zone_id)


@router.get("/nearest", summary="Nearest shelter not marked unsafe")
def nearest(lat: float, lon: float, db: Session = Depends(get_db)) -> dict:
    s = shelters.nearest(db, lat, lon)
    if s is None:
        raise HTTPException(404, "No shelter within 15 km")
    return s


@router.post("/{shelter_id}/unsafe", summary="Mark a shelter unsafe (or safe again)")
def mark(shelter_id: int, body: UnsafeIn, request: Request, db: Session = Depends(get_db),
         principal: Principal = Depends(require_authority)) -> dict:
    s = db.get(Shelter, shelter_id)
    if s is None:
        raise HTTPException(404, "No such shelter")
    s.unsafe, s.unsafe_note = body.unsafe, body.note.strip() if body.unsafe else ""
    s.unsafe_by = principal.username if body.unsafe else ""
    audit(db, principal, "mark_unsafe" if body.unsafe else "mark_safe", "shelter", s.id, request,
          {"name": s.name, "note": body.note}, commit=False)
    db.commit()
    return {"id": s.id, "unsafe": s.unsafe}
