"""Earthquake trigger: distance and decay maths, and nothing invented when the
USGS feed cannot be reached."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.services import quakes
from app.services.quakes import boost_points, km

from .conftest import requires_db


def test_distance():
    assert abs(km(26.95, 88.32, 26.95, 88.32)) < 1e-6
    assert 105 < km(26.0, 91.0, 27.0, 91.0) < 116          # one degree of latitude


def test_boost_fades_with_time_and_distance_and_is_bounded():
    assert boost_points(5.1, 32, 0) > boost_points(5.1, 32, 48) > 0
    assert boost_points(5.1, 10, 24) > boost_points(5.1, 45, 24)
    assert boost_points(5.1, 32, 72.1) == 0 and boost_points(5.1, 51, 1) == 0 and boost_points(4.4, 5, 1) == 0
    assert boost_points(8.0, 0, 0) == quakes.MAX_BOOST


def test_unreachable_feed_adds_nothing_and_says_so():
    f = quakes.Feed()
    def broken(*a, **k):
        raise OSError("no network")
    assert f.fetch(opener=broken) == 0
    assert f.last_error == "earthquake feed unavailable (OSError)"


@requires_db
def test_a_cached_nearby_quake_raises_the_zone_with_a_plain_reason(tx_db, monkeypatch):
    from app.models import Zone
    from app.services import risk_service
    zone = tx_db.query(Zone).filter(Zone.code == "SK-02").one()
    before = risk_service.compute_zone_risk(tx_db, zone, raise_alerts=False)["risk_score"]
    t = datetime.now(timezone.utc) - timedelta(hours=10)
    tx_db.execute(text("""INSERT INTO earthquakes (usgs_id, mag, place, occurred_at, lat, lon, depth_km, geom, url)
        VALUES ('test1', 5.1, 'test', :t, :la, :lo, 10, ST_SetSRID(ST_MakePoint(:lo, :la), 4326), '')"""),
                  {"t": t, "la": zone.centroid_lat + 0.2, "lo": zone.centroid_lon})
    after = risk_service.compute_zone_risk(tx_db, zone, raise_alerts=False)
    assert after["risk_score"] > before
    assert after["contributing_factors"][0]["key"] == "earthquake"
    assert after["contributing_factors"][0]["text"].startswith("M5.1 earthquake 22 km away, 10 h ago")
