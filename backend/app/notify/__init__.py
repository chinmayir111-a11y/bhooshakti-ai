"""Pluggable alert dispatcher.

`dispatch` fans one AlertPayload out across every channel named in
NOTIFY_CHANNELS, records an AlertDelivery row per attempt, and pushes the
result to connected dashboards. A channel that raises never stops the others —
a broken SMS gateway must not swallow the email.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert, AlertDelivery, DeliveryStatus, User
from .base import AlertPayload, DeliveryResult, Recipients
from .channels import (
    ConsoleChannel,
    EmailChannel,
    PushChannel,
    SmsChannel,
    VoiceChannel,
    WebsocketChannel,
)
from . import templates

log = logging.getLogger("bhooshakti.notify")

__all__ = ["AlertPayload", "DeliveryResult", "Recipients", "dispatch", "build_channels",
           "officials", "templates"]


def officials(db: Session | None) -> Recipients:
    """Every authority and field officer, plus the configured test inbox/phone."""
    emails: list[str] = []
    phones: list[str] = []
    tokens: list[str] = []

    if db is not None:
        for u in db.query(User).all():
            if u.role.value in ("authority", "field_officer"):
                if u.email:
                    emails.append(u.email)
                if u.phone:
                    phones.append(u.phone)
                if u.push_token:
                    tokens.append(u.push_token)

    # The configured test inbox always receives alerts — it is what the judge
    # sees during the demo.
    if settings.alert_test_email and settings.alert_test_email not in emails:
        emails.insert(0, settings.alert_test_email)
    if settings.alert_test_phone and settings.alert_test_phone not in phones:
        phones.insert(0, settings.alert_test_phone)
    # Officials get the SMS; a voice call is reserved for the public, who may
    # not be able to read one.
    return Recipients(emails=emails, phones=phones, voice=[], tokens=tokens)


def build_channels(db: Session | None = None,
                   channels: list[str] | None = None,
                   recipients: Recipients | None = None) -> list:
    """Instantiate the configured channels for `recipients` (default: officials)."""
    wanted = [c.lower() for c in (channels or settings.channel_list)]
    r = recipients if recipients is not None else officials(db)

    registry = {
        "console": lambda: ConsoleChannel(),
        "websocket": lambda: WebsocketChannel(),
        "email": lambda: EmailChannel(r.emails) if r.emails else None,
        "sms": lambda: SmsChannel(r.phones) if r.phones else None,
        "push": lambda: PushChannel(r.tokens),
        "voice": lambda: VoiceChannel(r.voice) if r.voice else None,
    }
    built = []
    for name in wanted:
        factory = registry.get(name)
        if factory is None:
            log.warning("unknown notification channel %r — skipped", name)
            continue
        ch = factory()
        if ch is not None:          # a medium with nobody to reach is skipped, not stubbed
            built.append(ch)
    return built


def dispatch(db: Session, alert: Alert, payload: AlertPayload,
             channels: list[str] | None = None,
             recipients: Recipients | None = None) -> list[DeliveryResult]:
    """Send `payload` on every configured channel and persist the outcomes."""
    payload.alert_id = alert.id
    results: list[DeliveryResult] = []

    for channel in build_channels(db, channels, recipients):
        try:
            results.extend(channel.send(payload))
        except Exception as exc:                     # never let one channel kill the rest
            log.exception("channel %s raised", channel.name)
            results.append(DeliveryResult(
                channel.name, "", "FAILED", f"{type(exc).__name__}: {exc}",
                datetime.now(timezone.utc),
            ))

    for r in results:
        db.add(AlertDelivery(
            alert_id=alert.id,
            channel=r.channel,
            recipient=r.recipient,
            language=payload.language,
            status=DeliveryStatus(r.status),
            detail=r.detail,
            sent_at=r.sent_at,
        ))
    db.flush()
    return results
