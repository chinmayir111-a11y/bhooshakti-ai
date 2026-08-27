"""Citizen reporting and the moderation queue.

Submitting is deliberately open — no login, no account. Every submission is
geo-validated against the monitored zones with PostGIS ST_Contains at insert
time, and the outcome of that check is what the moderation screen surfaces.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, audit, current_principal, require_authority
from ..models import CitizenReport, ReportStatus, Zone
from ..schemas import CitizenReportCreate, ModerationRequest
from ..services import spatial
from ..services.media import save_photo
from ..ws import EVENT_REPORT_MODERATED, EVENT_REPORT_NEW, EVENT_SUMMARY, manager

router = APIRouter(prefix="/reports", tags=["citizen reports"])

ISSUE_LABELS = {
    "crack": "Ground / wall cracking",
    "slope_movement": "Visible slope movement",
    "road_blockage": "Road blocked by debris",
    "water_seepage": "Water seepage from slope",
}


def _serialise(r: CitizenReport, zone_name: str | None = None) -> dict:
    return {
        "id": r.id,
        "issue_type": r.issue_type,
        "issue_label": ISSUE_LABELS.get(r.issue_type, r.issue_type),
        "description": r.description,
        "photo_path": r.photo_path,
        "lat": r.lat,
        "lon": r.lon,
        "phone": r.phone,
        "language": r.language,
        "zone_id": r.zone_id,
        "zone_name": zone_name,
        "geo_valid": r.geo_valid,
        "geo_note": r.geo_note,
        "status": r.status.value,
        "moderated_by": r.moderated_by,
        "moderated_at": r.moderated_at.isoformat() if r.moderated_at else None,
        "moderation_notes": r.moderation_notes,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "demo_data": True,
    }


@router.post("", status_code=201, summary="Submit a citizen hazard report (no login)")
def create_report(body: CitizenReportCreate, request: Request,
                  db: Session = Depends(get_db),
                  principal: Principal = Depends(current_principal)) -> dict:
    located = spatial.locate_point(db, body.lat, body.lon)

    report = CitizenReport(
        issue_type=body.issue_type,
        description=body.description.strip()[:2000],
        photo_path=save_photo(body.photo_base64, prefix="citizen"),
        geom=f"SRID=4326;POINT({body.lon} {body.lat})",
        lat=body.lat,
        lon=body.lon,
        phone=body.phone.strip()[:32],
        language=body.language,
        zone_id=located["zone_id"],
        geo_valid=located["geo_valid"],
        geo_note=located["note"],
        status=ReportStatus.PENDING,
    )
    db.add(report)
    db.flush()

    audit(db, principal, "create", "citizen_report", report.id, request,
          {"issue_type": body.issue_type, "geo_valid": located["geo_valid"]}, commit=False)
    db.commit()

    payload = _serialise(report, located["zone_name"])
    manager.publish_threadsafe(EVENT_REPORT_NEW, payload)
    manager.publish_threadsafe(EVENT_SUMMARY, spatial.dashboard_summary(db))

    return {
        **payload,
        "acknowledgement": ("Your report has been received and is being verified by the "
                            "district authority. You will not receive a reply on this "
                            "channel."),
    }


@router.get("", summary="Reports, newest first — the moderation queue")
def list_reports(request: Request, status: str | None = None,
                 zone_id: int | None = None, limit: int = Query(200, le=1000),
                 db: Session = Depends(get_db),
                 principal: Principal = Depends(current_principal)) -> list[dict]:
    q = db.query(CitizenReport).order_by(CitizenReport.created_at.desc(),
                                         CitizenReport.id.desc())
    if status:
        q = q.filter(CitizenReport.status == ReportStatus(status.upper()))
    if zone_id:
        q = q.filter(CitizenReport.zone_id == zone_id)
    reports = q.limit(limit).all()

    names = {z.id: z.name for z in db.query(Zone).all()}
    audit(db, principal, "read", "citizen_reports", "", request, {"returned": len(reports)})
    return [_serialise(r, names.get(r.zone_id)) for r in reports]


@router.post("/{report_id}/moderate", summary="Approve, reject or escalate a report")
def moderate(report_id: int, body: ModerationRequest, request: Request,
             db: Session = Depends(get_db),
             principal: Principal = Depends(require_authority)) -> dict:
    report = db.query(CitizenReport).filter(CitizenReport.id == report_id).first()
    if report is None:
        raise HTTPException(404, f"No report with id {report_id}")

    report.status = ReportStatus(body.decision)
    report.moderated_by = principal.username
    report.moderated_at = datetime.now(timezone.utc)
    report.moderation_notes = body.notes.strip()[:2000]

    audit(db, principal, "moderate", "citizen_report", report_id, request,
          {"decision": body.decision}, commit=False)
    db.commit()

    zone_name = None
    if report.zone_id:
        z = db.query(Zone).filter(Zone.id == report.zone_id).first()
        zone_name = z.name if z else None

    payload = _serialise(report, zone_name)
    manager.publish_threadsafe(EVENT_REPORT_MODERATED, payload)
    manager.publish_threadsafe(EVENT_SUMMARY, spatial.dashboard_summary(db))
    return payload


@router.get("/geo-check", summary="Preview the PostGIS zone match for a coordinate")
def geo_check(lat: float, lon: float, db: Session = Depends(get_db)) -> dict:
    """Used by the citizen form to tell the reporter, before they submit,
    whether their location falls inside a monitored zone."""
    return {**spatial.locate_point(db, lat, lon), "demo_data": True}
