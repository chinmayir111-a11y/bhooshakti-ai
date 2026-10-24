"""Real-event import (NASA GLC parsing + NE-India filter) and backtest scoring."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

import pytest

from ml.backtest import HIGH, evaluate_event, evaluate_window, first_alert, summarise

from .conftest import requires_db
from scripts.import_landslides import (
    Event,
    filter_ne_india,
    non_event_year,
    normalise_state,
    parse_glc_row,
)

UTC = timezone.utc


def glc(**kw) -> dict:
    row = {"event_id": "1", "event_date": "07/17/2013 12:00:00 AM", "event_title": "NH 29 near Kohima",
           "country_name": "India", "admin_division_name": "Nagaland", "latitude": "25.71",
           "longitude": "94.08", "landslide_trigger": "downpour", "fatality_count": "3",
           "location_accuracy": "5km", "source_link": "http://example.org/a"}
    row.update(kw)
    return row


# ------------------------------------------------------------------ import


def test_state_names_lose_diacritics():
    assert normalise_state("Nāgāland") == "Nagaland"
    assert normalise_state("Arunāchal Pradesh") == "Arunachal Pradesh"
    assert normalise_state("Meghālaya ") == "Meghalaya"


def test_parse_glc_row():
    ev = parse_glc_row(glc())
    assert ev.day == date(2013, 7, 17) and ev.state == "Nagaland"
    assert (ev.lat, ev.lon, ev.fatalities, ev.trigger) == (25.71, 94.08, 3, "downpour")
    assert ev.source == "NASA GLC" and ev.source_url == "http://example.org/a"
    assert ev.time_ist is None, "GLC gives a date, not a time — never invent one"


def test_unparseable_rows_are_dropped():
    assert parse_glc_row(glc(latitude="")) is None
    assert parse_glc_row(glc(event_date="not a date")) is None


def test_filter_keeps_only_the_eight_ne_states_inside_india():
    rows = [
        glc(event_id="1"),
        glc(event_id="2", admin_division_name="Nāgāland"),
        glc(event_id="3", admin_division_name="Sikkim", latitude="27.33", longitude="88.61"),
        glc(event_id="4", admin_division_name="Tripura", latitude="23.8", longitude="91.3"),
        glc(event_id="5", admin_division_name="Uttarakhand", latitude="30.3", longitude="78.0"),
        glc(event_id="6", admin_division_name="Bengal", latitude="27.04", longitude="88.26"),  # Darjeeling: WB
        glc(event_id="7", country_name="Nepal", admin_division_name="Sikkim"),
        glc(event_id="8", latitude="12.0"),               # tagged Nagaland but in the sea: bbox guard
    ]
    kept = [e.source_event_id for e in filter_ne_india(rows)]
    assert kept == ["1", "2", "3", "4"]


def test_non_event_year_avoids_any_catalogued_event_nearby():
    ev = Event("NASA GLC", "a", date(2013, 7, 17), 25.7, 94.1, "Nagaland", "", "", 0, "", "")
    clash = Event("NASA GLC", "b", date(2010, 7, 30), 25.8, 94.0, "Nagaland", "", "", 0, "", "")   # ~15 km, 13 days
    far = Event("NASA GLC", "c", date(2011, 7, 17), 23.7, 92.7, "Mizoram", "", "", 0, "", "")     # ~270 km
    for seed in range(20):
        y = non_event_year(ev, [ev, clash, far], [2010, 2011, 2013], random.Random(seed))
        assert y == 2011


def test_non_event_year_can_be_none():
    ev = Event("NASA GLC", "a", date(2013, 7, 17), 25.7, 94.1, "", "", "", 0, "", "")
    assert non_event_year(ev, [ev], [2013], random.Random(1)) is None


# ---------------------------------------------------------------- backtest


def tl(start: datetime, scores: list[float]) -> list[tuple[datetime, float]]:
    return [(start + timedelta(hours=i), s) for i, s in enumerate(scores)]


T0 = datetime(2016, 7, 1, tzinfo=UTC)


def test_lead_time_is_reference_minus_first_high():
    ref = T0 + timedelta(hours=100)
    scores = [10.0] * 90 + [55.0] * 30          # HIGH from hour 90
    r = evaluate_event(tl(T0, scores), ref, ref + timedelta(hours=24))
    assert r["outcome"] == "warned_before" and r["lead_hours"] == 10.0
    assert r["first_alert"] == (T0 + timedelta(hours=90)).isoformat()


def test_a_run_that_started_before_the_window_is_followed_back():
    ref = T0 + timedelta(hours=150)
    scores = [10.0] * 20 + [60.0] * 140          # HIGH since hour 20, window opens at 78
    r = evaluate_event(tl(T0, scores), ref, ref + timedelta(hours=24))
    assert r["lead_hours"] == 130.0


def test_an_old_episode_that_ended_does_not_count():
    ref = T0 + timedelta(hours=150)
    scores = [70.0] * 10 + [10.0] * 150           # HIGH only long before the 72 h window
    r = evaluate_event(tl(T0, scores), ref, ref + timedelta(hours=24))
    assert r["outcome"] == "missed" and r["lead_hours"] is None


def test_first_high_during_the_event_day_is_same_day_not_a_warning():
    ref = T0 + timedelta(hours=100)               # start of event day
    scores = [10.0] * 106 + [58.0] * 10            # HIGH at 06:00 on the day
    r = evaluate_event(tl(T0, scores), ref, ref + timedelta(hours=24))
    assert r["outcome"] == "same_day" and r["lead_hours"] == -6.0


def test_threshold_is_the_high_band_and_exactly_50_counts():
    assert HIGH == 50.0
    ref = T0 + timedelta(hours=50)
    r = evaluate_event(tl(T0, [49.9] * 40 + [50.0] + [10.0] * 20), ref, ref + timedelta(hours=24))
    assert r["outcome"] == "warned_before" and r["lead_hours"] == 10.0
    assert first_alert(tl(T0, [49.9] * 10), T0, T0 + timedelta(hours=10)) is None


def test_window_false_alarm_and_summary_counts():
    quiet = evaluate_window(tl(T0, [5.0] * 48))
    noisy = evaluate_window(tl(T0, [5.0] * 40 + [52.0] * 3 + [5.0] * 5))
    assert quiet == {"false_alarm": False, "hours_high": 0, "first_alert": None, "peak_score": 5.0}
    assert noisy["false_alarm"] and noisy["hours_high"] == 3

    events = [{"outcome": "warned_before", "lead_hours": 12.0},
              {"outcome": "warned_before", "lead_hours": 30.0},
              {"outcome": "same_day", "lead_hours": -3.0},
              {"outcome": "missed", "lead_hours": None}]
    s = summarise(events, [quiet, noisy], [quiet])
    assert (s["warned_before"], s["warned_same_day"], s["missed"]) == (2, 1, 1)
    assert s["median_lead_hours"] == 21.0
    assert s["non_event_false_alarms"] == 1 and s["dry_false_alarms"] == 0
    assert s["headline"].startswith("Warned before 2 of 4 held-out landslides")


# -------------------------------------------------------------- custom replay


@requires_db
def test_custom_replay_validates_input(client):
    from datetime import date as _d
    assert client.post("/replay/custom", json={"date": "2024-05-28"}).status_code == 422
    assert client.post("/replay/custom", json={"pincode": "000000", "date": "2024-05-28"}).status_code == 404
    too_recent = (_d.today()).isoformat()
    assert client.post("/replay/custom", json={"pincode": "796001", "date": too_recent}).status_code == 422


@requires_db
def test_custom_replay_reuses_the_cached_aizawl_window(client):
    """Aizawl 2024's ERA5 window is already cached by import_landslides, so this
    needs no network: the custom replay must give the same verdict the
    catalogued event gets."""
    # Date only: the reference is the start of the day, and Aizawl's 02:30 IST
    # alert lands AFTER midnight — a same-day crossing, honestly labelled.
    r = client.post("/replay/custom", json={"lat": 23.684, "lon": 92.715, "date": "2024-05-28", "label": "Hlimen"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event"]["source"] == "Your input" and body["event"]["title"] == "Hlimen"
    assert body["provenance"]["weather_fetch"] == "cached"
    assert body["verdict"]["outcome"] == "same_day" and body["verdict"]["first_alert"]
    assert len(body["hours"]) > 24 * 7

    # With the recorded time (06:00 IST) it matches the catalogued verdict.
    r = client.post("/replay/custom", json={"lat": 23.684, "lon": 92.715, "date": "2024-05-28", "time": "06:00"})
    v = r.json()["verdict"]
    assert v["outcome"] == "warned_before" and v["lead_hours"] == 3.5
