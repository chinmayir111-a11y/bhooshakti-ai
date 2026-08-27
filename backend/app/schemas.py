"""Request/response models. Keeps /docs honest and self-describing."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
Language = Literal["en", "hi", "as"]
IssueType = Literal["crack", "slope_movement", "road_blockage", "water_seepage"]


# --------------------------------------------------------------------- auth --


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    full_name: str
    designation: str
    expires_in_minutes: int


class MeResponse(BaseModel):
    user_id: int
    username: str
    role: str
    full_name: str
    designation: str
    email: str
    assigned_zone_ids: list[int] = []


class DemoLogin(BaseModel):
    username: str
    password: str
    role: str
    label: str
    description: str


# --------------------------------------------------------------------- risk --


class RecomputeRequest(BaseModel):
    zone_ids: list[int] | None = Field(
        None, description="Limit to these zones. Omit to recompute every zone."
    )
    raise_alerts: bool = Field(
        True, description="Fire alerts for zones that escalate into HIGH or CRITICAL."
    )


class RecomputeResponse(BaseModel):
    computed: int
    model_version: str
    results: list[dict[str, Any]]
    demo_data: bool = True


# ------------------------------------------------------------------- alerts --


class TestAlertRequest(BaseModel):
    zone_id: int | None = Field(None, description="Defaults to the highest-risk zone.")
    email: str | None = Field(None, description="Override ALERT_TEST_EMAIL for this send.")
    language: Language = "en"
    channels: list[str] | None = Field(
        None, description="Defaults to NOTIFY_CHANNELS from the environment."
    )


class DeliveryOut(BaseModel):
    channel: str
    recipient: str
    status: str
    detail: str
    language: str
    sent_at: datetime | None


class AlertOut(BaseModel):
    id: int
    zone_id: int
    zone_name: str
    zone_code: str | None = None
    district: str | None = None
    state: str | None = None
    severity: Severity
    risk_score: float
    confidence: float
    title: str
    message: str
    contributing_factors: list[dict[str, Any]]
    language: str
    created_at: datetime
    acknowledged: bool
    source: str
    deliveries: list[DeliveryOut]
    demo_data: bool = True


# ------------------------------------------------------------------ reports --


class CitizenReportCreate(BaseModel):
    issue_type: IssueType
    description: str = ""
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    phone: str = ""
    language: Language = "en"
    photo_base64: str | None = Field(
        None, description="Optional data URI or bare base64 image payload."
    )


class ModerationRequest(BaseModel):
    decision: Literal["APPROVED", "REJECTED", "ESCALATED"]
    notes: str = ""


class FieldVerifyRequest(BaseModel):
    client_uuid: str = Field(..., description="Client-generated UUID; makes offline replay idempotent.")
    zone_id: int
    verdict: Literal["CONFIRMED", "DENIED", "UNCERTAIN"]
    notes: str = ""
    lat: float | None = None
    lon: float | None = None
    observed_at: datetime | None = None
    submitted_offline: bool = False
    photo_base64: str | None = None


class FieldVerifyBatch(BaseModel):
    """Offline queue flush: the app posts everything it buffered at once."""

    reports: list[FieldVerifyRequest]


# --------------------------------------------------------------------- demo --


class SimulateRequest(BaseModel):
    speed: Literal[1, 4] = Field(1, description="1x or 4x playback.")
    zone_codes: list[str] | None = Field(
        None, description="Defaults to the Sikkim/Darjeeling corridor demo zones."
    )


class DemoState(BaseModel):
    running: bool
    step: int
    total_steps: int
    speed: int
    label: str
    started_at: datetime | None
    demo_data: bool = True
