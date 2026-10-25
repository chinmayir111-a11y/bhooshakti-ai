"""Nearest safe place: direction words, rounding, and never an unsafe shelter."""
from __future__ import annotations

from sqlalchemy import text

from app.services.shelters import bearing, compass, nearest, rounded_metres

from .conftest import requires_db


def test_compass_words():
    assert compass(bearing(26.90, 88.30, 26.95, 88.30)) == "north"
    assert compass(bearing(26.90, 88.30, 26.95, 88.35)) == "north-east"
    assert compass(bearing(26.90, 88.30, 26.90, 88.25)) == "west"
    assert compass(359) == "north" and compass(200) == "south"


def test_distances_are_said_the_way_people_say_them():
    assert rounded_metres(812) == 800 and rounded_metres(76) == 100 and rounded_metres(2340) == 2300


@requires_db
def test_an_unsafe_shelter_is_never_suggested(tx_db):
    lat, lon = 26.5000, 88.0000          # empty spot, outside every zone
    for osm, name, dlat in (("t/1", "Near School", 0.002), ("t/2", "Far Hall", 0.01)):
        tx_db.execute(text("""INSERT INTO shelters (osm_id, name, kind, lat, lon, geom, source)
            VALUES (:o, :n, 'school', :la, :lo, ST_SetSRID(ST_MakePoint(:lo, :la), 4326), 'test')"""),
                      {"o": osm, "n": name, "la": lat + dlat, "lo": lon})
    assert nearest(tx_db, lat, lon)["name"] == "Near School"
    tx_db.execute(text("UPDATE shelters SET unsafe = true WHERE osm_id = 't/1'"))
    s = nearest(tx_db, lat, lon)
    assert s["name"] == "Far Hall" and s["direction"] == "north" and s["distance_m"] == 1100
