"""Reporter privacy.

  * The API never shows a reporter's full number: `mask` keeps the last four
    digits. An authority can reveal one for a call-back, and that is audited.
  * After RETENTION_DAYS a report's number is replaced by a keyed hash (still
    good for "same sender?" checks, useless for calling), and its photo and
    voice note are deleted — unless the report was CONFIRMED as a real event.
`purge` runs with the 30-minute weather job; `mask` / `hashed` are pure.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..models import CitizenReport, ReportStatus

log = logging.getLogger(__name__)
RETENTION_DAYS = 90
HASH_PREFIX = "h:"


def uploads_dir():
    return settings.upload_dir


def mask(phone: str | None) -> str:
    p = (phone or "").strip()
    if not p:
        return ""
    if p.startswith(HASH_PREFIX):
        return "(removed after 90 days)"
    digits = "".join(c for c in p if c.isdigit())
    return f"•••• {digits[-4:]}" if len(digits) >= 4 else "••••"


def hashed(phone: str) -> str:
    if not phone or phone.startswith(HASH_PREFIX):
        return phone
    mac = hmac.new(settings.jwt_secret.encode(), phone.strip().encode(), hashlib.sha256).hexdigest()
    return HASH_PREFIX + mac[:24]


def purge(db: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RETENTION_DAYS)
    old = db.query(CitizenReport).filter(CitizenReport.created_at < cutoff).all()
    numbers = media = 0
    for r in old:
        if r.phone and not r.phone.startswith(HASH_PREFIX):
            r.phone = hashed(r.phone); numbers += 1
        if r.status != ReportStatus.APPROVED:
            for attr in ("photo_path", "voice_note_path"):
                path = getattr(r, attr)
                if path:
                    f = uploads_dir() / path.rsplit("/", 1)[-1]
                    try:
                        f.unlink(missing_ok=True)
                    except OSError:
                        log.warning("could not delete %s", f)
                    setattr(r, attr, ""); media += 1
    db.commit()
    if numbers or media:
        log.info("privacy purge: %s numbers hashed, %s media files deleted", numbers, media)
    return {"numbers_hashed": numbers, "media_deleted": media}
