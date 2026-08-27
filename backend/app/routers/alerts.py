"""Alert feed and the manual test-alert trigger.

`POST /alerts/test` is what the dashboard's "Send test alert" button calls. It
builds a real alert from a real zone's current risk and pushes it through every
configured channel — including a genuine SMTP send when SMTP_HOST is set.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Principal, audit, current_principal, require_authority
from ..models import Alert, Severity, Zone
from ..notify import AlertPayload, dispatch, templates
from ..schemas import AlertOut, TestAlertRequest
from ..services import risk_service, spatial
from ..ws import EVENT_ALERT_NEW, manager

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _serialise(db: Session, alert: Alert) -> dict:
    zone = db.query(Zone).filter(Zone.id == alert.zone_id).first()
    return {
        "id": alert.id,
        "zone_id": alert.zone_id,
        "zone_name": alert.zone_name,
        "zone_code": zone.code if zone else None,
        "district": zone.district if zone else None,
        "state": zone.state if zone else None,
        "severity": alert.severity.value,
        "risk_score": alert.risk_score,
        "confidence": alert.confidence,
        "title": alert.title,
        "message": alert.message,
        "contributing_factors": alert.contributing_factors or [],
        "language": alert.language,
        "created_at": alert.created_at,
        "acknowledged": alert.acknowledged,
        "source": alert.source,
        "deliveries": [
            {"channel": d.channel, "recipient": d.recipient, "status": d.status.value,
             "detail": d.detail, "language": d.language, "sent_at": d.sent_at}
            for d in alert.deliveries
        ],
        "demo_data": True,
    }


@router.get("", response_model=list[AlertOut], summary="Alert history, newest first")
def list_alerts(request: Request, limit: int = Query(100, le=500),
                severity: str | None = None, zone_id: int | None = None,
                db: Session = Depends(get_db),
                principal: Principal = Depends(current_principal)) -> list[dict]:
    q = db.query(Alert).order_by(Alert.created_at.desc(), Alert.id.desc())
    if severity:
        q = q.filter(Alert.severity == Severity(severity.upper()))
    if zone_id:
        q = q.filter(Alert.zone_id == zone_id)
    alerts = q.limit(limit).all()
    audit(db, principal, "read", "alerts", "", request, {"returned": len(alerts)})
    return [_serialise(db, a) for a in alerts]


@router.post("/test", summary="Send a real test alert on every configured channel")
def send_test_alert(body: TestAlertRequest, request: Request,
                    db: Session = Depends(get_db),
                    principal: Principal = Depends(require_authority)) -> dict:
    """Sends to ALERT_TEST_EMAIL (or `email` in the body).

    With SMTP_HOST configured this is a genuine end-to-end email send; without
    it the email channel reports SIMULATED and logs the rendered message.
    """
    if body.zone_id:
        zone = db.query(Zone).filter(Zone.id == body.zone_id).first()
        if zone is None:
            raise HTTPException(404, f"No zone with id {body.zone_id}")
    else:
        row = db.execute(text("""
            SELECT z.id FROM zones z
            JOIN LATERAL (
                SELECT risk_score FROM zone_risk zr WHERE zr.zone_id = z.id
                ORDER BY computed_at DESC, id DESC LIMIT 1
            ) r ON TRUE
            ORDER BY r.risk_score DESC LIMIT 1
        """)).first()
        if row is None:
            raise HTTPException(400, "No zone risk has been computed yet — POST /risk/recompute first.")
        zone = db.query(Zone).filter(Zone.id == row[0]).one()

    current = db.execute(text("""
        SELECT risk_score, severity::text AS severity, confidence, contributing_factors
        FROM zone_risk WHERE zone_id = :z ORDER BY computed_at DESC, id DESC LIMIT 1
    """), {"z": zone.id}).mappings().first()
    if current is None:
        raise HTTPException(400, f"Zone {zone.code} has no computed risk yet.")

    if body.email:
        # Per-request override of the configured recipient.
        settings.alert_test_email = body.email

    roads = spatial.roads_intersecting_zone(db, zone.id)
    villages = spatial.villages_in_zone(db, zone.id)

    payload = AlertPayload(
        alert_id=None, zone_id=zone.id, zone_code=zone.code, zone_name=zone.name,
        district=zone.district, state=zone.state,
        severity=current["severity"], risk_score=float(current["risk_score"]),
        confidence=float(current["confidence"]),
        contributing_factors=current["contributing_factors"] or [],
        language=body.language,
        deep_link=f"{settings.public_dashboard_url}/?zone={zone.id}",
        affected_roads=[r["name"] for r in roads[:4]],
        affected_villages=[v["name"] for v in villages[:6]],
        source="manual-test",
    )
    payload.title = templates.subject(payload)
    payload.message = templates.plain_text(payload)

    alert = Alert(
        zone_id=zone.id, zone_name=zone.name, severity=Severity(current["severity"]),
        risk_score=float(current["risk_score"]), confidence=float(current["confidence"]),
        title=payload.title, message=payload.message,
        contributing_factors=current["contributing_factors"] or [],
        language=body.language, source="manual-test",
    )
    db.add(alert)
    db.flush()

    results = dispatch(db, alert, payload, channels=body.channels)
    audit(db, principal, "send_test_alert", "alert", alert.id, request,
          {"zone": zone.code, "channels": [r.channel for r in results]})
    db.commit()

    manager.publish_threadsafe(EVENT_ALERT_NEW, _serialise(db, alert))

    return {
        "alert_id": alert.id,
        "zone": f"{zone.code} — {zone.name}",
        "severity": current["severity"],
        "risk_score": float(current["risk_score"]),
        "confidence": float(current["confidence"]),
        "email_configured": settings.email_configured,
        "deliveries": [
            {"channel": r.channel, "recipient": r.recipient,
             "status": r.status, "detail": r.detail}
            for r in results
        ],
        "note": ("Set SMTP_HOST/SMTP_USER/SMTP_PASSWORD in .env to turn the email "
                 "channel from SIMULATED into a real send."
                 if not settings.email_configured else
                 "Email dispatched over SMTP — check the recipient inbox."),
        "demo_data": True,
    }


@router.post("/{alert_id}/acknowledge", summary="Mark an alert as acknowledged")
def acknowledge(alert_id: int, request: Request, db: Session = Depends(get_db),
                principal: Principal = Depends(require_authority)) -> dict:
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert is None:
        raise HTTPException(404, f"No alert with id {alert_id}")
    alert.acknowledged = True
    audit(db, principal, "acknowledge", "alert", alert_id, request, commit=False)
    db.commit()
    manager.publish_threadsafe("alert.acknowledged", {"alert_id": alert_id})
    return {"ok": True, "alert_id": alert_id}
