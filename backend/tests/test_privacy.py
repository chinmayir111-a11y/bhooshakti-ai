"""Reporter numbers: masked in the API, hashed and media deleted after 90 days
(unless the report was confirmed)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.privacy import hashed, mask, purge

from .conftest import requires_db


def test_numbers_are_masked_to_the_last_four_digits():
    assert mask("+91 98765 43210") == "•••• 3210"
    assert mask("") == "" and mask(hashed("+919876543210")) == "(removed after 90 days)"


def test_hash_is_stable_and_not_the_number():
    h = hashed("+919876543210")
    assert h == hashed("+919876543210") and "9876" not in h and h.startswith("h:")


@requires_db
def test_purge_after_ninety_days_keeps_confirmed_evidence(tx_db, tmp_path, monkeypatch):
    from app.models import CitizenReport, ReportStatus
    from app.services import privacy
    monkeypatch.setattr(privacy, "uploads_dir", lambda: tmp_path)
    (tmp_path / "a.jpg").write_bytes(b"x"); (tmp_path / "b.jpg").write_bytes(b"x")
    old = datetime.now(timezone.utc) - timedelta(days=91)
    mk = lambda status, photo: CitizenReport(issue_type="crack", lat=26.9, lon=88.3, geom="SRID=4326;POINT(88.3 26.9)",
                                             phone="+919000000001", status=status, photo_path=photo, created_at=old)
    dismissed, confirmed = mk(ReportStatus.REJECTED, "/uploads/a.jpg"), mk(ReportStatus.APPROVED, "/uploads/b.jpg")
    tx_db.add_all([dismissed, confirmed]); tx_db.flush()
    purge(tx_db)
    assert dismissed.phone.startswith("h:") and confirmed.phone.startswith("h:")
    assert dismissed.photo_path == "" and not (tmp_path / "a.jpg").exists()
    assert confirmed.photo_path == "/uploads/b.jpg" and (tmp_path / "b.jpg").exists()
