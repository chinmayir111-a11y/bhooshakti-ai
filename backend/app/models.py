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


class AlertTier(str, enum.Enum):
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"


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
    """SYNTHETIC labelled events — only written by `seed.py --synthetic` for
    offline development. Real events live in `historical_events`."""

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


class HistoricalEvent(Base):
    """A REAL past landslide from a published inventory (NASA GLC, GSI
    Bhukosh) or a curated press/official record. Never synthetic."""

    __tablename__ = "historical_events"
    __table_args__ = (UniqueConstraint("source", "source_event_id", name="uq_historical_source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)          # NASA GLC | GSI Bhukosh | Curated
    source_event_id: Mapped[str] = mapped_column(String(64))
    occurred_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    time_known: Mapped[bool] = mapped_column(Boolean, default=False)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    state: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    location_accuracy: Mapped[str] = mapped_column(String(16), default="")
    trigger: Mapped[str] = mapped_column(String(32), default="")
    fatalities: Mapped[int] = mapped_column(Integer, default=0)
    source_url: Mapped[str] = mapped_column(Text, default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HistoricalWeather(Base):
    """ERA5 hourly rainfall + soil moisture around historical events, cached so
    training and the backtest never re-download. Keyed by the requested point
    rounded to 0.1°; the grid cell Open-Meteo actually used is stored too."""

    __tablename__ = "historical_weather"
    __table_args__ = (UniqueConstraint("cell", "ts", name="uq_hist_weather_cell_ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cell: Mapped[str] = mapped_column(String(24), index=True)      # "25.3,94.5"
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rainfall_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    vwc_0_7cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    grid_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    grid_lon: Mapped[float | None] = mapped_column(Float, nullable=True)


class ZoneWeatherGrid(Base):
    """Which model grid cell each zone's weather actually came from — what a
    judge needs to reproduce our numbers against Open-Meteo directly."""

    __tablename__ = "zone_weather_grid"
    __table_args__ = (UniqueConstraint("zone_id", "endpoint", name="uq_zone_grid_endpoint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(String(16))              # archive | forecast
    grid_lat: Mapped[float] = mapped_column(Float)
    grid_lon: Mapped[float] = mapped_column(Float)
    grid_elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    # simulated | hardware. Only a node registered as hardware may show the
    # LIVE dot — the dashboard never infers it from traffic alone.
    source: Mapped[str] = mapped_column(String(16), default="simulated",
                                        server_default=text("'simulated'"))


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

    # ADVISORY is machine-issued and unconfirmed; WARNING is human-confirmed or
    # a model CRITICAL. See app/services/escalation.py.
    tier: Mapped[str] = mapped_column(String(16), default=AlertTier.WARNING.value,
                                      server_default=text("'WARNING'"), index=True)
    # ACTIVE | CONFIRMED | DISMISSED — an advisory is closed one way or the other.
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE",
                                        server_default=text("'ACTIVE'"))
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("citizen_reports.id", ondelete="SET NULL"), nullable=True, index=True)
    # A WARNING upgraded from an advisory, or an all-clear following one.
    parent_alert_id: Mapped[int | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True)
    score_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)

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

    # Set by the offline queue (PWA / field app) so a replay is stored once.
    client_uuid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # web | pwa | sms | ivr — how the report reached us.
    channel: Mapped[str] = mapped_column(String(16), default="web", server_default=text("'web'"))
    voice_note_path: Mapped[str] = mapped_column(String(255), default="", server_default=text("''"))
    # Warning signs ticked by the reporter (services/signs.py keys).
    signs: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))

    # Auto-triage. Score 0-100 with the plain-language reasons behind it.
    corroboration_score: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    corroboration_reasons: Mapped[list] = mapped_column(JSONB, default=list)

    # Escalation ladder state. A report is "seen" once any moderator acts on it.
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str] = mapped_column(String(64), default="", server_default=text("''"))
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    advisory_alert_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_alert_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EscalationContact(Base):
    """Ordered call-out list per district. Level 0 is the on-duty moderator;
    every 10 unacknowledged minutes the ladder climbs one level."""

    __tablename__ = "escalation_contacts"
    __table_args__ = (Index("ix_escalation_district_level", "district", "level"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    district: Mapped[str] = mapped_column(String(128), index=True)
    level: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(128))
    designation: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    on_duty: Mapped[bool] = mapped_column(Boolean, default=True)


class Subscriber(Base):
    """A phone number registered for one zone's alerts — no smartphone needed
    (SMS JOIN <pincode>, or a missed call from the IVR)."""

    __tablename__ = "subscribers"
    __table_args__ = (UniqueConstraint("phone", "zone_id", name="uq_subscriber_zone"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), index=True)
    pincode: Mapped[str] = mapped_column(String(8), default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    source: Mapped[str] = mapped_column(String(16), default="sms")   # sms | ivr | web | seed
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Pincode(Base):
    """Postal code → place → monitored zone, so a keyword SMS can be located
    without GPS. Seeded for the demo districts only."""

    __tablename__ = "pincodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    pincode: Mapped[str] = mapped_column(String(8), index=True)
    place: Mapped[str] = mapped_column(String(128), index=True)
    district: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(64))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"), nullable=True)


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


class Volunteer(Base):
    """Gaon Prahari: a trained villager registered by an officer to one zone,
    who reads a manual rain gauge and texts the reading (`R 45`). Modelled on
    GSI's Darjeeling community pilot (gauge + threshold chart + whistle)."""

    __tablename__ = "volunteers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), index=True)
    place: Mapped[str] = mapped_column(String(120), default="")          # where the gauge stands
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    safe_place: Mapped[str] = mapped_column(String(160), default="")     # where the village goes on ALERT
    registered_by: Mapped[str] = mapped_column(String(64), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)     # seeded demo volunteer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VolunteerRainReading(Base):
    """One manual gauge reading: mm since the volunteer's previous reading."""

    __tablename__ = "volunteer_rain_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    volunteer_id: Mapped[int] = mapped_column(ForeignKey("volunteers.id", ondelete="CASCADE"), index=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), index=True)
    mm: Mapped[float] = mapped_column(Float)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    channel: Mapped[str] = mapped_column(String(16), default="sms")       # sms | app | app-offline
    client_uuid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    total_24h: Mapped[float] = mapped_column(Float, default=0.0)
    level: Mapped[str] = mapped_column(String(8), default="none")        # none | watch | alert
    source: Mapped[str] = mapped_column(String(32), default="volunteer gauge")


class Shelter(Base):
    """A building people can go to: school, community hall, hospital. Imported
    once from OpenStreetMap (scripts/import_shelters.py). An officer can mark
    one unsafe (e.g. it stands on the moving slope) and it is never suggested."""

    __tablename__ = "shelters"

    id: Mapped[int] = mapped_column(primary_key=True)
    osm_id: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="")            # school | community_centre | hospital ...
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True)
    unsafe: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    unsafe_note: Mapped[str] = mapped_column(String(300), default="", server_default=text("''"))
    unsafe_by: Mapped[str] = mapped_column(String(64), default="", server_default=text("''"))
    source: Mapped[str] = mapped_column(String(32), default="OpenStreetMap")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Earthquake(Base):
    """A USGS-catalogued earthquake near the North-East (feed cached every 15 min)."""

    __tablename__ = "earthquakes"

    id: Mapped[int] = mapped_column(primary_key=True)
    usgs_id: Mapped[str] = mapped_column(String(32), unique=True)
    mag: Mapped[float] = mapped_column(Float)
    place: Mapped[str] = mapped_column(String(200), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    depth_km: Mapped[float] = mapped_column(Float, default=0.0)
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    url: Mapped[str] = mapped_column(String(300), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "Role", "Severity", "SensorStatus", "RoadStatus", "ReportStatus", "Verdict",
    "DeliveryStatus", "User", "ZoneAssignment", "AuditLog", "Zone",
    "RainfallReading", "SoilMoistureReading", "HistoricalLandslide",
    "WeatherFetch",
    "RoadSegment", "Village", "Bridge", "SensorNode", "SensorReading",
    "ZoneRisk", "Alert", "AlertDelivery", "CitizenReport", "FieldReport",
    "ResponseAction", "AlertTier", "EscalationContact", "Subscriber", "Pincode",
    "HistoricalEvent", "HistoricalWeather", "ZoneWeatherGrid", "Volunteer", "VolunteerRainReading", "Shelter", "Earthquake",
]
