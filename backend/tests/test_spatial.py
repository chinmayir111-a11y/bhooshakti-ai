"""PostGIS spatial logic.

These run against a real PostGIS database on purpose. The claim being tested is
that zone lookup, road/zone intersection and cut-off analysis are done in SQL by
the database — mocking that away would test nothing at all.

Skipped automatically when no seeded database is reachable.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services import spatial

from .conftest import requires_db

pytestmark = requires_db


# ------------------------------------------------- ST_Contains: point in zone


def test_a_point_inside_a_zone_resolves_to_that_zone(db):
    zone = db.execute(text(
        "SELECT id, code, centroid_lat, centroid_lon FROM zones ORDER BY id LIMIT 1"
    )).mappings().one()

    found = spatial.locate_point(db, zone["centroid_lat"], zone["centroid_lon"])

    assert found["zone_id"] == zone["id"]
    assert found["geo_valid"] is True
    assert found["distance_km"] == 0.0
    assert zone["code"] in found["note"]


def test_a_point_far_outside_every_zone_is_flagged_with_the_nearest(db):
    # Bay of Bengal — comfortably outside every monitored hill zone.
    found = spatial.locate_point(db, 15.0, 88.0)

    assert found["zone_id"] is None
    assert found["geo_valid"] is False
    assert found["distance_km"] > 100
    assert "Outside every monitored zone" in found["note"]
    assert found["zone_code"], "the nearest zone must still be named for the moderator"


def test_locate_point_agrees_with_a_direct_st_contains_query(db):
    """The service must not diverge from the predicate it claims to use."""
    zones = db.execute(text(
        "SELECT id, centroid_lat, centroid_lon FROM zones ORDER BY id LIMIT 8"
    )).mappings().all()

    for z in zones:
        direct = db.execute(text("""
            SELECT id FROM zones
            WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
            LIMIT 1
        """), {"lat": z["centroid_lat"], "lon": z["centroid_lon"]}).scalar()
        assert spatial.locate_point(db, z["centroid_lat"], z["centroid_lon"])["zone_id"] == direct


def test_every_zone_polygon_is_valid_and_in_wgs84(db):
    bad = db.execute(text("""
        SELECT code FROM zones WHERE NOT ST_IsValid(geom) OR ST_SRID(geom) <> 4326
    """)).scalars().all()
    assert bad == [], f"invalid or mis-projected geometry: {bad}"


# --------------------------------------------- ST_Intersects: roads vs zones


def test_every_zone_has_at_least_one_road_crossing_it(db):
    orphans = db.execute(text("""
        SELECT z.code FROM zones z
        WHERE NOT EXISTS (
            SELECT 1 FROM road_segments r WHERE ST_Intersects(r.geom, z.geom)
        )
    """)).scalars().all()
    assert orphans == [], f"zones with no road exposure: {orphans}"


def test_roads_intersecting_a_zone_report_their_exposed_length(db):
    zone_id = db.execute(text("""
        SELECT z.id FROM zones z JOIN road_segments r ON ST_Intersects(r.geom, z.geom)
        GROUP BY z.id ORDER BY COUNT(*) DESC LIMIT 1
    """)).scalar_one()

    roads = spatial.roads_intersecting_zone(db, zone_id)

    assert roads
    for road in roads:
        assert road["exposed_km"] is not None
        assert road["exposed_km"] > 0
        assert road["exposed_km"] <= road["length_km"] + 0.01, \
            "the exposed portion cannot exceed the whole segment"


def test_a_zone_with_no_roads_returns_an_empty_list_not_an_error(db):
    # An id that cannot exist — the query must degrade cleanly.
    assert spatial.roads_intersecting_zone(db, 10_000_000) == []


# ----------------------------------------------- ST_DWithin: proximity cutoff


def test_villages_near_a_road_are_all_inside_the_radius(db):
    road_id = db.execute(text("""
        SELECT r.id FROM road_segments r JOIN villages v
          ON ST_DWithin(v.geom::geography, r.geom::geography, :radius)
        GROUP BY r.id ORDER BY COUNT(*) DESC LIMIT 1
    """), {"radius": spatial.CUTOFF_RADIUS_M}).scalar_one()

    near = spatial.villages_near_road(db, road_id)

    assert near
    for v in near:
        assert float(v["distance_m"]) <= spatial.CUTOFF_RADIUS_M
    distances = [float(v["distance_m"]) for v in near]
    assert distances == sorted(distances), "results must be nearest-first"


def test_a_tighter_radius_never_returns_more_settlements(db):
    road_id = db.execute(text("SELECT id FROM road_segments ORDER BY id LIMIT 1")).scalar_one()
    wide = spatial.villages_near_road(db, road_id, radius_m=5000)
    tight = spatial.villages_near_road(db, road_id, radius_m=500)
    assert len(tight) <= len(wide)
    assert {v["id"] for v in tight} <= {v["id"] for v in wide}


# ------------------------------------------------------ the blocking cascade


def test_blocking_a_road_marks_it_and_cuts_off_nearby_settlements(db):
    """The step-7 cascade, end to end, inside a rolled-back transaction."""
    zone_id = db.execute(text("""
        SELECT z.id FROM zones z
        JOIN road_segments r ON ST_Intersects(r.geom, z.geom)
        JOIN villages v ON ST_DWithin(v.geom::geography, r.geom::geography, :radius)
        WHERE r.criticality = 'lifeline'
        GROUP BY z.id ORDER BY COUNT(v.id) DESC LIMIT 1
    """), {"radius": spatial.CUTOFF_RADIUS_M}).scalar_one()

    result = spatial.block_road_in_zone(db, zone_id, note="test debris flow")

    assert result["road"] is not None
    assert result["road"]["status"] == "BLOCKED"
    assert result["villages_cut_off"], "a blocked lifeline must cut something off"

    persisted = db.execute(text(
        "SELECT status::text, status_note FROM road_segments WHERE id = :i"
    ), {"i": result["road"]["id"]}).mappings().one()
    assert persisted["status"] == "BLOCKED"
    assert persisted["status_note"] == "test debris flow"

    flagged = db.execute(text(
        "SELECT id FROM villages WHERE is_cut_off"
    )).scalars().all()
    assert set(v["id"] for v in result["villages_cut_off"]) <= set(flagged)


def test_reset_infrastructure_clears_every_flag(db):
    zone_id = db.execute(text("""
        SELECT z.id FROM zones z JOIN road_segments r ON ST_Intersects(r.geom, z.geom)
        GROUP BY z.id LIMIT 1
    """)).scalar_one()
    spatial.block_road_in_zone(db, zone_id, note="temporary")

    spatial.reset_infrastructure(db)

    assert db.execute(text("SELECT COUNT(*) FROM road_segments WHERE status <> 'OPEN'")).scalar_one() == 0
    assert db.execute(text("SELECT COUNT(*) FROM villages WHERE is_cut_off")).scalar_one() == 0


# --------------------------------------------------------------- geo outputs


def test_zones_geojson_is_wellformed_and_carries_risk(db):
    fc = spatial.zones_geojson(db)

    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) >= 20

    for feature in fc["features"]:
        assert feature["geometry"]["type"] == "Polygon"
        ring = feature["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1], "a polygon ring must close"

        props = feature["properties"]
        assert props["severity"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
        assert isinstance(props["contributing_factors"], list)
        # GeoJSON is lon/lat; the separate centroid field is lat/lon for Leaflet.
        lat, lon = props["centroid"]
        assert 20 < lat < 30 and 85 < lon < 97, "centroid outside North-East India"


@pytest.mark.parametrize("emitter,geom_type", [
    (spatial.roads_geojson, "LineString"),
    (spatial.villages_geojson, "Point"),
    (spatial.bridges_geojson, "Point"),
    (spatial.sensors_geojson, "Point"),
    (spatial.historical_geojson, "Point"),
])
def test_layer_emitters_produce_the_right_geometry(db, emitter, geom_type):
    fc = emitter(db)
    assert fc["type"] == "FeatureCollection"
    assert fc["features"]
    assert all(f["geometry"]["type"] == geom_type for f in fc["features"])


def test_dashboard_summary_counts_every_zone_exactly_once(db):
    summary = spatial.dashboard_summary(db)
    total_zones = db.execute(text("SELECT COUNT(*) FROM zones")).scalar_one()
    assert sum(summary["severity_counts"].values()) == total_zones
    assert summary["sensors_failed"] <= summary["sensors_total"]


def test_villages_in_zone_matches_st_contains(db):
    zone_id = db.execute(text("""
        SELECT z.id FROM zones z JOIN villages v ON ST_Contains(z.geom, v.geom)
        GROUP BY z.id ORDER BY COUNT(*) DESC LIMIT 1
    """)).scalar_one()

    service = {v["id"] for v in spatial.villages_in_zone(db, zone_id)}
    direct = set(db.execute(text("""
        SELECT v.id FROM villages v JOIN zones z ON z.id = :z
        WHERE ST_Contains(z.geom, v.geom)
    """), {"z": zone_id}).scalars().all())

    assert service == direct
    assert service, "the busiest zone must contain at least one settlement"
