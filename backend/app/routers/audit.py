"""Audit trail.

Every read of zone risk, every report, every moderation decision and every
alert dispatch writes a row. Reading the trail is itself restricted to the
authority role.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import Principal, audit as write_audit, require_authority
from ..models import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", summary="Audit log, newest first")
def list_audit(request: Request, limit: int = Query(200, le=2000),
               action: str | None = None, resource: str | None = None,
               username: str | None = None,
               db: Session = Depends(get_db),
               principal: Principal = Depends(require_authority)) -> dict:
    q = db.query(AuditLog).order_by(AuditLog.ts.desc(), AuditLog.id.desc())
    if action:
        q = q.filter(AuditLog.action == action)
    if resource:
        q = q.filter(AuditLog.resource == resource)
    if username:
        q = q.filter(AuditLog.username == username)
    rows = q.limit(limit).all()

    write_audit(db, principal, "read", "audit_log", "", request, {"returned": len(rows)})
    return {
        "entries": [{
            "id": r.id,
            "ts": r.ts.isoformat() if r.ts else None,
            "username": r.username,
            "role": r.role,
            "action": r.action,
            "resource": r.resource,
            "resource_id": r.resource_id,
            "method": r.method,
            "path": r.path,
            "ip": r.ip,
            "detail": r.detail or {},
        } for r in rows],
        "total": db.query(AuditLog).count(),
        "demo_data": True,
    }
