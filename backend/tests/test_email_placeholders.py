"""Real SMTP must never be tried for the seeded made-up .local addresses."""
from app.config import settings
from app.notify import channels
from app.notify.channels import EmailChannel


def test_local_addresses_are_skipped_even_with_smtp(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_user", "u")
    monkeypatch.setattr(settings, "smtp_password", "p")
    sent = []
    monkeypatch.setattr(EmailChannel, "_send_one", lambda self, payload, to: sent.append(to) or
                        channels.DeliveryResult("email", to, "SENT", "", channels._now()))
    out = EmailChannel(["l0.darjeeling@bhooshakti.local", "real@example.com"]).send(None)
    assert sent == ["real@example.com"]
    assert [r.status for r in out] == ["SIMULATED", "SENT"]
