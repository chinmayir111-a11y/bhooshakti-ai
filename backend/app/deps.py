"""Request dependencies: JWT auth, role gates, audit logging.

Role model
    authority     — full read, moderation, alerting, demo control
    field_officer — assigned zones, verification submission
    citizen       — anonymous reporting only

Every data access that touches zone risk, reports or alerts writes an
audit_log row. `/audit` surfaces them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, Role, User
from .security import decode_access_token

bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user_id: int | None
    username: str
    role: str
    full_name: str = ""

    @property
    def is_anonymous(self) -> bool:
        return self.user_id is None

    def has(self, *roles: str) -> bool:
        return self.role in roles


ANONYMOUS = Principal(user_id=None, username="anonymous", role="anonymous")


def current_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal:
    """Resolve the caller. Returns ANONYMOUS when no valid token is present —
    citizen reporting is deliberately open, so this must not raise."""
    if creds is None or not creds.credentials:
        return ANONYMOUS
    claims = decode_access_token(creds.credentials)
    if not claims:
        return ANONYMOUS
    user = db.query(User).filter(User.id == claims.get("uid")).first()
    if user is None:
        return ANONYMOUS
    return Principal(
        user_id=user.id,
        username=user.username,
        role=user.role.value,
        full_name=user.full_name,
    )


def require_auth(principal: Principal = Depends(current_principal)) -> Principal:
    if principal.is_anonymous:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    return principal


def require_roles(*roles: str):
    """Dependency factory: `Depends(require_roles('authority'))`."""

    def _guard(principal: Principal = Depends(require_auth)) -> Principal:
        if not principal.has(*roles):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{principal.role}' may not perform this action "
                f"(requires: {', '.join(roles)})",
            )
        return principal

    return _guard


require_authority = require_roles(Role.AUTHORITY.value)
require_field = require_roles(Role.AUTHORITY.value, Role.FIELD_OFFICER.value)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def audit(
    db: Session,
    principal: Principal,
    action: str,
    resource: str,
    resource_id: Any = "",
    request: Request | None = None,
    detail: dict | None = None,
    commit: bool = True,
) -> None:
    entry = AuditLog(
        user_id=principal.user_id,
        username=principal.username,
        role=principal.role,
        action=action,
        resource=resource,
        resource_id=str(resource_id or ""),
        method=request.method if request else "",
        path=str(request.url.path) if request else "",
        ip=(request.client.host if request and request.client else ""),
        detail=detail or {},
    )
    db.add(entry)
    if commit:
        db.commit()
