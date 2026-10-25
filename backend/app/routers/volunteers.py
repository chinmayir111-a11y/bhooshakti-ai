"""Gaon Prahari village volunteers: registration (officers), the map listing,
and the app form's reading endpoint. SMS readings (R 45) arrive via inbound."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, audit, require_authority, require_roles
from ..models import Volunteer, Zone
from ..services import volunteers

router = APIRouter(prefix="/volunteers", tags=["volunteers"])
officers = require_roles("authority", "field_officer")


class VolunteerCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    phone: str = Field(..., min_length=6, max_length=32)
    zone_id: int
    place: str = ""
    safe_place: str = ""
    lat: float | None = None
    lon: float | None = None


class ReadingIn(BaseModel):
    phone: str = Field(..., min_length=6, max_length=32)
    mm: float = Field(..., ge=0, le=volunteers.MAX_READING_MM)
    client_uuid: str | None = Field(None, max_length=64)
    read_at: datetime | None = None
    channel: str = "app"


@router.get("", summary="Village volunteers with their last gauge reading (officers)")
def listing(db: Session = Depends(get_db), _: Principal = Depends(officers)) -> list[dict]:
    return volunteers.listing(db)


@router.post("", status_code=201, summary="Register a village volunteer to one zone (authority)")
def register(body: VolunteerCreate, request: Request, db: Session = Depends(get_db),
             principal: Principal = Depends(require_authority)) -> dict:
    zone = db.get(Zone, body.zone_id)
    if zone is None:
        raise HTTPException(404, "No such zone")
    if db.query(Volunteer).filter(Volunteer.phone == body.phone.strip()).first():
        raise HTTPException(409, "This phone number is already registered")
    v = Volunteer(name=body.name.strip(), phone=body.phone.strip(), zone_id=zone.id,
                  place=body.place.strip() or zone.name, safe_place=body.safe_place.strip(),
                  lat=body.lat if body.lat is not None else zone.centroid_lat,
                  lon=body.lon if body.lon is not None else zone.centroid_lon,
                  registered_by=principal.username)
    db.add(v)
    db.flush()
    audit(db, principal, "register", "volunteer", v.id, request,
          {"zone_id": zone.id, "name": v.name}, commit=False)
    db.commit()
    return {"id": v.id, "name": v.name, "zone_id": v.zone_id}


@router.post("/reading", summary="A volunteer's gauge reading from the app (offline-safe)")
def reading(body: ReadingIn, db: Session = Depends(get_db)) -> dict:
    v = volunteers.by_phone(db, body.phone)
    if v is None:
        raise HTTPException(404, "This number is not registered as a village volunteer")
    channel = body.channel if body.channel in ("app", "app-offline") else "app"
    return volunteers.record(db, v, body.mm, channel=channel, read_at=body.read_at,
                             client_uuid=body.client_uuid)


@router.get("/zone/{zone_id}/readings", summary="Volunteer gauge readings in a zone (officers)")
def zone_readings(zone_id: int, hours: int = 72, db: Session = Depends(get_db),
                  _: Principal = Depends(officers)) -> list[dict]:
    return volunteers.zone_readings(db, zone_id, min(max(hours, 1), 24 * 14))
