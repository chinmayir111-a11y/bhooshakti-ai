"""ORM models. Geometry columns are real PostGIS types (SRID 4326).

Spatial logic lives in SQL (ST_Contains / ST_Intersects / ST_DWithin) — see
app/services/spatial.py — not in Python.
"""
from __future__ import annotations

import enum
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Role(str, enum.Enum):
    AUTHORITY = "authority"
    FIELD_OFFICER = "field_officer"
    CITIZEN = "citizen"


class Severity(str, enum.Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SensorStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    MAINTENANCE = "MAINTENANCE"


class RoadStatus(str, enum.Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class ReportStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


class Verdict(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    UNCERTAIN = "UNCERTAIN"


class DeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SIMULATED = "SIMULATED"


def _enum(py_enum: type[enum.Enum], name: str) -> Enum:
    """Store enums by *value* so the DB holds readable strings."""
    return Enum(
        py_enum,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
    )


# ---------------------------------------------------------------------------
# Identity & audit
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    full_name: Mapped[str] = mapped_column(String(128), default="")
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role, "role_enum"))
    designation: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    push_token: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assignments: Mapped[list["ZoneAssignment"]] = relationship(back_populates="officer")


class ZoneAssignment(Base):
    """Which field officer covers which zone."""

    __tablename__ = "zone_assignments"
    __table_args__ = (UniqueConstraint("user_id", "zone_id", name="uq_assignment"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))

    officer: Mapped[User] = relationship(back_populates="assignments")
    zone: Mapped["Zone"] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="anonymous")
    role: Mapped[str] = mapped_column(String(32), default="anonymous")
    action: Mapped[str] = mapped_column(String(64))
    resource: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(64), default="")
    method: Mapped[str] = mapped_column(String(8), default="")
    path: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    district: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(64))
    geom: Mapped[object] = mapped_column(Geometry("POLYGON", srid=4326, spatial_index=True))
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lon: Mapped[float] = mapped_column(Float)

    # static terrain features fed to the susceptibility model
    slope_deg: Mapped[float] = mapped_column(Float)
    aspect_deg: Mapped[float] = mapped_column(Float)
    elevation_m: Mapped[float] = mapped_column(Float)
    lithology: Mapped[str] = mapped_column(String(64))
    land_cover: Mapped[str] = mapped_column(String(64))
    population: Mapped[int] = mapped_column(Integer, default=0)
    area_km2: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RainfallReading(Base):
    __tablename__ = "rainfall_readings"
    __table_args__ = (
        Index("ix_rainfall_zone_ts", "zone_id", "ts"),
        # Named so the MQTT roll-up can ON CONFLICT onto it: one canonical
        # rainfall figure per zone per hour, refined as telemetry arrives.
        UniqueConstraint("zone_id", "ts", name="uq_rainfall_zone_hour"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rainfall_mm: Mapped[float] = mapped_column(Float)
    # simulated | open-meteo | sensor
    source: Mapped[str] = mapped_column(String(32), default="simulated")
    # Future-dated rows are forecast, not observation. Trailing-window sums MUST
    # exclude them — without this flag a 24h total would quietly include
    # tomorrow's rain and every risk score would run hot.
    is_forecast: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False, index=True
    )


class SoilMoistureReading(Base):
    __tablename__ = "soil_moisture_readings"
    __table_args__ = (
        Index("ix_soil_zone_ts", "zone_id", "ts"),
        UniqueConstraint("zone_id", "ts", name="uq_soil_zone_hour"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Degree of saturation, 0-100. This is what the model and fusion consume.
    moisture_pct: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), default="simulated")
    is_forecast: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False, index=True
    )

    # Raw volumetric water content (m3/m3) exactly as Open-Meteo returned it,
    # kept so the conversion above can be re-derived or audited later.
    # 0-7 cm is the only layer both the archive and the forecast endpoints
    # share, so it is the canonical one; the two shallower layers exist only on
    # the forecast side and are stored for display.
    vwc_0_7cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    vwc_0_1cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    vwc_1_3cm: Mapped[float | None] = mapped_column(Float, nullable=True)


class WeatherFetch(Base):
    """One row per successful Open-Meteo pull, so the dashboard can say how old
    the cached weather is and the demo can prove it is running from cache."""

    __tablename__ = "weather_fetches"

    id: Mapped[int] = mapped_column(primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    endpoint: Mapped[str] = mapped_column(String(32))          # archive | forecast
    zones: Mapped[int] = mapped_column(Integer, default=0)
    hours_written: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class HistoricalLandslide(Base):
    """~120 labelled events with the feature values as of occurrence."""

    __tablename__ = "historical_landslides"

    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    rainfall_24h: Mapped[float] = mapped_column(Float)
    rainfall_72h: Mapped[float] = mapped_column(Float)
    antecedent_rain_15d: Mapped[float] = mapped_column(Float)
    soil_moisture_pct: Mapped[float] = mapped_column(Float)
    slope_deg: Mapped[float] = mapped_column(Float)
    aspect_deg: Mapped[float] = mapped_column(Float)
    elevation_m: Mapped[float] = mapped_column(Float)
    lithology: Mapped[str] = mapped_column(String(64))
    land_cover: Mapped[str] = mapped_column(String(64))

    label: Mapped[int] = mapped_column(Integer, default=1)
    fatalities: Mapped[int] = mapped_column(Integer, default=0)
    trigger: Mapped[str] = mapped_column(String(64), default="rainfall")
    notes: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


class RoadSegment(Base):
    __tablename__ = "road_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    road_class: Mapped[str] = mapped_column(String(16), default="NH")
    geom: Mapped[object] = mapped_column(Geometry("LINESTRING", srid=4326, spatial_index=True))
    status: Mapped[RoadStatus] = mapped_column(_enum(RoadStatus, "road_status_enum"), default=RoadStatus.OPEN)
    length_km: Mapped[float] = mapped_column(Float, default=0.0)
    criticality: Mapped[str] = mapped_column(String(32), default="lifeline")
    status_note: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Village(Base):
    __tablename__ = "villages"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    district: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(64))
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    population: Mapped[int] = mapped_column(Integer, default=0)
    households: Mapped[int] = mapped_column(Integer, default=0)
    is_cut_off: Mapped[bool] = mapped_column(Boolean, default=False)
    cut_off_reason: Mapped[str] = mapped_column(String(255), default="")


class Bridge(Base):
    __tablename__ = "bridges"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    span_m: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[RoadStatus] = mapped_column(_enum(RoadStatus, "bridge_status_enum"), default=RoadStatus.OPEN)
    road_name: Mapped[str] = mapped_column(String(128), default="")


class SensorNode(Base):
    __tablename__ = "sensor_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    status: Mapped[SensorStatus] = mapped_column(
        _enum(SensorStatus, "sensor_status_enum"), default=SensorStatus.ACTIVE
    )
    sensor_types: Mapped[list] = mapped_column(JSONB, default=list)
    battery_pct: Mapped[float] = mapped_column(Float, default=100.0)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (Index("ix_sensor_reading_node_ts", "node_id", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[str] = mapped_column(String(32), index=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rainfall_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_moisture_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    tilt_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    ingested_via: Mapped[str] = mapped_column(String(16), default="mqtt")


# ---------------------------------------------------------------------------
# Risk & alerting
# ---------------------------------------------------------------------------


class ZoneRisk(Base):
    """One row per risk computation. Latest row per zone is the live figure."""

    __tablename__ = "zone_risk"
    __table_args__ = (Index("ix_zone_risk_zone_time", "zone_id", "computed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    risk_score: Mapped[float] = mapped_column(Float)          # 0-100
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity_enum"))
    confidence: Mapped[float] = mapped_column(Float)          # 0-1
    contributing_factors: Mapped[list] = mapped_column(JSONB, default=list)

    model_probability: Mapped[float] = mapped_column(Float, default=0.0)
    rainfall_24h: Mapped[float] = mapped_column(Float, default=0.0)
    rainfall_72h: Mapped[float] = mapped_column(Float, default=0.0)
    antecedent_rain_15d: Mapped[float] = mapped_column(Float, default=0.0)
    soil_moisture_pct: Mapped[float] = mapped_column(Float, default=0.0)
    forecast_24h_mm: Mapped[float] = mapped_column(Float, default=0.0)
    sensor_health: Mapped[float] = mapped_column(Float, default=1.0)
    model_version: Mapped[str] = mapped_column(String(32), default="v1")
    trigger: Mapped[str] = mapped_column(String(32), default="scheduled")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    zone_name: Mapped[str] = mapped_column(String(128), default="")
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "alert_severity_enum"))
    risk_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    contributing_factors: Mapped[list] = mapped_column(JSONB, default=list)
    language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(32), default="auto")

    deliveries: Mapped[list["AlertDelivery"]] = relationship(
        back_populates="alert", cascade="all, delete-orphan", lazy="selectin"
    )


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(16))
    recipient: Mapped[str] = mapped_column(String(255), default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    status: Mapped[DeliveryStatus] = mapped_column(
        _enum(DeliveryStatus, "delivery_status_enum"), default=DeliveryStatus.PENDING
    )
    detail: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    alert: Mapped[Alert] = relationship(back_populates="deliveries")


# ---------------------------------------------------------------------------
# Human-in-the-loop
# ---------------------------------------------------------------------------


class CitizenReport(Base):
    __tablename__ = "citizen_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, default="")
    photo_path: Mapped[str] = mapped_column(String(255), default="")
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    phone: Mapped[str] = mapped_column(String(32), default="")
    language: Mapped[str] = mapped_column(String(8), default="en")

    # set by PostGIS ST_Contains against zones at insert time
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"), nullable=True)
    geo_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    geo_note: Mapped[str] = mapped_column(String(255), default="")

    status: Mapped[ReportStatus] = mapped_column(
        _enum(ReportStatus, "report_status_enum"), default=ReportStatus.PENDING
    )
    moderated_by: Mapped[str] = mapped_column(String(64), default="")
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    moderation_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class FieldReport(Base):
    __tablename__ = "field_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    # client-generated UUID makes offline replay idempotent
    client_uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    officer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    officer_name: Mapped[str] = mapped_column(String(128), default="")

    verdict: Mapped[Verdict] = mapped_column(_enum(Verdict, "verdict_enum"))
    notes: Mapped[str] = mapped_column(Text, default="")
    photo_path: Mapped[str] = mapped_column(String(255), default="")
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_offline: Mapped[bool] = mapped_column(Boolean, default=False)


class ResponseAction(Base):
    """Prioritised response list produced at the end of the demo timeline."""

    __tablename__ = "response_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    action: Mapped[str] = mapped_column(String(255))
    owner: Mapped[str] = mapped_column(String(128), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "Role", "Severity", "SensorStatus", "RoadStatus", "ReportStatus", "Verdict",
    "DeliveryStatus", "User", "ZoneAssignment", "AuditLog", "Zone",
    "RainfallReading", "SoilMoistureReading", "HistoricalLandslide",
    "WeatherFetch",
    "RoadSegment", "Village", "Bridge", "SensorNode", "SensorReading",
    "ZoneRisk", "Alert", "AlertDelivery", "CitizenReport", "FieldReport",
    "ResponseAction",
]
