"""Photo handling for citizen and field reports.

Images arrive base64-encoded in JSON so the web form and the Expo app can use
one code path. Files land in backend/uploads and are served read-only at
/uploads. A real deployment writes to object storage instead — see
DEPLOYMENT.md, "Photo storage".
"""
from __future__ import annotations

import base64
import binascii
import logging
import re
import uuid

from ..config import settings

log = logging.getLogger("bhooshakti.media")

MAX_BYTES = 6 * 1024 * 1024   # 6 MB — a phone photo, not a video

_DATA_URI = re.compile(r"^data:(image/(?P<ext>png|jpe?g|webp|heic));base64,", re.I)
_EXT_BY_SIGNATURE = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"RIFF", "webp"),
]


def save_photo(payload: str | None, prefix: str = "report") -> str:
    """Persist a base64 image and return its public path, or '' if there is none."""
    if not payload:
        return ""

    ext = "jpg"
    match = _DATA_URI.match(payload)
    if match:
        ext = (match.group("ext") or "jpg").lower().replace("jpeg", "jpg")
        payload = payload[match.end():]

    payload = payload.strip().replace("\n", "").replace("\r", "")
    try:
        raw = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        log.warning("discarded an unparseable photo payload")
        return ""

    if not raw:
        return ""
    if len(raw) > MAX_BYTES:
        log.warning("discarded a photo of %.1f MB (limit %.0f MB)",
                    len(raw) / 1e6, MAX_BYTES / 1e6)
        return ""

    for signature, sig_ext in _EXT_BY_SIGNATURE:
        if raw.startswith(signature):
            ext = sig_ext
            break
    else:
        # Not a recognised image container — refuse rather than store unknown bytes.
        log.warning("discarded a photo payload with no recognised image signature")
        return ""

    name = f"{prefix}-{uuid.uuid4().hex[:12]}.{ext}"
    (settings.upload_dir / name).write_bytes(raw)
    return f"/uploads/{name}"
