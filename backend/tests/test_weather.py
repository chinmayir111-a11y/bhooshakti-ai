"""Open-Meteo ingest: unit conversion, and keeping forecast out of observations.

The conversion tests are pure. The database tests guard the one mistake that
would be invisible in the UI but wrong everywhere: letting forecast rows leak
into a "trailing 24 hours" sum.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.openmeteo import (
    VWC_DRY,
    VWC_SATURATED,
    HourlyRow,
    vwc_to_saturation_pct,
)

from .conftest import requires_db


# ------------------------------------------------- volumetric -> saturation


def test_dry_and_saturated_anchors_map_to_the_ends_of_the_scale():
    assert vwc_to_saturation_pct(VWC_DRY) == 0.0
    assert vwc_to_saturation_pct(VWC_SATURATED) == 100.0


def test_conversion_is_monotonic():
    values = [vwc_to_saturation_pct(v) for v in (0.20, 0.28, 0.35, 0.42, 0.50, 0.60)]
    assert values == sorted(values)


def test_values_outside_the_anchors_clamp_rather_than_overflow():
    assert vwc_to_saturation_pct(0.02) == 0.0
    assert vwc_to_saturation_pct(0.95) == 100.0


def test_missing_readings_stay_missing():
    """A gap must not silently become 0% saturation — that reads as bone dry."""
    assert vwc_to_saturation_pct(None) is None


def test_the_observed_regional_median_lands_in_a_usable_band():
    """Real ERA5 median across the monitored zones is ~0.417 m3/m3.

    Fusion ramps soil pressure between 55% and 90%, so the regional median has
    to sit inside that band or the term would be dead most of the time.
    """
    median = vwc_to_saturation_pct(0.417)
    assert 50.0 < median < 75.0


@pytest.mark.parametrize("vwc,expected", [(0.367, 42.0), (0.504, 91.0)])
def test_regional_percentiles_span_the_fusion_thresholds(vwc, expected):
    assert vwc_to_saturation_pct(vwc) == pytest.approx(expected, abs=1.5)


# ------------------------------------------------------------ forecast flag


def test_parsed_rows_carry_the_forecast_flag():
    now = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
    past = HourlyRow(1, now - timedelta(hours=3), 2.0, 0.4, None, None, is_forecast=False)
    ahead = HourlyRow(1, now + timedelta(hours=3), 2.0, 0.4, None, None, is_forecast=True)
    assert past.is_forecast is False
    assert ahead.is_forecast is True


@requires_db
def test_no_observation_is_dated_in_the_future(db):
    for table in ("rainfall_readings", "soil_moisture_readings"):
        stray = db.execute(text(
            f"SELECT COUNT(*) FROM {table} WHERE NOT is_forecast AND ts > NOW()"
        )).scalar_one()
        assert stray == 0, f"{table} has future-dated rows marked as observed"


@requires_db
def test_elapsed_forecast_rows_do_not_leave_a_hole_in_the_series(db):
    """Forecasts age into the past between weather refreshes.

    They keep their `is_forecast` flag until a refresh replaces them with the
    observation, so the recent end of the series can be forecast-only. The
    series builder must fall back to them rather than skipping those hours —
    otherwise a 24h rainfall total quietly loses its most recent hours and
    every risk score drifts low. (This is the bug the assertion originally
    here was hiding: it demanded the situation never arise, when in fact it
    arises constantly and simply has to be handled.)
    """
    from app.services.risk_service import _zone_series

    zone_id = db.execute(text("SELECT id FROM zones ORDER BY id LIMIT 1")).scalar_one()
    rain, soil, _ = _zone_series(db, zone_id)

    hours_available = db.execute(text("""
        SELECT COUNT(DISTINCT ts) FROM rainfall_readings
        WHERE zone_id = :z AND ts >= NOW() - INTERVAL '30 days' AND ts <= NOW()
    """), {"z": zone_id}).scalar_one()

    assert len(rain) == hours_available, "series skipped hours it had data for"
    assert len(soil) == len(rain), "rainfall and soil series must stay aligned"

    # And the most recent 24h must be essentially complete.
    assert len(rain) >= 24, "not enough history to compute a 24h total"


@requires_db
def test_the_series_never_reaches_into_the_future(db):
    """Whatever else happens, tomorrow must not appear in a trailing total."""
    from app.services.risk_service import _zone_series

    zone_id = db.execute(text("SELECT id FROM zones ORDER BY id LIMIT 1")).scalar_one()
    rain, _soil, _ = _zone_series(db, zone_id)

    within_window = db.execute(text("""
        SELECT COUNT(DISTINCT ts) FROM rainfall_readings
        WHERE zone_id = :z AND ts >= NOW() - INTERVAL '30 days' AND ts <= NOW()
    """), {"z": zone_id}).scalar_one()
    future = db.execute(text("""
        SELECT COUNT(DISTINCT ts) FROM rainfall_readings
        WHERE zone_id = :z AND ts > NOW()
    """), {"z": zone_id}).scalar_one()

    assert future > 0, "no forecast cached — refresh weather before running this"
    assert len(rain) == within_window, "future hours leaked into the trailing series"


@requires_db
def test_observation_wins_over_forecast_for_the_same_hour(db):
    """When both exist for an hour, the real observation must be the one used."""
    from app.services.risk_service import _zone_series

    zone_id = db.execute(text("SELECT id FROM zones ORDER BY id LIMIT 1")).scalar_one()
    hour = db.execute(text("""
        SELECT ts FROM rainfall_readings
        WHERE zone_id = :z AND NOT is_forecast AND ts <= NOW()
        ORDER BY ts DESC LIMIT 1
    """), {"z": zone_id}).scalar_one()

    observed = db.execute(text("""
        SELECT rainfall_mm FROM rainfall_readings
        WHERE zone_id = :z AND ts = :t AND NOT is_forecast
    """), {"z": zone_id, "t": hour}).scalar_one()

    rain, _soil, _ = _zone_series(db, zone_id)
    hours = db.execute(text("""
        SELECT DISTINCT ts FROM rainfall_readings
        WHERE zone_id = :z AND ts >= NOW() - INTERVAL '30 days' AND ts <= NOW()
        ORDER BY ts
    """), {"z": zone_id}).scalars().all()

    assert rain[hours.index(hour)] == pytest.approx(float(observed))


@requires_db
def test_trailing_window_stops_at_now(db):
    """The window ends at the present moment, never later.

    Superseded a stricter version of this test that asserted the series simply
    drops every forecast row. That is wrong once a forecast has aged into the
    past: those hours still need to be counted, they just must not extend past
    now. See test_elapsed_forecast_rows_do_not_leave_a_hole_in_the_series.
    """
    from app.services.risk_service import _zone_series

    zone_id = db.execute(text("SELECT id FROM zones ORDER BY id LIMIT 1")).scalar_one()
    rain, _soil, last_ts = _zone_series(db, zone_id)

    assert rain, "series is empty"
    assert last_ts is not None and last_ts <= datetime.now(timezone.utc)

    beyond_now = db.execute(text("""
        SELECT COUNT(*) FROM rainfall_readings WHERE zone_id = :z AND ts > NOW()
    """), {"z": zone_id}).scalar_one()
    total_rows = db.execute(text("""
        SELECT COUNT(*) FROM rainfall_readings
        WHERE zone_id = :z AND ts >= NOW() - INTERVAL '30 days'
    """), {"z": zone_id}).scalar_one()

    assert beyond_now > 0, "no forecast cached — refresh weather before running this"
    assert len(rain) < total_rows, "the future must be excluded from a trailing total"


@requires_db
def test_real_weather_is_actually_cached(db):
    """The claim on the dashboard is that rainfall is real. Check it is."""
    rows = db.execute(text(
        "SELECT COUNT(*) FROM rainfall_readings WHERE source = 'open-meteo'"
    )).scalar_one()
    zones = db.execute(text("SELECT COUNT(*) FROM zones")).scalar_one()
    assert rows > zones * 24 * 20, "cached Open-Meteo coverage looks too thin"


@requires_db
def test_raw_volumetric_values_are_kept_for_audit(db):
    """moisture_pct is derived; the source value must survive so the mapping
    can be re-derived without re-fetching."""
    row = db.execute(text(
        "SELECT vwc_0_7cm, moisture_pct FROM soil_moisture_readings "
        "WHERE source = 'open-meteo' AND vwc_0_7cm IS NOT NULL LIMIT 1"
    )).mappings().first()
    assert row is not None
    assert 0.0 < float(row["vwc_0_7cm"]) < 1.0, "raw VWC must stay in m3/m3"
    assert vwc_to_saturation_pct(row["vwc_0_7cm"]) == pytest.approx(
        float(row["moisture_pct"]), abs=0.05)


@requires_db
def test_sensor_readings_are_never_overwritten_by_a_weather_refresh(db):
    """Real telemetry outranks a weather model — and this is also what keeps a
    running demo storm intact when the cache refreshes underneath it."""
    from app.services import openmeteo

    zone_id = db.execute(text("SELECT id FROM zones ORDER BY id LIMIT 1")).scalar_one()
    hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    db.execute(text("""
        INSERT INTO rainfall_readings (zone_id, ts, rainfall_mm, source, is_forecast)
        VALUES (:z, :t, 99.0, 'sensor', FALSE)
        ON CONFLICT ON CONSTRAINT uq_rainfall_zone_hour
        DO UPDATE SET rainfall_mm = 99.0, source = 'sensor'
    """), {"z": zone_id, "t": hour})

    openmeteo.store(db, [openmeteo.HourlyRow(zone_id, hour, 0.1, 0.40, None, None, False)])

    kept = db.execute(text(
        "SELECT rainfall_mm, source FROM rainfall_readings WHERE zone_id = :z AND ts = :t"
    ), {"z": zone_id, "t": hour}).mappings().one()
    assert kept["source"] == "sensor"
    assert float(kept["rainfall_mm"]) == 99.0
