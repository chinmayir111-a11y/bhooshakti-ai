"""One path for every alert the system issues, whatever raised it.

    model risk crossing HIGH       -> ADVISORY       (machine, unconfirmed)
    model risk crossing CRITICAL   -> WARNING
    corroborated citizen report    -> ADVISORY       (app/services/escalation.py)
    moderator CONFIRM              -> WARNING        (upgrade of the advisory)
    moderator DISMISS              -> all-clear follow-up to the same people

Public recipients are the zone's subscribers, grouped by language so each
person hears or reads the message in the language they registered with.
Officials always receive the English version. Every WARNING is also published
on MQTT `bhooshakti/siren/<zone_id>` for a panchayat siren relay.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert, AlertTier, Severity, Zone
from ..notify import AlertPayload, Recipients, dispatch, officials, templates
from ..ws import EVENT_ALERT_DELIVERY, EVENT_ALERT_NEW, manager
from . import spatial

log = logging.getLogger("bhooshakti.alerting")

PUBLIC_CHANNELS = ["sms", "voice"]


def tier_for_model(severity: Severity) -> str:
    """Model output alone never claims more than the evidence: HIGH is an
    advisory, only CRITICAL is a warning."""
    return AlertTier.WARNING.value if severity is Severity.CRITICAL else AlertTier.ADVISORY.value


def public_groups(db: Session, zone_id: int) -> dict[str, Recipients]:
    groups: dict[str, Recipients] = {}
    for sub in spatial.zone_subscribers(db, zone_id):
        lang = sub["language"] or "en"
        g = groups.setdefault(lang, Recipients())
        g.phones.append(sub["phone"])
        g.voice.append(sub["phone"])
    return groups


def sound_siren(zone: Zone, alert: Alert) -> bool:
    from ..mqtt_client import ingest
    ok = ingest.publish(f"{settings.mqtt_siren_prefix}/{zone.id}", {
        "zone_id": zone.id, "zone_code": zone.code, "alert_id": alert.id,
        "tier": alert.tier, "severity": alert.severity.value,
        "action": "sound", "duration_s": 120,
        "issued_at": datetime.now(timezone.utc).isoformat(), "demo_data": True,
    })
    log.info("siren %s for zone %s (alert %s)", "published" if ok else "NOT published (broker down)",
             zone.code, alert.id)
    return ok


def issue(db: Session, *, zone: Zone, tier: str, severity: Severity, risk_score: float,
          confidence: float, factors: list[dict], source: str, kind: str = "risk",
          place: str = "", report_id: int | None = None, parent_alert_id: int | None = None,
          score_breakdown: dict | None = None, include_public: bool = True,
          explicit: dict[str, Recipients] | None = None, language: str = "en") -> Alert:
    """Create, dispatch and broadcast one alert. Commits."""
    roads = spatial.roads_intersecting_zone(db, zone.id)
    villages = spatial.villages_in_zone(db, zone.id)

    def payload_for(lang: str) -> AlertPayload:
        p = AlertPayload(
            alert_id=None, zone_id=zone.id, zone_code=zone.code, zone_name=zone.name,
            district=zone.district, state=zone.state, severity=severity.value,
            risk_score=risk_score, confidence=confidence, contributing_factors=factors,
            language=lang, deep_link=f"{settings.public_dashboard_url}/control?zone={zone.id}",
            affected_roads=[r["name"] for r in roads[:4]],
            affected_villages=[v["name"] for v in villages[:6]],
            source=source, tier=tier, kind=kind, place=place,
        )
        p.title = templates.subject(p)
        p.message = templates.plain_text(p)
        return p

    head = payload_for(language)
    alert = Alert(
        zone_id=zone.id, zone_name=zone.name, severity=severity, risk_score=risk_score,
        confidence=confidence, title=head.title, message=head.message,
        contributing_factors=factors, language=language, source=source, tier=tier,
        report_id=report_id, parent_alert_id=parent_alert_id,
        score_breakdown=score_breakdown or {},
        status="ACTIVE",
    )
    db.add(alert)
    db.flush()

    # Officials (and the demo inbox) on every configured channel, in English.
    if explicit is not None:
        groups = explicit
    else:
        groups = public_groups(db, zone.id) if include_public else {}
    results = dispatch(db, alert, head, recipients=officials(db).merged(groups.pop(language, Recipients())))
    for lang, rec in groups.items():
        results += dispatch(db, alert, payload_for(lang), channels=PUBLIC_CHANNELS, recipients=rec)

    siren = None
    if tier == AlertTier.WARNING.value and kind != "all_clear":
        siren = sound_siren(zone, alert)
    db.commit()

    manager.publish_threadsafe(EVENT_ALERT_NEW, {
        "id": alert.id, "zone_id": zone.id, "zone_code": zone.code, "zone_name": zone.name,
        "district": zone.district, "state": zone.state, "severity": severity.value,
        "tier": tier, "kind": kind, "status": alert.status, "risk_score": risk_score,
        "confidence": confidence, "contributing_factors": factors, "title": head.title,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "affected_roads": head.affected_roads, "affected_villages": head.affected_villages,
        "source": source, "report_id": report_id, "siren": siren, "demo_data": True,
    })
    manager.publish_threadsafe(EVENT_ALERT_DELIVERY, {
        "alert_id": alert.id,
        "deliveries": [{"channel": r.channel, "recipient": r.recipient,
                        "status": r.status, "detail": r.detail} for r in results],
    })
    label = "ALL CLEAR" if kind == "all_clear" else tier
    manager.activity(f"{label} issued — {place or zone.name}", kind=tier.lower(),
                     zone_id=zone.id, alert_id=alert.id, severity=severity.value)
    return alert


def recipients_of(alert: Alert) -> dict[str, Recipients]:
    """Exactly who received `alert`, grouped by language — so an all-clear
    reaches the same people the advisory did, and nobody else."""
    groups: dict[str, Recipients] = {}
    for d in alert.deliveries:
        if d.status.value == "FAILED" or not d.recipient:
            continue
        g = groups.setdefault(d.language or "en", Recipients())
        if d.channel == "email":
            g.emails.append(d.recipient)
        elif d.channel == "sms":
            g.phones.append(d.recipient)
        elif d.channel == "voice" and d.recipient.startswith("+"):
            g.voice.append(d.recipient)
    for g in groups.values():
        g.emails, g.phones, g.voice = (list(dict.fromkeys(x)) for x in (g.emails, g.phones, g.voice))
    return groups


def serialise(alert: Alert, zone: Zone | None = None) -> dict[str, Any]:
    return {
        "id": alert.id, "tier": alert.tier, "status": alert.status,
        "severity": alert.severity.value, "title": alert.title,
        "zone_id": alert.zone_id, "zone_name": alert.zone_name,
        "report_id": alert.report_id, "parent_alert_id": alert.parent_alert_id,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }
