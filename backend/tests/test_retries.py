"""Outgoing messages: a failed recipient is retried with backoff, three tries in all."""
from datetime import datetime, timezone

from app.notify import retry_failed
from app.notify.base import AlertPayload, DeliveryResult


class Flaky:
    name = "sms"

    def __init__(self, fail_times):
        self.recipients, self.count, self.fail_times = ["+911"], [0], fail_times   # list: shared by retry copies

    @property
    def calls(self):
        return self.count[0]

    def send(self, payload):
        self.count[0] += 1
        ok = self.calls > self.fail_times
        return [DeliveryResult("sms", self.recipients[0], "SENT" if ok else "FAILED", "", datetime.now(timezone.utc))]


def _payload():
    return AlertPayload(alert_id=1, zone_id=1, zone_code="Z", zone_name="Z", district="D", state="S",
                        severity="HIGH", risk_score=60, confidence=0.7)


def test_a_failure_is_retried_until_it_goes_through():
    ch = Flaky(fail_times=2)
    first = ch.send(_payload())
    out = retry_failed(ch, _payload(), first, delays=(0, 0))
    assert out[0].status == "SENT" and "after 3 tries" in out[0].detail


def test_three_tries_at_most_then_failed_is_recorded():
    ch = Flaky(fail_times=10)
    out = retry_failed(ch, _payload(), ch.send(_payload()), delays=(0, 0))
    assert out[0].status == "FAILED" and "after 3 tries" in out[0].detail


def test_simulated_and_sent_are_never_retried():
    ch = Flaky(fail_times=0)
    sim = [DeliveryResult("sms", "+911", "SIMULATED", "stub")]
    assert retry_failed(ch, _payload(), sim, delays=(0, 0))[0].detail == "stub" and ch.calls == 0
