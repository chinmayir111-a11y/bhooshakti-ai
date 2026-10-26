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


# Voice notes: a 20 s clip from the web recorder (webm/ogg/mp4) or the IVR
# (wav/mp3). Same rules as photos — recognised container or nothing.
MAX_AUDIO_BYTES = 3 * 1024 * 1024
_AUDIO_DATA_URI = re.compile(r"^data:audio/(?P<ext>[a-z0-9.+-]+)(;[^,]*)?;base64,", re.I)
_AUDIO_SIGNATURES = [
    (b"\x1aE\xdf\xa3", "webm"),     # EBML: webm / matroska
    (b"OggS", "ogg"),
    (b"RIFF", "wav"),
    (b"ID3", "mp3"),
    (b"\xff\xfb", "mp3"),
    (b"\xff\xf3", "mp3"),
]


def _audio_ext(raw: bytes) -> str | None:
    for signature, ext in _AUDIO_SIGNATURES:
        if raw.startswith(signature):
            return ext
    if raw[4:8] == b"ftyp":         # mp4 / m4a — what Safari's MediaRecorder emits
        return "m4a"
    return None


def save_audio_bytes(raw: bytes, prefix: str = "voice") -> str:
    if not raw or len(raw) > MAX_AUDIO_BYTES:
        log.warning("discarded a voice note of %d bytes", len(raw or b""))
        return ""
    ext = _audio_ext(raw)
    if ext is None:
        log.warning("discarded a voice payload with no recognised audio signature")
        return ""
    name = f"{prefix}-{uuid.uuid4().hex[:12]}.{ext}"
    (settings.upload_dir / name).write_bytes(raw)
    return f"/uploads/{name}"


def save_audio(payload: str | None, prefix: str = "voice") -> str:
    """Persist a base64 voice note and return its public path, or ''."""
    if not payload:
        return ""
    match = _AUDIO_DATA_URI.match(payload)
    if match:
        payload = payload[match.end():]
    try:
        raw = base64.b64decode(payload.strip(), validate=False)
    except (binascii.Error, ValueError):
        return ""
    return save_audio_bytes(raw, prefix)
