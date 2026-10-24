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


def _audit(db, report_id: int) -> list[str]:
    return [r[0] for r in db.execute(text(
        "SELECT action FROM audit_log WHERE resource = 'citizen_report' AND resource_id = :i ORDER BY id"
    ), {"i": str(report_id)})]


def test_ladder_climbs_every_ten_minutes_until_acknowledged(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(40)                                  # below every advisory threshold
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)

    acts = escalation.tick(tx_db, now=t0)
    assert acts == [{"report_id": r.id, "action": "notify_moderator", "level": 0}]
    assert r.escalation_level == 1

    assert escalation.tick(tx_db, now=t0 + timedelta(minutes=9, seconds=59)) == []

    acts = escalation.tick(tx_db, now=t0 + timedelta(minutes=10))
    assert acts == [{"report_id": r.id, "action": "escalate", "level": 1}]

    acts = escalation.tick(tx_db, now=t0 + timedelta(minutes=20))
    assert acts == [{"report_id": r.id, "action": "escalate", "level": 2}]
    assert r.advisory_alert_id is None, "score 40 must never auto-advise"

    # Roster has three levels; the ladder stops at the top instead of looping.
    assert escalation.tick(tx_db, now=t0 + timedelta(minutes=45)) == []
    assert _audit(tx_db, r.id).count("escalate") == 2


def test_acknowledged_report_stops_the_clock(tx_db, pin_score, no_siren):
    from app.deps import Principal
    from app.services import escalation
    pin_score(90)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    escalation.acknowledge(tx_db, r, Principal(1, "authority", "authority"))
    tx_db.flush()
    assert escalation.tick(tx_db, now=t0 + timedelta(minutes=30)) == []
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

    acts = escalation.tick(tx_db, now=t0 + timedelta(minutes=20))
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
    escalation.tick(tx_db, now=t0 + timedelta(minutes=60))
    assert r.advisory_alert_id is None


def test_score_85_advises_immediately(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(85)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    acts = escalation.tick(tx_db, now=t0 + timedelta(seconds=30))
    assert [a["action"] for a in acts] == ["notify_moderator", "advisory"]
    assert r.advisory_alert_id is not None


def test_outside_every_zone_escalates_but_cannot_advise(tx_db, pin_score, no_siren):
    from app.services import escalation
    pin_score(95)
    t0 = datetime.now(timezone.utc)
    r = _report(tx_db, t0)
    r.zone_id = None
    tx_db.flush()
    acts = escalation.tick(tx_db, now=t0 + timedelta(minutes=25))
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
