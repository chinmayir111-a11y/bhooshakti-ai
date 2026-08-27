"""Login and identity. Three seeded demo accounts are advertised at
`GET /auth/demo-logins` so the login screen can list them."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Principal, audit, require_auth
from ..models import User, ZoneAssignment
from ..schemas import DemoLogin, LoginRequest, LoginResponse, MeResponse
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

DEMO_ACCOUNTS = [
    ("authority", "authority", "Authority — State EOC",
     "Command dashboard, moderation queue, alert dispatch, demo control."),
    ("field.officer", "field_officer", "Field Officer",
     "Assigned zones, on-site verification, offline-first submission."),
    ("citizen", "citizen", "Citizen",
     "Public hazard reporting. Reporting itself needs no account."),
]


@router.get("/demo-logins", response_model=list[DemoLogin],
            summary="The three seeded demo accounts")
def demo_logins() -> list[DemoLogin]:
    return [
        DemoLogin(username=u, password=settings.demo_password, role=r,
                  label=label, description=desc)
        for u, r, label, desc in DEMO_ACCOUNTS
    ]


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.username == body.username.strip().lower()).first()
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    token = create_access_token(subject=user.username, role=user.role.value, user_id=user.id)
    audit(db, Principal(user.id, user.username, user.role.value, user.full_name),
          "login", "auth", user.id, request)
    return LoginResponse(
        access_token=token,
        username=user.username,
        role=user.role.value,
        full_name=user.full_name,
        designation=user.designation,
        expires_in_minutes=settings.jwt_expire_minutes,
    )


@router.get("/me", response_model=MeResponse)
def me(principal: Principal = Depends(require_auth), db: Session = Depends(get_db)) -> MeResponse:
    user = db.query(User).filter(User.id == principal.user_id).one()
    zone_ids = [a.zone_id for a in db.query(ZoneAssignment)
                .filter(ZoneAssignment.user_id == user.id).all()]
    return MeResponse(
        user_id=user.id, username=user.username, role=user.role.value,
        full_name=user.full_name, designation=user.designation,
        email=user.email, assigned_zone_ids=zone_ids,
    )


@router.post("/push-token", summary="Register an Expo push token for this user")
def register_push_token(token: str, principal: Principal = Depends(require_auth),
                        db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.id == principal.user_id).one()
    user.push_token = token
    db.commit()
    return {"ok": True, "registered_for": user.username}
