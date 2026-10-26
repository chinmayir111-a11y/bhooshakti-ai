"""Warning signs a villager can see before a slide.

From GSI's community landslide-warning pilot in Darjeeling (Giddapahar,
Kurseong), where residents were trained to watch for exactly these. One list,
used by the citizen app, the SMS parser and the corroboration score.
"""
from __future__ import annotations

# key -> (plain words for the reasons list, SMS keywords that mean it)
SIGNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "crack": ("new cracks in the ground or walls", ("CRACK", "CRACKS")),
    "spring": ("muddy or new springs, or water suddenly stopping", ("SPRING", "SPRINGS")),
    "tilt": ("tilted trees, poles or walls", ("TILT", "TILTED")),
    "sound": ("rumbling or cracking sounds", ("SOUND", "SOUNDS", "RUMBLE")),
    "stones": ("falling stones", ("STONE", "STONES")),
    "sinking": ("the road or ground sinking", ("SINK", "SINKING")),
}
SIGN_KEYS = tuple(SIGNS)
_BY_WORD = {w: k for k, (_, words) in SIGNS.items() for w in words}

POINTS_PER_SIGN = 10
MAX_SIGN_POINTS = 30


def clean(signs: list[str] | None) -> list[str]:
    """Known signs only, each once, in the canonical order."""
    given = set(signs or [])
    return [k for k in SIGN_KEYS if k in given]


def from_words(words: list[str]) -> list[str]:
    """SMS tokens -> signs, e.g. ['CRACK', 'near', 'school', 'SPRING'] -> ['crack', 'spring']."""
    return clean([_BY_WORD[w.upper()] for w in words if w.upper() in _BY_WORD])
