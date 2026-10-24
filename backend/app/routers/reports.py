"""Citizen reporting, auto-triage and the moderation queue.

Submitting is deliberately open — no login, no account. Every submission is
geo-validated against the monitored zones with PostGIS ST_Contains, scored for
corroboration, and put on the escalation ladder (app/services/escalation.py)
so that it can never sit unseen.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, audit, current_principal, require_authority
from ..models import CitizenReport, ReportStatus, Zone
from ..schemas import CitizenReportCreate, DecisionRequest, ModerationRequest
from ..services import escalation, spatial
from ..services.media import save_audio, save_photo
from ..ws import EVENT_REPORT_MODERATED, EVENT_REPORT_NEW, EVENT_SUMMARY, manager

router = APIRouter(prefix="/reports", tags=["citizen reports"])

ISSUE_LABELS = {
    "landslide": "Landslide",
    "sos": "SOS — person in danger",
    "crack": "Ground / wall cracking",
    "slope_movement": "Visible slope movement",
    "road_blockage": "Road blocked by debris",
    "water_seepage": "Water seepage from slope",
    "tilted_trees": "Tilted trees or poles",
    "muddy_water": "Muddy water in stream",
    "voice_report": "Voice report (IVR)",
    "sms_report": "SMS report",
}


def serialise(db: Session, r: CitizenReport, zone_name: str | None = None) -> dict:
    return {
        "id": r.id,
        "issue_type": r.issue_type,
        "issue_label": ISSUE_LABELS.get(r.issue_type, r.issue_type),
        "description": r.description,
        "photo_path": r.photo_path,
        "voice_note_path": r.voice_note_path,
        "lat": r.lat,
        "lon": r.lon,
        "phone": r.phone,
        "language": r.language,
        "channel": r.channel,
        "zone_id": r.zone_id,
        "zone_name": zone_name,
        "geo_valid": r.geo_valid,
        "geo_note": r.geo_note,
        "status": r.status.value,
        "corroboration_score": r.corroboration_score,
        "corroboration_reasons": r.corroboration_reasons or [],
        "escalation": escalation.schedule(db, r),
        "moderated_by": r.moderated_by,
        "moderated_at": r.moderated_at.isoformat() if r.moderated_at else None,
        "moderation_notes": r.moderation_notes,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "demo_data": True,
    }


def _zone_name(db: Session, zone_id: int | None) -> str | None:
    if not zone_id:
        return None
    z = db.get(Zone, zone_id)
    return z.name if z else None


def submit(db: Session, *, issue_type: str, lat: float, lon: float, description: str = "",
           phone: str = "", language: str = "en", photo_path: str = "", voice_path: str = "",
           channel: str = "web", client_uuid: str | None = None,
           principal: Principal | None = None, request: Request | None = None) -> CitizenReport:
    """Store one report from any channel (web, PWA, SMS, IVR) and start triage."""
    located = spatial.locate_point(db, lat, lon)
    report = CitizenReport(
        issue_type=issue_type,
        description=description.strip()[:2000],
        photo_path=photo_path,
        voice_note_path=voice_path,
        geom=f"SRID=4326;POINT({lon} {lat})",
        lat=lat, lon=lon,
        phone=phone.strip()[:32],
        language=language,
        zone_id=located["zone_id"],
        geo_valid=located["geo_valid"],
        geo_note=located["note"],
        status=ReportStatus.PENDING,
        channel=channel,
        client_uuid=client_uuid,
        created_at=datetime.now(timezone.utc),
    )
    db.add(report)
    db.flush()
    audit(db, principal or escalation.SYSTEM, "create", "citizen_report", report.id, request,
          {"issue_type": issue_type, "geo_valid": located["geo_valid"], "channel": channel},
          commit=False)
    db.commit()

    triage = escalation.on_new_report(db, report)

    payload = serialise(db, report, located["zone_name"])
    manager.publish_threadsafe(EVENT_REPORT_NEW, payload)
    manager.publish_threadsafe(EVENT_SUMMARY, spatial.dashboard_summary(db))
    place = spatial.nearest_place(db, lat, lon)
    manager.activity(f"New report near {place} · score {triage['score']:.0f}",
                     kind="report", report_id=report.id, lat=lat, lon=lon,
                     zone_id=report.zone_id)
    return report


@router.post("", status_code=201, summary="Submit a citizen hazard report (no login)")
def create_report(body: CitizenReportCreate, request: Request,
                  db: Session = Depends(get_db),
                  principal: Principal = Depends(current_principal)) -> dict:
    if body.client_uuid:
        existing = db.query(CitizenReport).filter(CitizenReport.client_uuid == body.client_uuid).first()
        if existing is not None:      # offline replay of something already stored
            return {**serialise(db, existing, _zone_name(db, existing.zone_id)), "duplicate": True}

    report = submit(
        db, issue_type=body.issue_type, lat=body.lat, lon=body.lon,
        description=body.description, phone=body.phone, language=body.language,
        photo_path=save_photo(body.photo_base64, prefix="citizen"),
        voice_path=save_audio(body.voice_base64, prefix="citizen-voice"),
        channel=body.channel, client_uuid=body.client_uuid,
        principal=principal, request=request,
    )
    return {
        **serialise(db, report, _zone_name(db, report.zone_id)),
        "acknowledgement": ("Your report has been received. A district officer has been "
                            "notified and it will be escalated automatically if nobody "
                            "responds."),
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
    return [serialise(db, r, names.get(r.zone_id)) for r in reports]


@router.get("/escalations", summary="Open reports with their next escalation step")
def escalations(db: Session = Depends(get_db)) -> list[dict]:
    reports = db.query(CitizenReport).filter(
        CitizenReport.status == ReportStatus.PENDING,
        CitizenReport.acknowledged_at.is_(None),
    ).order_by(CitizenReport.corroboration_score.desc(), CitizenReport.id).limit(100).all()
    names = {z.id: z.name for z in db.query(Zone).all()}
    return [serialise(db, r, names.get(r.zone_id)) for r in reports]


def _load(db: Session, report_id: int) -> CitizenReport:
    report = db.get(CitizenReport, report_id)
    if report is None:
        raise HTTPException(404, f"No report with id {report_id}")
    return report


def _broadcast(db: Session, report: CitizenReport) -> dict:
    payload = serialise(db, report, _zone_name(db, report.zone_id))
    manager.publish_threadsafe(EVENT_REPORT_MODERATED, payload)
    manager.publish_threadsafe(EVENT_SUMMARY, spatial.dashboard_summary(db))
    return payload


@router.post("/{report_id}/acknowledge", summary="Stop the escalation clock: a human has seen it")
def acknowledge(report_id: int, request: Request, db: Session = Depends(get_db),
                principal: Principal = Depends(require_authority)) -> dict:
    report = _load(db, report_id)
    escalation.acknowledge(db, report, principal)
    audit(db, principal, "acknowledge", "citizen_report", report_id, request, commit=False)
    db.commit()
    return _broadcast(db, report)


@router.post("/{report_id}/confirm", summary="CONFIRM — upgrade to a WARNING for the zone")
def confirm(report_id: int, body: DecisionRequest, request: Request,
            db: Session = Depends(get_db),
            principal: Principal = Depends(require_authority)) -> dict:
    report = _load(db, report_id)
    warning = escalation.confirm(db, report, principal, body.notes)
    return {**_broadcast(db, report), "warning_alert_id": warning.id if warning else None}


@router.post("/{report_id}/dismiss", summary="DISMISS — false report; all-clear to advisory recipients")
def dismiss(report_id: int, body: DecisionRequest, request: Request,
            db: Session = Depends(get_db),
            principal: Principal = Depends(require_authority)) -> dict:
    report = _load(db, report_id)
    follow_up = escalation.dismiss(db, report, principal, body.notes)
    return {**_broadcast(db, report), "all_clear_alert_id": follow_up.id if follow_up else None}


@router.post("/{report_id}/moderate", summary="Approve, reject or escalate a report")
def moderate(report_id: int, body: ModerationRequest, request: Request,
             db: Session = Depends(get_db),
             principal: Principal = Depends(require_authority)) -> dict:
    """Kept for the field app and older clients. APPROVED and REJECTED route
    through CONFIRM and DISMISS so the alert tiers stay consistent."""
    report = _load(db, report_id)
    if body.decision == "APPROVED":
        escalation.confirm(db, report, principal, body.notes)
    elif body.decision == "REJECTED":
        escalation.dismiss(db, report, principal, body.notes)
    else:
        escalation.acknowledge(db, report, principal)
        report.status = ReportStatus.ESCALATED
        report.moderated_by = principal.username
        report.moderated_at = datetime.now(timezone.utc)
        report.moderation_notes = body.notes.strip()[:2000]
        audit(db, principal, "moderate", "citizen_report", report_id, request,
              {"decision": body.decision}, commit=False)
        db.commit()
    return _broadcast(db, report)


@router.get("/geo-check", summary="Preview the PostGIS zone match for a coordinate")
def geo_check(lat: float, lon: float, db: Session = Depends(get_db)) -> dict:
    """Used by the citizen form to tell the reporter, before they submit,
    whether their location falls inside a monitored zone."""
    near = spatial.nearest_pincode(db, lat, lon)
    return {**spatial.locate_point(db, lat, lon),
            "nearest_pincode": near["pincode"] if near else None,
            "nearest_pincode_place": near["place"] if near else None,
            "demo_data": True}
