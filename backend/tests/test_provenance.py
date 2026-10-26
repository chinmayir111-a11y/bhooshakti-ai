"""Data provenance: every weather number can be traced to an endpoint, a
model, a grid cell and a URL a judge can open themselves."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from sqlalchemy import text

from app.services import openmeteo

from .conftest import requires_db


def test_verify_urls_reproduce_the_request_we_make():
    urls = openmeteo.verify_urls(26.953, 88.321)
    f = urlparse(urls["forecast"])
    q = parse_qs(f.query)
    assert f.netloc == "api.open-meteo.com"
    assert q["latitude"] == ["26.953"] and q["longitude"] == ["88.321"]
    assert "precipitation" in q["hourly"][0] and "soil_moisture_0_to_7cm" in q["hourly"][0]
    a = parse_qs(urlparse(urls["archive"]).query)
    assert a["start_date"][0] < a["end_date"][0]


@requires_db
def test_zone_provenance_names_model_grid_and_fetch_time(client, tx_db):
    zone_id = tx_db.execute(text("SELECT id FROM zones WHERE code = 'DJ-04'")).scalar()
    p = client.get(f"/weather/zone/{zone_id}/provenance").json()
    assert p["zone_code"] == "DJ-04"
    endpoints = {s["endpoint"] for s in p["sources"]}
    assert any("archive-api.open-meteo.com" in e for e in endpoints)
    assert any("ERA5" in s["model"] for s in p["sources"])
    for s in p["sources"]:
        assert s["grid"] is not None, "grid cell must be recorded on refresh"
        # The model cell is near, but not exactly at, the requested point.
        assert abs(s["grid"]["lat"] - p["requested_point"]["lat"]) < 0.3
    assert p["verify_live"]["forecast"].startswith("https://api.open-meteo.com/v1/forecast?")


@requires_db
def test_sensors_carry_source_and_only_hardware_can_be_live(client):
    fc = client.get("/sensors").json()
    props = {f["properties"]["node_id"]: f["properties"] for f in fc["features"]}
    assert props["HW-01"]["source"] == "hardware"
    assert props["KB-01"]["source"] == "simulated"
    assert all(not p["live"] for p in props.values() if p["source"] != "hardware")


@requires_db
def test_rain_frames_are_hourly_per_zone(client):
    body = client.get("/weather/rain-frames?hours=12").json()
    assert body["frames"], "cached Open-Meteo rainfall expected"
    f = body["frames"][0]
    assert set(f) == {"ts", "forecast", "zones"} and f["zones"]
