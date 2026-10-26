"""Escalation ladder timings, with time frozen by passing `now` explicitly.

The score itself is pinned per test (corroboration has its own tests), so
these exercise only the ladder: T+0 moderator, T+10 next officer, T+20
advisory at score >= 60, immediate advisory at score >= 85, and the human
CONFIRM / DISMISS decisions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from .conftest import requires_db

pytestmark = requires_db


@pytest.fixture(autouse=True)
def clean_advisories(tx_db):
    """Advisories left ACTIVE by a demo run would make a new report join them
    instead of issuing its own. Close them inside the test transaction."""
    # Open demo reports would be worked by tick() too and could issue the
    # advisory this test's report then joins: mark them seen for the test.
    tx_db.execute(text("UPDATE citizen_reports SET advisory_alert_id = NULL, acknowledged_at = NOW(), "
                       "acknowledged_by = 'test-fixture' WHERE status = 'PENDING' AND acknowledged_at IS NULL"))
    tx_db.execute(text("UPDATE alerts SET status = 'SUPERSEDED' WHERE tier = 'ADVISORY' AND status = 'ACTIVE'"))
    tx_db.flush()


@pytest.fixture()
def pin_score(monkeypatch):
    """pin_score(n) makes every report score exactly n."""
    from app.services import corroboration

    box = {"score": 0.0}

    def fake(db, report, now=None):
        reasons = [{"key": "pinned", "points": int(box["score"]), "text": f"pinned at {box['score']}"}]
        report.corroboration_score = box["score"]
        report.corroboration_reasons = reasons
        return box["score"], reasons

    monkeypatch.setattr(corroboration, "score_report", fake)
    return lambda n: box.__setitem__("score", float(n))


def _report(db, created: datetime, zone_code: str = "DJ-04"):
    from app.models import CitizenReport, ReportStatus
    z = db.execute(text("SELECT id, centroid_lat AS lat, centroid_lon AS lon FROM zones WHERE code = :c"),
                   {"c": zone_code}).mappings().one()
    r = CitizenReport(issue_type="landslide", lat=z["lat"], lon=z["lon"],
                      geom=f"SRID=4326;POINT({z['lon']} {z['lat']})", phone="+919999900001",
                      zone_id=z["id"], geo_valid=True, status=ReportStatus.PENDING, created_at=created)
    db.add(r)
    db.flush()
    return r


def _mine(actions, report):
    """tick() works every open report in the database, including live demo
    data; the assertions are about this test's report only."""
    return [a for a in actions if a["report_id"] == report.id]


def _audit(db, report_id: int) -> list[str]:
    return [r[0] for r in db.execute(text(
        "SELECT action FROM audit_log WHERE resource = 'citizen_report' AND resource_id = :i ORDER BY id"
    ), {"i": str(report_id)})]


def test_ladder_climbs_every_ten_minutes_until_acknowledged(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(20)                                  # below every advisory threshold
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)

    acts = _mine(escalation.tick(tx_db, now=t0), r)
    assert acts == [{"report_id": r.id, "action": "notify_moderator", "level": 0}]
    assert r.escalation_level == 1

    assert _mine(escalation.tick(tx_db, now=t0 + timedelta(minutes=9, seconds=59)), r) == []

    acts = _mine(escalation.tick(tx_db, now=t0 + timedelta(minutes=10)), r)
    assert acts == [{"report_id": r.id, "action": "escalate", "level": 1}]

    acts = _mine(escalation.tick(tx_db, now=t0 + timedelta(minutes=20)), r)
    assert acts == [{"report_id": r.id, "action": "escalate", "level": 2}]
    assert r.advisory_alert_id is None, "score 20 must never auto-advise"

    # Roster has three levels; the ladder stops at the top instead of looping.
    assert _mine(escalation.tick(tx_db, now=t0 + timedelta(minutes=45)), r) == []
    assert _audit(tx_db, r.id).count("escalate") == 2


def test_acknowledged_report_stops_the_clock(tx_db, pin_score, no_siren):
    from app.deps import Principal
    from app.services import escalation
    pin_score(90)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    escalation.acknowledge(tx_db, r, Principal(1, "authority", "authority"))
    tx_db.flush()
    assert _mine(escalation.tick(tx_db, now=t0 + timedelta(minutes=30)), r) == []
    assert r.advisory_alert_id is None


def test_score_60_advises_at_twenty_minutes_not_before(tx_db, pin_score, no_siren):
    from app.models import Alert
    from app.services import escalation
    pin_score(60)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)

    escalation.tick(tx_db, now=t0)
    escalation.tick(tx_db, now=t0 + timedelta(minutes=19, seconds=59))
    assert r.advisory_alert_id is None

    acts = _mine(escalation.tick(tx_db, now=t0 + timedelta(minutes=20)), r)
    assert {"advisory"} <= {a["action"] for a in acts}
    alert = tx_db.get(Alert, r.advisory_alert_id)
    assert alert.tier == "ADVISORY" and alert.status == "ACTIVE"
    assert alert.report_id == r.id
    assert "Unverified public reports of a landslide near" in alert.message
    assert "await official confirmation" in alert.message
    assert alert.score_breakdown["corroboration_score"] == 60
    assert "auto_advisory" in _audit(tx_db, r.id)
    assert no_siren == [], "an ADVISORY never sounds the siren"


def test_score_59_never_advises_on_the_timer(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(59)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    # Past the 20-minute timer, before the ladder runs out at 30 (after which
    # test_safety_nets' "nobody answered" rule takes over).
    escalation.tick(tx_db, now=t0 + timedelta(minutes=25))
    assert r.advisory_alert_id is None


def test_score_85_advises_immediately(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(85)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    acts = _mine(escalation.tick(tx_db, now=t0 + timedelta(seconds=30)), r)
    assert [a["action"] for a in acts] == ["notify_moderator", "advisory"]
    assert r.advisory_alert_id is not None


def test_outside_every_zone_escalates_but_cannot_advise(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(95)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    r.zone_id = None
    tx_db.flush()
    acts = _mine(escalation.tick(tx_db, now=t0 + timedelta(minutes=25)), r)
    assert "advisory" not in {a["action"] for a in acts}
    assert r.escalation_level >= 2


def test_confirm_upgrades_to_warning_and_sounds_siren(tx_db, pin_score, no_siren):
    from app.deps import Principal
    from app.models import Alert, ReportStatus
    from app.services import escalation
    pin_score(90)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    escalation.tick(tx_db, now=t0)
    advisory = tx_db.get(Alert, r.advisory_alert_id)

    warning = escalation.confirm(tx_db, r, Principal(1, "authority", "authority"))
    assert warning.tier == "WARNING"
    assert warning.parent_alert_id == advisory.id
    assert advisory.status == "CONFIRMED"
    assert r.status is ReportStatus.APPROVED and r.acknowledged_at is not None
    assert [t for t, _ in no_siren] == [f"bhooshakti/siren/{r.zone_id}"]
    assert no_siren[0][1]["alert_id"] == warning.id
    # Same people the advisory reached, nobody new.
    adv_sms = {d.recipient for d in advisory.deliveries if d.channel == "sms"}
    warn_sms = {d.recipient for d in warning.deliveries if d.channel == "sms"}
    assert adv_sms <= warn_sms


def test_dismiss_sends_all_clear_to_the_same_recipients(tx_db, pin_score, no_siren):
    from app.deps import Principal
    from app.models import Alert, ReportStatus
    from app.services import escalation
    pin_score(90)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    escalation.tick(tx_db, now=t0)
    advisory = tx_db.get(Alert, r.advisory_alert_id)

    follow = escalation.dismiss(tx_db, r, Principal(1, "authority", "authority"), "debris was old")
    assert r.status is ReportStatus.REJECTED
    assert advisory.status == "DISMISSED"
    assert follow.parent_alert_id == advisory.id
    assert "false report" in follow.message.lower()

    def who(a, ch):
        return {d.recipient for d in a.deliveries if d.channel == ch}
    for ch in ("sms", "voice", "email"):
        assert who(follow, ch) == who(advisory, ch), ch
    assert no_siren == []


def test_schedule_reports_the_next_step_for_countdowns(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(70)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    escalation.tick(tx_db, now=t0)
    s = escalation.schedule(tx_db, r, now=t0)
    assert s["open"] and s["level"] == 1
    assert datetime.fromisoformat(s["next_step_at"]) == t0 + timedelta(minutes=10)
    assert datetime.fromisoformat(s["advisory_at"]) == t0 + timedelta(minutes=20)


def test_second_report_of_the_same_slide_joins_the_open_advisory(tx_db, pin_score, no_siren):
    from app.deps import Principal
    from app.models import Alert
    from app.services import escalation
    pin_score(90)
    t0 = datetime.now(timezone.utc)
    a = _report(tx_db, t0)
    b = _report(tx_db, t0 + timedelta(minutes=3))
    escalation.tick(tx_db, now=t0 + timedelta(minutes=4))
    assert a.advisory_alert_id is not None
    assert b.advisory_alert_id == a.advisory_alert_id, "one incident, one advisory"
    assert "advisory_joined" in _audit(tx_db, b.id)

    # Dismissing one of the two does not all-clear the zone while the other is open.
    me = Principal(1, "authority", "authority")
    assert escalation.dismiss(tx_db, b, me) is None
    assert tx_db.get(Alert, a.advisory_alert_id).status == "ACTIVE"
    follow = escalation.dismiss(tx_db, a, me)
    assert follow is not None and tx_db.get(Alert, a.advisory_alert_id).status == "DISMISSED"


def test_confirm_turns_the_zone_itself_critical(tx_db, pin_score, no_siren):
    """The map colours zones from zone_risk; a confirmed report must move it
    to CRITICAL, matching the WARNING that went out."""
    from sqlalchemy import text
    from app.deps import Principal
    from app.services import escalation
    pin_score(90)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0, zone_code="AR-03")
    escalation.tick(tx_db, now=t0)
    escalation.confirm(tx_db, r, Principal(1, "authority", "authority"))
    row = tx_db.execute(text("SELECT severity::text AS s, risk_score, contributing_factors FROM zone_risk "
                             "WHERE zone_id = :z ORDER BY computed_at DESC, id DESC LIMIT 1"), {"z": r.zone_id}).mappings().first()
    assert row["s"] == "CRITICAL" and row["risk_score"] >= 75


def test_two_person_rule_for_a_public_warning(tx_db, pin_score, no_siren):
    """CONFIRM needs a prepare step; the same officer then waits 30 s, a second officer does not."""
    from datetime import timedelta
    from app.deps import Principal
    from app.services import escalation
    pin_score(40)
    r = _report(tx_db, datetime.now(timezone.utc))
    a, b = Principal(1, "authority", "authority"), Principal(2, "other.officer", "authority")
    assert "Prepare the confirmation first" in escalation.release_check(tx_db, r, a)
    reach = escalation.prepare_confirm(tx_db, r, a)
    assert reach["zone_name"] and reach["release_after_s"] == 30
    assert "second officer" in escalation.release_check(tx_db, r, a)          # same officer, at once
    assert escalation.release_check(tx_db, r, b) is None                       # second officer, at once
    later = datetime.now(timezone.utc) + timedelta(seconds=31)
    assert escalation.release_check(tx_db, r, a, now=later) is None            # same officer, after 30 s


def test_sos_stays_on_top_and_needs_a_note_to_close(tx_db, pin_score, no_siren):
    import pytest
    from fastapi import HTTPException
    from app.routers.reports import _sos_needs_note, escalations
    pin_score(5)
    r = _report(tx_db, datetime.now(timezone.utc))
    r.issue_type = "sos"
    tx_db.flush()
    assert escalations(include_checking=True, db=tx_db)[0]["id"] == r.id, "SOS first even with the lowest score"
    with pytest.raises(HTTPException) as e:
        _sos_needs_note(r, "  ")
    assert e.value.status_code == 422
    _sos_needs_note(r, "Family reached by phone, safe")
