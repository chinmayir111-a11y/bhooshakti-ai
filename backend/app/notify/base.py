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


class Channel(Protocol):
    name: str

    def send(self, payload: AlertPayload) -> list[DeliveryResult]:
        ...
