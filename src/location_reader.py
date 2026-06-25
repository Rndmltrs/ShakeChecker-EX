"""Read the location name from the top-left HUD and decide if it is a cave."""

from __future__ import annotations

import re
import cv2
import numpy as np

from battle_reader import LocationCalibration
from ocr_engine import run_ocr_no_det

_last_mask = None
_last_location = ""
_last_loc_time = 0.0

OCR_THROTTLE_S = 0.25

_CH_SUFFIX = re.compile(r"\s*c\s*h[\.,\-\s]*\d+.*$", re.IGNORECASE)
_TITLE_PREFIX = re.compile(r"^\s*pokemmo\s*", re.IGNORECASE)

_CAVE_KEYWORDS = (
    "cave",
    "cavern",
    "tunnel",
    "mine",
    "gate",
    "grotto",
    "chamber",
    "coronet",
)

_CAVE_WORD_GROUPS = (
    ("victory", "road"),
    ("ice", "path"),
    ("ravaged", "path"),
    ("stark", "mountain"),
    ("iron", "island"),
)


def clean_location(raw: str) -> str:
    s = _TITLE_PREFIX.sub("", raw.strip())
    cleaned = _CH_SUFFIX.sub("", s).strip(" .|")

    if "load" in cleaned.lower():
        return "ShakeChecker"

    cleaned = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", cleaned)
    return cleaned


def is_cave_location(name: str) -> bool:
    n = name.lower()
    if any(k in n for k in _CAVE_KEYWORDS):
        return True
    return any(all(word in n for word in group) for group in _CAVE_WORD_GROUPS)


def extract_location_mask(frame_bgr: np.ndarray, cal: LocationCalibration) -> np.ndarray | None:
    h, w = frame_bgr.shape[:2]
    crop = frame_bgr[int(h * cal.top): int(h * cal.bottom),
                     int(w * cal.left): int(w * cal.right)]
    if crop.size == 0:
        return None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(edges, kernel, iterations=1)
    return mask


def read_location(frame_bgr: np.ndarray, cal: LocationCalibration) -> str:
    """OCR the top-left HUD location (cleaned), or '' if not readable."""
    import time
    global _last_mask, _last_location, _last_loc_time

    # Throttle to ~4 Hz (prevents excessive CPU use)
    if time.time() - _last_loc_time < OCR_THROTTLE_S:
        return _last_location
    _last_loc_time = time.time()

    h, w = frame_bgr.shape[:2]

    # Initial HUD crop
    crop = frame_bgr[int(h * cal.top): int(h * cal.bottom),
                     int(w * cal.left): int(w * cal.right)]
    if crop.size == 0:
        return ""

    # --- LOOSER HEIGHT LIMIT (80% band) ---
    h0 = crop.shape[0]
    y_top = int(h0 * 0.10)
    y_bot = int(h0 * 0.90)
    PADY = 6
    y1p = max(0, y_top - PADY)
    y2p = min(h0, y_bot + PADY)
    crop = crop[y1p:y2p]

    # Build mask using edge detection
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    mask = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    # --- FAST PATH: skip OCR if mask unchanged ---
    if _last_mask is not None and mask.shape == _last_mask.shape:
        if np.array_equal(mask, _last_mask):
            return _last_location

    ys, xs = np.where(mask > 0)

    # --- LOOSER WIDTH LIMIT (55%) ---
    w0 = crop.shape[1]
    max_width = int(w0 * 0.55)
    PADX = 8

    if len(xs) > 0:
        x1b, x2b = xs.min(), xs.max()
        x1b = max(0, x1b - PADX)
        x2b = min(w0 - 1, x2b + PADX, max_width)
        crop = crop[:, x1b:x2b + 1]
    else:
        crop = crop[:, :max_width]

    # Resize to 48px height for CRNN
    scale = 48.0 / crop.shape[0]
    up = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # OCR
    texts = run_ocr_no_det(up, task_name="location_inference")

    # --- Store mask + location for next frame ---
    cleaned = clean_location(" ".join(texts)) if texts else _last_location
    _last_mask = mask.copy()
    _last_location = cleaned
    return cleaned
