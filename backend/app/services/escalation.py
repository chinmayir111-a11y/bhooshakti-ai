"""Citizen reports must never sit unseen.

Every new report is scored (app/services/corroboration.py) and enters a
ladder that only a human acknowledgement stops:

    T+0                 on-duty moderator(s) for the district: websocket + SMS + email
    T+10 min            unacknowledged -> the next officer in escalation_contacts
    T+20, 30 ... min    ... and the next, until the list runs out
    T+20 min, score>=60 unacknowledged -> automatic ADVISORY to everyone
                        registered in the zone
    score >= 85         ADVISORY immediately, at any time, still awaiting a human

An ADVISORY is machine-issued and worded as unverified. Only a moderator's
CONFIRM produces a WARNING; DISMISS sends an all-clear to exactly the people
the advisory reached.

`tick(db, now)` is deterministic in `now`, which is how the tests freeze time.
A background thread (EscalationScheduler) calls it every ESCALATION_INTERVAL_S,
the same pattern as the MQTT roll-up flusher.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import session_scope
from ..deps import Principal, audit
from ..models import (
    Alert,
    AlertTier,
    CitizenReport,
    EscalationContact,
    ReportStatus,
    Role,
    Severity,
    User,
    Zone,
)
from ..notify import AlertPayload, DeliveryResult, Recipients, build_channels
from ..ws import EVENT_ALERT_UPDATE, EVENT_REPORT_ESCALATION, manager
from . import alerting, corroboration, spatial

log = logging.getLogger("bhooshakti.escalation")

SYSTEM = Principal(user_id=None, username="system:escalation", role="system")
MODERATOR_CHANNELS = ["websocket", "sms", "email"]


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _zone(db: Session, report: CitizenReport) -> Zone | None:
    return db.get(Zone, report.zone_id) if report.zone_id else None


def _district(db: Session, report: CitizenReport) -> str:
    z = _zone(db, report)
    if z:
        return z.district
    # Outside every zone: use the nearest zone's district so somebody owns it.
    row = db.execute(text("""
        SELECT district FROM zones
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) LIMIT 1
    """), {"lat": report.lat, "lon": report.lon}).scalar()
    return row or ""


def contacts_at(db: Session, district: str, level: int) -> list[dict[str, str]]:
    rows = db.query(EscalationContact).filter(
        EscalationContact.district == district,
        EscalationContact.level == level,
        EscalationContact.on_duty.is_(True),
    ).order_by(EscalationContact.id).all()
    out = [{"name": c.name, "designation": c.designation, "phone": c.phone, "email": c.email}
           for c in rows]
    if not out and level == 0:
        # No roster for this district: every authority account is on duty.
        out = [{"name": u.full_name or u.username, "designation": u.designation,
                "phone": u.phone, "email": u.email}
               for u in db.query(User).filter(User.role == Role.AUTHORITY).all()]
    return out


def has_level(db: Session, district: str, level: int) -> bool:
    return bool(contacts_at(db, district, level))


# ---------------------------------------------------------------------------
# Serialisation for the escalation panel
# ---------------------------------------------------------------------------


def schedule(db: Session, report: CitizenReport, now: datetime | None = None) -> dict[str, Any]:
    """What happens next, and when — drives the dashboard countdowns."""
    now = now or datetime.now(timezone.utc)
    created = _utc(report.created_at) or now
    open_ = report.acknowledged_at is None and report.status == ReportStatus.PENDING
    step = timedelta(minutes=settings.escalation_step_minutes)

    next_step_at = next_step_label = None
    if open_ and report.escalation_level >= 1:
        district = _district(db, report)
        if has_level(db, district, report.escalation_level):
            next_step_at = created + step * report.escalation_level
            names = ", ".join(c["name"] for c in contacts_at(db, district, report.escalation_level))
            next_step_label = f"Escalate to {names}"

    advisory_at = None
    if open_ and report.advisory_alert_id is None and report.zone_id:
        if report.corroboration_score >= settings.advisory_immediate_score:
            advisory_at = now
        elif report.corroboration_score >= settings.advisory_min_score:
            advisory_at = created + timedelta(minutes=settings.escalation_advisory_minutes)

    return {
        "open": open_,
        "level": report.escalation_level,
        "next_step_at": next_step_at.isoformat() if next_step_at else None,
        "next_step_label": next_step_label,
        "advisory_at": advisory_at.isoformat() if advisory_at else None,
        "advisory_alert_id": report.advisory_alert_id,
        "warning_alert_id": report.warning_alert_id,
        "acknowledged_at": report.acknowledged_at.isoformat() if report.acknowledged_at else None,
        "acknowledged_by": report.acknowledged_by,
    }


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def notify_moderators(db: Session, report: CitizenReport, level: int,
                      now: datetime) -> list[dict[str, Any]]:
    district = _district(db, report)
    people = contacts_at(db, district, level)
    place = spatial.nearest_place(db, report.lat, report.lon)
    zone = _zone(db, report)

    rec = Recipients(emails=[p["email"] for p in people if p["email"]],
                     phones=[p["phone"] for p in people if p["phone"]])
    # The demo inbox sees every escalation, as it does every alert.
    if settings.alert_test_email and settings.alert_test_email not in rec.emails:
        rec.emails.append(settings.alert_test_email)

    step = "on-duty moderator" if level == 0 else f"escalation level {level}"
    title = (f"REVIEW NEEDED — citizen report #{report.id} near {place} "
             f"(corroboration {report.corroboration_score:.0f}/100, {step})")
    reasons = report.corroboration_reasons or []
    payload = AlertPayload(
        alert_id=None, zone_id=zone.id if zone else 0, zone_code=zone.code if zone else "",
        zone_name=zone.name if zone else place, district=district,
        state=zone.state if zone else "", severity="MODERATE",
        risk_score=report.corroboration_score, confidence=report.corroboration_score / 100.0,
        contributing_factors=[{"text": f"{r['text']} ({r['points']:+d})", "weight": 0,
                               "direction": "increases"} for r in reasons],
        title=title, kind="moderator", place=place, tier="ADVISORY",
        deep_link=f"{settings.public_dashboard_url}/control/moderation?report={report.id}",
    )
    results = []
    for ch in build_channels(db, MODERATOR_CHANNELS, rec):
        try:
            results += ch.send(payload)
        except Exception as exc:          # one broken channel never blocks the rest
            log.exception("moderator notify via %s failed", ch.name)
            results.append(DeliveryResult(ch.name, "", "FAILED", f"{type(exc).__name__}: {exc}", now))
    deliveries = [{"channel": r.channel, "recipient": r.recipient, "status": r.status,
                   "detail": r.detail} for r in results]

    report.escalation_level = level + 1
    report.last_escalated_at = now
    audit(db, SYSTEM, "escalate" if level else "notify_moderator", "citizen_report", report.id,
          detail={"level": level, "district": district, "contacts": [p["name"] for p in people],
                  "score": report.corroboration_score, "reasons": reasons,
                  "deliveries": deliveries}, commit=False)
    manager.publish_threadsafe(EVENT_REPORT_ESCALATION, {
        "report_id": report.id, "level": level, "contacts": [p["name"] for p in people],
        "district": district, "score": report.corroboration_score, "title": title,
        "deliveries": deliveries, "schedule": schedule(db, report, now),
    })
    if level:
        manager.activity(f"Report #{report.id} near {place} unacknowledged — escalated to "
                         f"{', '.join(p['name'] for p in people) or 'next officer'}",
                         kind="escalation", report_id=report.id)
    return deliveries


def issue_advisory(db: Session, report: CitizenReport, reason: str, now: datetime) -> Alert | None:
    zone = _zone(db, report)
    if zone is None:
        log.info("report %s is outside every zone — no zone to advise", report.id)
        return None
    place = spatial.nearest_place(db, report.lat, report.lon)
    current = db.execute(text("""
        SELECT risk_score, severity::text AS severity, confidence FROM zone_risk
        WHERE zone_id = :z ORDER BY computed_at DESC, id DESC LIMIT 1
    """), {"z": zone.id}).mappings().first()
    sev = Severity(current["severity"]) if current else Severity.MODERATE
    if sev in (Severity.LOW,):
        sev = Severity.MODERATE
    breakdown = {"corroboration_score": report.corroboration_score,
                 "reasons": report.corroboration_reasons, "trigger": reason,
                 "report_id": report.id}

    alert = alerting.issue(
        db, zone=zone, tier=AlertTier.ADVISORY.value, severity=sev,
        risk_score=float(current["risk_score"]) if current else report.corroboration_score,
        confidence=float(current["confidence"]) if current else report.corroboration_score / 100.0,
        factors=[{"key": r["key"], "text": r["text"], "weight": max(r["points"], 0) / 100.0,
                  "direction": "increases" if r["points"] > 0 else "reduces"}
                 for r in report.corroboration_reasons or []],
        source="auto-advisory", kind="advisory", place=place, report_id=report.id,
        score_breakdown=breakdown,
    )
    report.advisory_alert_id = alert.id
    audit(db, SYSTEM, "auto_advisory", "citizen_report", report.id,
          detail={**breakdown, "alert_id": alert.id, "zone": zone.code, "place": place,
                  "channels": sorted({d.channel for d in alert.deliveries})}, commit=False)
    db.commit()
    return alert


def on_new_report(db: Session, report: CitizenReport, now: datetime | None = None) -> dict[str, Any]:
    """Score, notify the on-duty moderator (T+0), and advise at once if the
    evidence is already overwhelming. Re-scores neighbours whose cluster this
    report may have just completed."""
    now = now or datetime.now(timezone.utc)
    score, reasons = corroboration.score_report(db, report, now)
    audit(db, SYSTEM, "corroboration_score", "citizen_report", report.id,
          detail={"score": score, "reasons": reasons}, commit=False)
    notify_moderators(db, report, 0, now)
    db.commit()

    advisory = None
    if (settings.escalation_enabled and score >= settings.advisory_immediate_score
            and report.advisory_alert_id is None):
        advisory = issue_advisory(db, report, f"score {score:.0f} >= {settings.advisory_immediate_score:.0f}", now)

    _rescore_neighbours(db, report, now)
    return {"score": score, "reasons": reasons,
            "advisory_alert_id": advisory.id if advisory else None}


def _rescore_neighbours(db: Session, report: CitizenReport, now: datetime) -> None:
    ids = [r[0] for r in db.execute(text("""
        SELECT id FROM citizen_reports
        WHERE id <> :id AND status = 'PENDING' AND acknowledged_at IS NULL
          AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r)
          AND created_at > :since
    """), {"id": report.id, "lat": report.lat, "lon": report.lon,
           "r": corroboration.CLUSTER_RADIUS_M,
           "since": now - timedelta(minutes=corroboration.CLUSTER_WINDOW_MIN)})]
    for rid in ids:
        other = db.get(CitizenReport, rid)
        old = other.corroboration_score
        corroboration.score_report(db, other, now)
        if other.corroboration_score != old:
            audit(db, SYSTEM, "corroboration_rescore", "citizen_report", rid,
                  detail={"from": old, "to": other.corroboration_score,
                          "reasons": other.corroboration_reasons,
                          "because_of_report": report.id}, commit=False)
    db.commit()


def tick(db: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    """One pass of the ladder over every open report. Returns what it did."""
    now = now or datetime.now(timezone.utc)
    step_min = settings.escalation_step_minutes
    actions: list[dict[str, Any]] = []

    open_reports = db.query(CitizenReport).filter(
        CitizenReport.status == ReportStatus.PENDING,
        CitizenReport.acknowledged_at.is_(None),
        CitizenReport.created_at > now - timedelta(hours=24),
    ).order_by(CitizenReport.id).with_for_update(skip_locked=True).all()

    for r in open_reports:
        created = _utc(r.created_at) or now
        age_min = (now - created).total_seconds() / 60.0

        old = r.corroboration_score
        corroboration.score_report(db, r, now)
        if r.corroboration_score != old:
            audit(db, SYSTEM, "corroboration_rescore", "citizen_report", r.id,
                  detail={"from": old, "to": r.corroboration_score,
                          "reasons": r.corroboration_reasons}, commit=False)

        if r.escalation_level == 0:
            notify_moderators(db, r, 0, now)
            actions.append({"report_id": r.id, "action": "notify_moderator", "level": 0})

        district = _district(db, r)
        while (r.escalation_level >= 1 and age_min >= step_min * r.escalation_level
               and has_level(db, district, r.escalation_level)):
            level = r.escalation_level
            notify_moderators(db, r, level, now)
            actions.append({"report_id": r.id, "action": "escalate", "level": level})

        if settings.escalation_enabled and r.advisory_alert_id is None and r.zone_id:
            immediate = r.corroboration_score >= settings.advisory_immediate_score
            timed = (age_min >= settings.escalation_advisory_minutes
                     and r.corroboration_score >= settings.advisory_min_score)
            if immediate or timed:
                why = (f"score {r.corroboration_score:.0f} >= {settings.advisory_immediate_score:.0f}"
                       if immediate else
                       f"unacknowledged for {age_min:.0f} min with score "
                       f"{r.corroboration_score:.0f} >= {settings.advisory_min_score:.0f}")
                alert = issue_advisory(db, r, why, now)
                if alert:
                    actions.append({"report_id": r.id, "action": "advisory", "alert_id": alert.id})
        db.commit()
    return actions


# ---------------------------------------------------------------------------
# Human decisions
# ---------------------------------------------------------------------------


def acknowledge(db: Session, report: CitizenReport, principal: Principal) -> None:
    if report.acknowledged_at is None:
        report.acknowledged_at = datetime.now(timezone.utc)
        report.acknowledged_by = principal.username


def confirm(db: Session, report: CitizenReport, principal: Principal, notes: str = "") -> Alert | None:
    """CONFIRM: the report is real. Upgrades the advisory (or issues fresh) to
    a WARNING for the zone, which also sounds the siren."""
    acknowledge(db, report, principal)
    report.status = ReportStatus.APPROVED
    report.moderated_by = principal.username
    report.moderated_at = datetime.now(timezone.utc)
    report.moderation_notes = notes.strip()[:2000]

    zone = _zone(db, report)
    if zone is None:
        db.commit()
        return None
    place = spatial.nearest_place(db, report.lat, report.lon)
    advisory = db.get(Alert, report.advisory_alert_id) if report.advisory_alert_id else None
    current = db.execute(text("""
        SELECT risk_score, confidence FROM zone_risk WHERE zone_id = :z
        ORDER BY computed_at DESC, id DESC LIMIT 1
    """), {"z": zone.id}).mappings().first()

    warning = alerting.issue(
        db, zone=zone, tier=AlertTier.WARNING.value, severity=Severity.CRITICAL,
        risk_score=float(current["risk_score"]) if current else 100.0,
        confidence=0.95, factors=[{"key": "human_confirmed", "weight": 1.0, "direction": "increases",
                                   "text": f"Confirmed on review by {principal.username}"}],
        source="moderator-confirmed", kind="confirmed", place=place, report_id=report.id,
        parent_alert_id=advisory.id if advisory else None,
        score_breakdown={"corroboration_score": report.corroboration_score,
                         "reasons": report.corroboration_reasons, "confirmed_by": principal.username},
        explicit=alerting.recipients_of(advisory) if advisory else None,
    )
    if advisory:
        advisory.status = "CONFIRMED"
        advisory.acknowledged = True
    report.warning_alert_id = warning.id
    audit(db, principal, "confirm", "citizen_report", report.id,
          detail={"warning_alert_id": warning.id, "advisory_alert_id": report.advisory_alert_id},
          commit=False)
    db.commit()
    manager.publish_threadsafe(EVENT_ALERT_UPDATE, {"alert_id": advisory.id, "status": "CONFIRMED",
                                                    "superseded_by": warning.id} if advisory else
                               {"alert_id": warning.id, "status": "ACTIVE"})
    return warning


def dismiss(db: Session, report: CitizenReport, principal: Principal, notes: str = "") -> Alert | None:
    """DISMISS: a false report. If an advisory went out, the same recipients
    get an all-clear so nobody is left avoiding a road for nothing."""
    acknowledge(db, report, principal)
    report.status = ReportStatus.REJECTED
    report.moderated_by = principal.username
    report.moderated_at = datetime.now(timezone.utc)
    report.moderation_notes = notes.strip()[:2000]

    follow_up = None
    advisory = db.get(Alert, report.advisory_alert_id) if report.advisory_alert_id else None
    zone = _zone(db, report)
    if advisory and zone:
        place = spatial.nearest_place(db, report.lat, report.lon)
        follow_up = alerting.issue(
            db, zone=zone, tier=AlertTier.ADVISORY.value, severity=Severity.LOW,
            risk_score=advisory.risk_score, confidence=advisory.confidence,
            factors=[{"key": "dismissed", "weight": 0, "direction": "reduces",
                      "text": f"Checked and dismissed by {principal.username}"}],
            source="all-clear", kind="all_clear", place=place, report_id=report.id,
            parent_alert_id=advisory.id, explicit=alerting.recipients_of(advisory),
        )
        follow_up.status = "DISMISSED"
        advisory.status = "DISMISSED"
        advisory.acknowledged = True
        manager.publish_threadsafe(EVENT_ALERT_UPDATE, {"alert_id": advisory.id, "status": "DISMISSED",
                                                        "all_clear_alert_id": follow_up.id})
    audit(db, principal, "dismiss", "citizen_report", report.id,
          detail={"advisory_alert_id": report.advisory_alert_id,
                  "all_clear_alert_id": follow_up.id if follow_up else None}, commit=False)
    db.commit()
    return follow_up


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------


class EscalationScheduler:
    """Runs `tick` on a daemon thread every ESCALATION_INTERVAL_S seconds."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.ticks = 0
        self.last_error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="escalation", daemon=True)
        self._thread.start()
        log.info("escalation ladder running every %ss", settings.escalation_interval_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _loop(self) -> None:
        while not self._stop.wait(settings.escalation_interval_s):
            try:
                with session_scope() as db:
                    done = tick(db)
                self.ticks += 1
                self.last_error = None
                if done:
                    log.info("escalation tick: %s", done)
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("escalation tick failed")


scheduler = EscalationScheduler()
