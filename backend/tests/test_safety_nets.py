"""The safety nets for when nobody is at the desk, and the guard against one
sender flooding the queue:

  * every officer on the ladder told, nobody answered -> ADVISORY anyway
  * two SOS from different senders close together  -> ADVISORY at once
  * one sender past the hourly limit -> folded into their latest card
  * a repeated SOS from the same sender -> the same card, never refused
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from .conftest import requires_db
from .test_escalation import _mine, _report, clean_advisories, pin_score  # noqa: F401  (fixtures)

pytestmark = requires_db


def _tag(db, report, sender: str) -> None:
    """What reports.submit writes for every new report: who sent it."""
    from app.deps import audit
    from app.services.escalation import SYSTEM
    audit(db, SYSTEM, "create", "citizen_report", report.id, detail={"sender": sender}, commit=False)
    db.flush()


def _sos(db, created, sender, zone_code="DJ-04"):
    r = _report(db, created, zone_code)
    r.issue_type = "sos"
    r.phone = ""
    db.flush()
    _tag(db, r, sender)
    return r


def test_nobody_answering_still_warns_the_area(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(40)                         # under the 60 timer, over the 30 floor
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    for minutes in (0, 10, 20, 29):
        escalation.tick(tx_db, now=t0 + timedelta(minutes=minutes))
    assert r.advisory_alert_id is None, "the last officer gets a full step to answer"

    acts = _mine(escalation.tick(tx_db, now=t0 + timedelta(minutes=30)), r)
    assert "advisory" in {a["action"] for a in acts}
    reason = tx_db.execute(text("SELECT score_breakdown->>'trigger' FROM alerts WHERE id = :i"),
                           {"i": r.advisory_alert_id}).scalar()
    assert "no officer answered" in reason


def test_nobody_answering_a_junk_report_stays_quiet(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(20)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    for minutes in (0, 10, 20, 30, 60):
        escalation.tick(tx_db, now=t0 + timedelta(minutes=minutes))
    assert r.advisory_alert_id is None


def test_two_sos_from_different_people_advise_at_once(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(40)
    t0 = datetime.now(timezone.utc)
    a = _sos(tx_db, t0, "device:aaa")
    escalation.tick(tx_db, now=t0)
    assert a.advisory_alert_id is None, "one SOS alone waits for a human"

    b = _sos(tx_db, t0 + timedelta(minutes=5), "device:bbb")
    acts = _mine(escalation.tick(tx_db, now=t0 + timedelta(minutes=5)), b)
    assert "advisory" in {x["action"] for x in acts}
    assert escalation.sos_senders(tx_db, b) == 2


def test_two_sos_from_the_same_person_are_not_a_crowd(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(40)
    t0 = datetime.now(timezone.utc)
    _sos(tx_db, t0, "device:aaa")
    b = _sos(tx_db, t0 + timedelta(minutes=5), "device:aaa")
    escalation.tick(tx_db, now=t0 + timedelta(minutes=5))
    assert b.advisory_alert_id is None


def test_one_sender_cannot_open_more_than_five_cards_an_hour(tx_db, pin_score, no_siren):
    from app.config import settings
    from app.routers import reports
    pin_score(10)
    z = tx_db.execute(text("SELECT centroid_lat, centroid_lon FROM zones WHERE code = 'DJ-04'")).one()
    ids = [reports.submit(tx_db, issue_type="crack", lat=z[0], lon=z[1], phone="+919000000077").id
           for _ in range(settings.report_limit_per_hour)]
    assert len(set(ids)) == settings.report_limit_per_hour

    extra = reports.submit(tx_db, issue_type="crack", lat=z[0], lon=z[1], phone="+919000000077")
    assert extra.id == ids[-1] and getattr(extra, "folded", False)
    other = reports.submit(tx_db, issue_type="crack", lat=z[0], lon=z[1], phone="+919000000078")
    assert other.id not in ids, "a different person is not limited"


def test_sos_is_never_refused_and_repeats_join_one_card(tx_db, pin_score, no_siren):
    from app.config import settings
    from app.routers import reports
    pin_score(10)
    z = tx_db.execute(text("SELECT centroid_lat, centroid_lon FROM zones WHERE code = 'DJ-04'")).one()
    for _ in range(settings.report_limit_per_hour):          # use up the hourly limit
        reports.submit(tx_db, issue_type="crack", lat=z[0], lon=z[1], device_id="dev-1")
    first = reports.submit(tx_db, issue_type="sos", lat=z[0], lon=z[1], device_id="dev-1")
    assert not getattr(first, "folded", False), "the limit never blocks an SOS"
    again = reports.submit(tx_db, issue_type="sos", lat=z[0], lon=z[1], device_id="dev-1")
    assert again.id == first.id


def test_weather_job_pulls_recent_rain_then_rescores_with_alerts_on(monkeypatch):
    """The 30-minute job: a short pull (not the 30-day history), then every
    zone rescored with alerts allowed. Network and database calls are stubbed."""
    from contextlib import contextmanager

    from app.config import settings
    from app.services import weather_job

    calls = {}

    @contextmanager
    def fake_session():
        yield "db"

    monkeypatch.setattr(weather_job, "session_scope", fake_session)
    monkeypatch.setattr(weather_job.openmeteo, "refresh",
                        lambda db, history_days=None: calls.setdefault("refresh", history_days) and {"ok": True} or {"ok": True})
    monkeypatch.setattr(weather_job.risk_service, "recompute_all",
                        lambda db, trigger, raise_alerts: calls.update(trigger=trigger, alerts=raise_alerts) or
                        [{"alert_id": None}, {"alert_id": 7}])
    monkeypatch.setattr(settings, "weather_provider", "open-meteo")

    out = weather_job.run_once()
    assert calls["refresh"] == settings.weather_archive_lag_days + 2
    assert calls == {**calls, "trigger": "weather-refresh", "alerts": True}
    assert out["zones"] == 2 and out["alerts"] == [7]
