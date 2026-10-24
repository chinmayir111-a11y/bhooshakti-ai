"""Tiny unauthenticated endpoints for the citizen app — kept small so the
"Am I safe?" screen loads on 2G."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..notify import templates
from ..services import spatial

router = APIRouter(prefix="/public", tags=["public"])


def _risk(db: Session, zone_id: int) -> dict | None:
    row = db.execute(text("""
        SELECT z.id, z.code, z.name, z.district, r.severity::text AS severity,
               r.risk_score, r.computed_at
        FROM zones z LEFT JOIN LATERAL (
            SELECT severity, risk_score, computed_at FROM zone_risk WHERE zone_id = z.id
            ORDER BY computed_at DESC, id DESC LIMIT 1) r ON TRUE
        WHERE z.id = :z
    """), {"z": zone_id}).mappings().first()
    return dict(row) if row else None


def _answer(db: Session, zone_id: int | None, place: str, lang: str, inside: bool) -> dict:
    risk = _risk(db, zone_id) if zone_id else None
    sev = risk["severity"] if risk else None
    active = db.execute(text("""
        SELECT tier, title, created_at FROM alerts
        WHERE zone_id = :z AND status = 'ACTIVE' AND created_at > NOW() - INTERVAL '12 hours'
          AND source NOT IN ('manual-test', 'all-clear')
        ORDER BY created_at DESC LIMIT 1
    """), {"z": zone_id}).mappings().first() if zone_id else None
    return {
        "inside_zone": inside,
        "zone_id": zone_id,
        "zone_name": risk["name"] if risk else None,
        "place": place,
        "severity": sev,
        "message": templates.safety_line(sev, place, lang),
        "active_alert": {"tier": active["tier"], "title": active["title"],
                         "created_at": active["created_at"].isoformat()} if active else None,
        "computed_at": risk["computed_at"].isoformat() if risk and risk["computed_at"] else None,
        "demo_data": True,
    }


@router.get("/risk", summary="Am I safe? Current risk at a point")
def risk_at(lat: float, lon: float, lang: str = "en", db: Session = Depends(get_db)) -> dict:
    found = spatial.locate_point(db, lat, lon)
    zone_id = found["zone_id"]
    inside = zone_id is not None
    # Just outside a zone, the nearest zone's risk is still the useful answer,
    # but it is labelled as such.
    if not inside and found.get("distance_km") is not None and found["distance_km"] <= 10:
        zone_id = db.execute(text("SELECT id FROM zones WHERE code = :c"),
                             {"c": found["zone_code"]}).scalar()
    place = spatial.nearest_place(db, lat, lon)
    return {**_answer(db, zone_id, place, lang, inside), "distance_km": found.get("distance_km")}


@router.get("/pincode/{pincode}", summary="Current risk for a pincode")
def risk_by_pincode(pincode: str, lang: str = "en", db: Session = Depends(get_db)) -> dict:
    row = db.execute(text("SELECT place, zone_id FROM pincodes WHERE pincode = :p LIMIT 1"),
                     {"p": pincode}).mappings().first()
    if row is None:
        raise HTTPException(404, f"Pincode {pincode} is not in the demo districts")
    return _answer(db, row["zone_id"], row["place"], lang, row["zone_id"] is not None)


@router.get("/sms-number", summary="The number keyword SMS should be sent to")
def sms_number() -> dict:
    from ..config import settings
    return {"number": settings.twilio_from_number or settings.msg91_sender_id or "",
            "configured": bool(settings.twilio_from_number or settings.msg91_sender_id),
            "keywords": ["LS <pincode> <what you see>", "SAFE <pincode>", "JOIN <pincode>", "STOP"]}
