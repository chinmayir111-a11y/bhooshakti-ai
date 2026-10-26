"""citizen-report triage + escalation, alert tiers, offline channels,
sensor provenance, real historical events

Revision ID: 0003_triage_offline
Revises: 0002_openmeteo
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_triage_offline"
down_revision = "0002_openmeteo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- citizen report triage ------------------------------------------------
    for name, col in (
        ("client_uuid", sa.Column("client_uuid", sa.String(64), nullable=True, unique=True)),
        ("channel", sa.Column("channel", sa.String(16), nullable=False, server_default="web")),
        ("voice_note_path", sa.Column("voice_note_path", sa.String(255), nullable=False, server_default="")),
        ("corroboration_score", sa.Column("corroboration_score", sa.Float(), nullable=False, server_default="0")),
        ("corroboration_reasons", sa.Column("corroboration_reasons", JSONB(), nullable=True)),
        ("acknowledged_at", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True)),
        ("acknowledged_by", sa.Column("acknowledged_by", sa.String(64), nullable=False, server_default="")),
        ("escalation_level", sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0")),
        ("last_escalated_at", sa.Column("last_escalated_at", sa.DateTime(timezone=True), nullable=True)),
        ("advisory_alert_id", sa.Column("advisory_alert_id", sa.Integer(), nullable=True)),
        ("warning_alert_id", sa.Column("warning_alert_id", sa.Integer(), nullable=True)),
    ):
        op.add_column("citizen_reports", col)

    # --- alert tiers ------------------------------------------------------------
    op.add_column("alerts", sa.Column("tier", sa.String(16), nullable=False, server_default="WARNING"))
    op.create_index("ix_alerts_tier", "alerts", ["tier"])
    op.add_column("alerts", sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"))
    op.add_column("alerts", sa.Column("report_id", sa.Integer(),
                                      sa.ForeignKey("citizen_reports.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_alerts_report_id", "alerts", ["report_id"])
    op.add_column("alerts", sa.Column("parent_alert_id", sa.Integer(),
                                      sa.ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True))
    op.add_column("alerts", sa.Column("score_breakdown", JSONB(), nullable=True))

    # --- sensor provenance --------------------------------------------------------
    op.add_column("sensor_nodes", sa.Column("source", sa.String(16), nullable=False, server_default="simulated"))

    # --- escalation roster, subscribers, pincodes ------------------------------------
    op.create_table(
        "escalation_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("district", sa.String(128), nullable=False, index=True),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("designation", sa.String(128), nullable=False, server_default=""),
        sa.Column("phone", sa.String(32), nullable=False, server_default=""),
        sa.Column("email", sa.String(255), nullable=False, server_default=""),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("on_duty", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_escalation_district_level", "escalation_contacts", ["district", "level"])
    op.create_table(
        "subscribers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.String(32), nullable=False, index=True),
        sa.Column("zone_id", sa.Integer(), sa.ForeignKey("zones.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("pincode", sa.String(8), nullable=False, server_default=""),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("source", sa.String(16), nullable=False, server_default="sms"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("phone", "zone_id", name="uq_subscriber_zone"),
    )
    op.create_table(
        "pincodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pincode", sa.String(8), nullable=False, index=True),
        sa.Column("place", sa.String(128), nullable=False, index=True),
        sa.Column("district", sa.String(128), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("zone_id", sa.Integer(), sa.ForeignKey("zones.id", ondelete="SET NULL"), nullable=True),
    )

    # --- real historical events + ERA5 cache + zone grid provenance -----------------
    op.create_table(
        "historical_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False, index=True),
        sa.Column("source_event_id", sa.String(64), nullable=False),
        sa.Column("occurred_on", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("time_known", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("geom", Geometry("POINT", srid=4326, spatial_index=True), nullable=False),
        sa.Column("state", sa.String(64), nullable=False, server_default=""),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("location_accuracy", sa.String(16), nullable=False, server_default=""),
        sa.Column("trigger", sa.String(32), nullable=False, server_default=""),
        sa.Column("fatalities", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source", "source_event_id", name="uq_historical_source_id"),
    )
    op.create_table(
        "historical_weather",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cell", sa.String(24), nullable=False, index=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rainfall_mm", sa.Float(), nullable=True),
        sa.Column("vwc_0_7cm", sa.Float(), nullable=True),
        sa.Column("grid_lat", sa.Float(), nullable=True),
        sa.Column("grid_lon", sa.Float(), nullable=True),
        sa.UniqueConstraint("cell", "ts", name="uq_hist_weather_cell_ts"),
    )
    op.create_table(
        "zone_weather_grid",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("zone_id", sa.Integer(), sa.ForeignKey("zones.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.String(16), nullable=False),
        sa.Column("grid_lat", sa.Float(), nullable=False),
        sa.Column("grid_lon", sa.Float(), nullable=False),
        sa.Column("grid_elevation_m", sa.Float(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("zone_id", "endpoint", name="uq_zone_grid_endpoint"),
    )


def downgrade() -> None:
    for t in ("zone_weather_grid", "historical_weather", "historical_events", "pincodes",
              "subscribers", "escalation_contacts"):
        op.drop_table(t)
    op.drop_column("sensor_nodes", "source")
    for c in ("score_breakdown", "parent_alert_id", "report_id", "status", "tier"):
        op.drop_column("alerts", c)
    for c in ("warning_alert_id", "advisory_alert_id", "last_escalated_at", "escalation_level",
              "acknowledged_by", "acknowledged_at", "corroboration_reasons", "corroboration_score",
              "voice_note_path", "channel", "client_uuid"):
        op.drop_column("citizen_reports", c)
