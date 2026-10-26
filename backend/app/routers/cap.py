"""CAP 1.2 alert feed. Real cell broadcast requires government integration —
see README, "Rural / offline access"."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alert
from ..services import cap

router = APIRouter(prefix="/api/cap", tags=["offline channels"])


@router.get("/alerts.xml", summary="Recent alerts as an Atom feed of CAP 1.2 messages")
def feed(limit: int = 50, db: Session = Depends(get_db)) -> Response:
    return Response(cap.feed_xml(db, max(1, min(limit, 200))), media_type="application/atom+xml")


@router.get("/alerts/{alert_id}.xml", summary="One alert as a CAP 1.2 message")
def one(alert_id: int, db: Session = Depends(get_db)) -> Response:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, f"No alert with id {alert_id}")
    return Response(cap.alert_xml(db, alert), media_type="application/cap+xml")
