"""real weather from Open-Meteo: forecast flag, raw VWC columns, fetch log

Revision ID: 0002_openmeteo
Revises: 0001_initial

Forecast rows now share the observation tables, so `is_forecast` is what keeps
trailing-window sums from quietly including the future. The vwc_* columns keep
Open-Meteo's raw m3/m3 values next to the derived degree-of-saturation, so the
unit conversion can be audited or re-derived without re-fetching.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_openmeteo"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rainfall_readings",
                  sa.Column("is_forecast", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_rainfall_readings_is_forecast", "rainfall_readings", ["is_forecast"])

    op.add_column("soil_moisture_readings",
                  sa.Column("is_forecast", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_soil_moisture_readings_is_forecast", "soil_moisture_readings", ["is_forecast"])
    for col in ("vwc_0_7cm", "vwc_0_1cm", "vwc_1_3cm"):
        op.add_column("soil_moisture_readings", sa.Column(col, sa.Float(), nullable=True))

    op.create_table(
        "weather_fetches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("endpoint", sa.String(32), nullable=False),
        sa.Column("zones", sa.Integer(), server_default="0", nullable=False),
        sa.Column("hours_written", sa.Integer(), server_default="0", nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ok", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("detail", sa.Text(), server_default="", nullable=False),
    )
    op.create_index("ix_weather_fetches_fetched_at", "weather_fetches", ["fetched_at"])


def downgrade() -> None:
    op.drop_index("ix_weather_fetches_fetched_at", table_name="weather_fetches")
    op.drop_table("weather_fetches")
    for col in ("vwc_1_3cm", "vwc_0_1cm", "vwc_0_7cm"):
        op.drop_column("soil_moisture_readings", col)
    op.drop_index("ix_soil_moisture_readings_is_forecast", table_name="soil_moisture_readings")
    op.drop_column("soil_moisture_readings", "is_forecast")
    op.drop_index("ix_rainfall_readings_is_forecast", table_name="rainfall_readings")
    op.drop_column("rainfall_readings", "is_forecast")
