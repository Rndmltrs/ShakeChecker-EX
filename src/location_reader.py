"""Read the location name from the top-left HUD and decide if it is a cave.

The Dusk Ball is boosted in caves (and at night). The vendored locations_index
covers only some regions (no Sinnoh), so cave-ness is decided by the name: a set
of keywords ("cave", "tunnel", "mine", "gate", ...) plus a few keyword-less caves
matched by their distinctive words (Victory Road, Mt. Coronet, Ice Path), which
tolerates OCR noise like "VictoryF Road". This is a heuristic, not a full
location database — see CLAUDE.md milestone 4 for the data-backed version.
"""

from __future__ import annotations

import re

import cv2
import numpy as np

from battle_reader import LocationCalibration
from ocr_engine import run_ocr

# Drops the " Ch. N" channel suffix (and any trailing noise) from the HUD line.
_CH_SUFFIX = re.compile(r"\s*ch\.?\s*\d+.*$", re.IGNORECASE)

# A location whose name contains any of these is a cave.
_CAVE_KEYWORDS = (
    "cave",
    "cavern",
    "tunnel",
    "mine",
    "gate",
    "grotto",
    "chamber",
    "coronet",  # Mt. Coronet, however "Mt." is OCR'd
)
# Keyword-less caves, matched by ALL their distinctive words (OCR-noise tolerant).
_CAVE_WORD_GROUPS = (
    ("victory", "road"),
    ("ice", "path"),
    ("ravaged", "path"),
    ("stark", "mountain"),
    ("iron", "island"),
)


def clean_location(raw: str) -> str:
    """The location name without the ' Ch. N' channel suffix or stray edges."""
    return _CH_SUFFIX.sub("", raw.strip()).strip(" .|")


def is_cave_location(name: str) -> bool:
    """True if the location name denotes a cave (Dusk Ball boosted)."""
    n = name.lower()
    if any(k in n for k in _CAVE_KEYWORDS):
        return True
    return any(all(word in n for word in group) for group in _CAVE_WORD_GROUPS)


def read_location(frame_bgr: np.ndarray, cal: LocationCalibration) -> str:
    """OCR the top-left HUD location (cleaned), or '' if not readable."""
    h, w = frame_bgr.shape[:2]
    crop = frame_bgr[int(h * cal.top) : int(h * cal.bottom), int(w * cal.left) : int(w * cal.right)]
    if crop.size == 0:
        return ""
    up = cv2.resize(crop, None, fx=cal.upscale, fy=cal.upscale, interpolation=cv2.INTER_CUBIC)
    texts = run_ocr(up)
    return clean_location(" ".join(texts)) if texts else ""
