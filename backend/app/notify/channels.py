"""Channel adapters: console, websocket, email, sms, push.

Real adapters sit behind the same interface as the stubs, so switching from a
demo to a live deployment is an .env change, never a code change.

  email — genuinely sends over SMTP when SMTP_HOST is set. With no host it
          reports SIMULATED and logs the rendered message.
  sms   — real Twilio and MSG91 adapters (plain REST, no vendor SDK). Defaults
          to the stub so the demo needs no paid account.
  push  — real Expo push adapter; stub when no device token is registered.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import httpx

from ..config import settings
from . import templates
from .base import AlertPayload, DeliveryResult

log = logging.getLogger("bhooshakti.notify")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# console
# ---------------------------------------------------------------------------


class ConsoleChannel:
    name = "console"

    def send(self, payload: AlertPayload) -> list[DeliveryResult]:
        bar = "=" * 74
        log.warning(
            "\n%s\n[ALERT] %s  |  score %.0f/100  |  confidence %.0f%%\n%s\n%s\n%s",
            bar, templates.subject(payload), payload.risk_score,
            payload.confidence * 100, bar,
            "\n".join(f"  - {line}" for line in payload.factor_lines) or "  (no factors)",
            bar,
        )
        return [DeliveryResult(self.name, "stdout", "SENT", "printed to server log", _now())]


# ---------------------------------------------------------------------------
# websocket
# ---------------------------------------------------------------------------


class WebsocketChannel:
    """Pushes to every connected dashboard. Fan-out itself happens in ws.py;
    this records the delivery so /alerts can show the channel."""

    name = "websocket"

    def send(self, payload: AlertPayload) -> list[DeliveryResult]:
        from ..ws import manager
        n = manager.client_count
        return [DeliveryResult(
            self.name, f"{n} dashboard client(s)", "SENT" if n else "SIMULATED",
            "pushed over /ws/live" if n else "no dashboard connected — queued in replay buffer",
            _now(),
        )]


# ---------------------------------------------------------------------------
# email  (REAL SMTP)
# ---------------------------------------------------------------------------


class EmailChannel:
    name = "email"

    def __init__(self, recipients: list[str] | None = None) -> None:
        self.recipients = recipients or [settings.alert_test_email]

    def send(self, payload: AlertPayload) -> list[DeliveryResult]:
        results: list[DeliveryResult] = []
        for to_addr in self.recipients:
            if not to_addr:
                continue
            if not settings.email_configured:
                log.warning(
                    "[email:SIMULATED] SMTP_HOST is unset — would have sent to %s:\n%s",
                    to_addr, templates.plain_text(payload),
                )
                results.append(DeliveryResult(
                    self.name, to_addr, "SIMULATED",
                    "SMTP_HOST not configured — set it in .env to send for real", _now(),
                ))
                continue
            results.append(self._send_one(payload, to_addr))
        return results

    def _send_one(self, payload: AlertPayload, to_addr: str) -> DeliveryResult:
        msg = EmailMessage()
        name, addr = parseaddr(settings.smtp_from)
        msg["From"] = formataddr((name or "BHOOSHAKTI AI", addr or settings.smtp_user))
        msg["To"] = to_addr
        msg["Subject"] = f"[BHOOSHAKTI AI · DEMO] {templates.subject(payload)}"
        msg["X-Bhooshakti-Severity"] = payload.severity
        msg["X-Bhooshakti-Data"] = "SIMULATED"
        msg.set_content(templates.plain_text(payload))
        msg.add_alternative(templates.html_body(payload), subtype="html")

        try:
            if settings.smtp_port == 465:
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                      context=ctx, timeout=25) as s:
                    if settings.smtp_user:
                        s.login(settings.smtp_user, settings.smtp_password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=25) as s:
                    s.ehlo()
                    if settings.smtp_starttls:
                        s.starttls(context=ssl.create_default_context())
                        s.ehlo()
                    if settings.smtp_user:
                        s.login(settings.smtp_user, settings.smtp_password)
                    s.send_message(msg)
        except Exception as exc:
            log.error("[email:FAILED] %s -> %s", to_addr, exc)
            return DeliveryResult(self.name, to_addr, "FAILED", f"{type(exc).__name__}: {exc}", _now())

        log.info("[email:SENT] %s via %s:%s", to_addr, settings.smtp_host, settings.smtp_port)
        return DeliveryResult(
            self.name, to_addr, "SENT",
            f"accepted by {settings.smtp_host}:{settings.smtp_port}", _now(),
        )


# ---------------------------------------------------------------------------
# sms
# ---------------------------------------------------------------------------


class SmsChannel:
    name = "sms"

    def __init__(self, recipients: list[str] | None = None) -> None:
        self.recipients = recipients or [settings.alert_test_phone]

    def send(self, payload: AlertPayload) -> list[DeliveryResult]:
        body = templates.sms_text(payload)
        provider = settings.sms_provider.lower().strip()
        out: list[DeliveryResult] = []
        for number in self.recipients:
            if not number:
                continue
            if provider == "twilio" and settings.twilio_account_sid:
                out.append(self._twilio(number, body))
            elif provider == "msg91" and settings.msg91_auth_key:
                out.append(self._msg91(number, body))
            else:
                log.warning("[sms:SIMULATED] -> %s : %s", number, body)
                out.append(DeliveryResult(
                    self.name, number, "SIMULATED",
                    f"stub gateway (SMS_PROVIDER={provider or 'stub'}) — message logged, not sent",
                    _now(),
                ))
        return out

    def _twilio(self, number: str, body: str) -> DeliveryResult:
        url = (f"https://api.twilio.com/2010-04-01/Accounts/"
               f"{settings.twilio_account_sid}/Messages.json")
        try:
            r = httpx.post(
                url,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                data={"To": number, "From": settings.twilio_from_number, "Body": body},
                timeout=20,
            )
            r.raise_for_status()
            return DeliveryResult(self.name, number, "SENT",
                                  f"twilio sid={r.json().get('sid', '')}", _now())
        except Exception as exc:
            return DeliveryResult(self.name, number, "FAILED", f"twilio: {exc}", _now())

    def _msg91(self, number: str, body: str) -> DeliveryResult:
        try:
            r = httpx.post(
                "https://api.msg91.com/api/v2/sendsms",
                headers={"authkey": settings.msg91_auth_key,
                         "Content-Type": "application/json"},
                json={"sender": settings.msg91_sender_id, "route": "4", "country": "91",
                      "sms": [{"message": body, "to": [number.lstrip("+")]}]},
                timeout=20,
            )
            r.raise_for_status()
            return DeliveryResult(self.name, number, "SENT", "msg91 accepted", _now())
        except Exception as exc:
            return DeliveryResult(self.name, number, "FAILED", f"msg91: {exc}", _now())


# ---------------------------------------------------------------------------
# push  (Expo)
# ---------------------------------------------------------------------------


class PushChannel:
    name = "push"

    def __init__(self, tokens: list[str] | None = None) -> None:
        self.tokens = [t for t in (tokens or []) if t]

    def send(self, payload: AlertPayload) -> list[DeliveryResult]:
        title = f"{payload.severity} — {payload.zone_name}"
        body = (f"Risk {payload.risk_score:.0f}/100 · confidence "
                f"{payload.confidence * 100:.0f}%. "
                f"{payload.factor_lines[0] if payload.factor_lines else ''}")[:170]

        if not self.tokens or settings.push_provider.lower() != "expo":
            log.warning("[push:SIMULATED] %s | %s", title, body)
            return [DeliveryResult(
                self.name, "no registered device", "SIMULATED",
                "no Expo push token registered — field app not paired", _now(),
            )]

        messages = [{
            "to": t, "title": title, "body": body, "sound": "default",
            "priority": "high",
            "data": {"zone_id": payload.zone_id, "alert_id": payload.alert_id,
                     "severity": payload.severity, "deep_link": payload.deep_link},
        } for t in self.tokens]

        headers = {"Content-Type": "application/json"}
        if settings.expo_access_token:
            headers["Authorization"] = f"Bearer {settings.expo_access_token}"
        try:
            r = httpx.post("https://exp.host/--/api/v2/push/send",
                           json=messages, headers=headers, timeout=20)
            r.raise_for_status()
            return [DeliveryResult(self.name, t, "SENT", "expo accepted", _now())
                    for t in self.tokens]
        except Exception as exc:
            return [DeliveryResult(self.name, t, "FAILED", f"expo: {exc}", _now())
                    for t in self.tokens]
