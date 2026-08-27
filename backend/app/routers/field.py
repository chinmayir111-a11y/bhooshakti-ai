"""Field officer verification.

`POST /field/verify` accepts either a single report or a batch. The batch form
is what the Expo app posts when it comes back online and flushes its offline
queue — `client_uuid` makes replay idempotent, so a flaky reconnect that sends
the same item twice cannot create duplicates.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, audit, require_auth, require_field
from ..models import FieldReport, Verdict, Zone, ZoneAssignment
from ..schemas import FieldVerifyBatch, FieldVerifyRequest
from ..services import risk_service, spatial
from ..services.media import save_photo
from ..ws import EVENT_FIELD_REPORT, EVENT_SUMMARY, manager

router = APIRouter(prefix="/field", tags=["field officer"])


def _serialise(fr: FieldReport, zone: Zone | None) -> dict:
    return {
        "id": fr.id,
        "client_uuid": fr.client_uuid,
        "zone_id": fr.zone_id,
        "zone_code": zone.code if zone else None,
        "zone_name": zone.name if zone else None,
        "verdict": fr.verdict.value,
        "notes": fr.notes,
        "photo_path": fr.photo_path,
        "lat": fr.lat,
        "lon": fr.lon,
        "officer_name": fr.officer_name,
        "observed_at": fr.observed_at.isoformat() if fr.observed_at else None,
        "created_at": fr.created_at.isoformat() if fr.created_at else None,
        "synced_at": fr.synced_at.isoformat() if fr.synced_at else None,
        "submitted_offline": fr.submitted_offline,
        "demo_data": True,
    }


def _upsert(db: Session, item: FieldVerifyRequest, principal: Principal) -> tuple[dict, bool]:
    """Returns (payload, created). Existing client_uuid -> no duplicate row."""
    existing = db.query(FieldReport).filter(
        FieldReport.client_uuid == item.client_uuid).first()
    zone = db.query(Zone).filter(Zone.id == item.zone_id).first()
    if zone is None:
        raise HTTPException(404, f"No zone with id {item.zone_id}")

    if existing is not None:
        # Idempotent replay from the offline queue — acknowledge, don't duplicate.
        return _serialise(existing, zone), False

    observed = item.observed_at or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)

    fr = FieldReport(
        client_uuid=item.client_uuid,
        zone_id=item.zone_id,
        officer_id=principal.user_id,
        officer_name=principal.full_name or principal.username,
        verdict=Verdict(item.verdict),
        notes=item.notes.strip()[:2000],
        photo_path=save_photo(item.photo_base64, prefix="field"),
        geom=(f"SRID=4326;POINT({item.lon} {item.lat})"
              if item.lat is not None and item.lon is not None else None),
        lat=item.lat,
        lon=item.lon,
        observed_at=observed,
        synced_at=datetime.now(timezone.utc),
        submitted_offline=item.submitted_offline,
    )
    db.add(fr)
    db.flush()
    return _serialise(fr, zone), True


@router.post("/verify", summary="Submit one field verification")
def verify(body: FieldVerifyRequest, request: Request, db: Session = Depends(get_db),
           principal: Principal = Depends(require_field)) -> dict:
    payload, created = _upsert(db, body, principal)
    audit(db, principal, "verify", "field_report", payload["id"], request,
          {"verdict": body.verdict, "zone_id": body.zone_id,
           "offline": body.submitted_offline, "duplicate": not created}, commit=False)
    db.commit()

    if created:
        manager.publish_threadsafe(EVENT_FIELD_REPORT, payload)
        manager.publish_threadsafe(EVENT_SUMMARY, spatial.dashboard_summary(db))
    return {**payload, "created": created,
            "message": "Recorded." if created else "Already synced — no duplicate created."}


@router.post("/verify/batch", summary="Flush an offline queue (idempotent)")
def verify_batch(body: FieldVerifyBatch, request: Request, db: Session = Depends(get_db),
                 principal: Principal = Depends(require_field)) -> dict:
    accepted, duplicates, failed = [], [], []
    for item in body.reports:
        try:
            payload, created = _upsert(db, item, principal)
            (accepted if created else duplicates).append(payload)
        except HTTPException as exc:
            failed.append({"client_uuid": item.client_uuid, "error": exc.detail})

    audit(db, principal, "verify_batch", "field_report", "", request,
          {"accepted": len(accepted), "duplicates": len(duplicates),
           "failed": len(failed)}, commit=False)
    db.commit()

    for payload in accepted:
        manager.publish_threadsafe(EVENT_FIELD_REPORT, payload)
    if accepted:
        manager.publish_threadsafe(EVENT_SUMMARY, spatial.dashboard_summary(db))

    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "failed": failed,
        "synced": len(accepted),
        "demo_data": True,
    }


@router.get("/assignments", summary="Zones assigned to the signed-in officer, worst first")
def assignments(request: Request, db: Session = Depends(get_db),
                principal: Principal = Depends(require_auth)) -> list[dict]:
    rows = (db.query(ZoneAssignment, Zone)
            .join(Zone, Zone.id == ZoneAssignment.zone_id)
            .filter(ZoneAssignment.user_id == principal.user_id).all())

    # An authority account sees everything, so the app is demoable from any login.
    zones = [z for _, z in rows] or (
        db.query(Zone).order_by(Zone.id).all() if principal.role == "authority" else []
    )

    out = []
    for z in zones:
        detail = risk_service.zone_detail(db, z, sparkline_hours=24)
        risk = detail.get("risk") or {}
        out.append({
            "zone_id": z.id,
            "code": z.code,
            "name": z.name,
            "district": z.district,
            "state": z.state,
            "centroid": [z.centroid_lat, z.centroid_lon],
            "risk_score": risk.get("risk_score"),
            "severity": risk.get("severity", "LOW"),
            "confidence": risk.get("confidence"),
            "contributing_factors": risk.get("contributing_factors", []),
            "sensors": detail.get("sensors", []),
            "roads": [r["name"] for r in detail.get("roads", [])],
            "villages": [v["name"] for v in detail.get("villages", [])],
            "demo_data": True,
        })

    rank = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}
    out.sort(key=lambda z: (rank.get(z["severity"], 4), -(z["risk_score"] or 0)))
    audit(db, principal, "read", "assignments", "", request, {"zones": len(out)})
    return out
