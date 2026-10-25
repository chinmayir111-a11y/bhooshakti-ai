"""Channel interface shared by every notification adapter."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


@dataclass
class AlertPayload:
    """Everything a channel needs to render an alert, in any language."""

    alert_id: int | None
    zone_id: int
    zone_code: str
    zone_name: str
    district: str
    state: str
    severity: str
    risk_score: float
    confidence: float
    contributing_factors: list[dict] = field(default_factory=list)
    title: str = ""
    message: str = ""
    language: str = "en"
    deep_link: str = ""
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    affected_roads: list[str] = field(default_factory=list)
    affected_villages: list[str] = field(default_factory=list)
    source: str = "auto"
    # ADVISORY (machine, unconfirmed) or WARNING (human-confirmed / model CRITICAL).
    tier: str = "WARNING"
    # risk | advisory | confirmed | all_clear — selects the wording.
    kind: str = "risk"
    place: str = ""          # "near X" for report-driven messages
    shelter: str = ""        # nearest safe place, named in danger SMS / voice / email

    @property
    def factor_lines(self) -> list[str]:
        return [f["text"] for f in self.contributing_factors if f.get("text")]


@dataclass
class DeliveryResult:
    channel: str
    recipient: str
    status: str          # SENT | FAILED | SIMULATED
    detail: str = ""
    sent_at: datetime | None = None


@dataclass
class Recipients:
    """Who a single dispatch goes to, per medium. `None` on dispatch means
    "the officials list" — the original behaviour for risk alerts."""

    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    voice: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)

    def merged(self, other: "Recipients") -> "Recipients":
        def u(a: list[str], b: list[str]) -> list[str]:
            return list(dict.fromkeys([*a, *b]))
        return Recipients(u(self.emails, other.emails), u(self.phones, other.phones),
                          u(self.voice, other.voice), u(self.tokens, other.tokens))


class Channel(Protocol):
    name: str

    def send(self, payload: AlertPayload) -> list[DeliveryResult]:
        ...
