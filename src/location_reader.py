"""Read the location name from the top-left HUD and decide if it is a cave."""

from __future__ import annotations

import re

import cv2
import numpy as np
from numpy.typing import NDArray

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

# --- Load Main Menu template (bottom half of “Loaded ROMs:”) ---
try:
    _ROM_TEMPLATE = cv2.imread("src/data/templates/mainmenu.png", cv2.IMREAD_GRAYSCALE)
except Exception:
    _ROM_TEMPLATE = None


def _is_main_menu_template(crop_gray: np.ndarray) -> bool:
    """Detect Main Menu using template matching (no OCR needed)."""
    if _ROM_TEMPLATE is None:
        return False

    # Match only the lower half of the HUD crop (tops are cut off)
    h = crop_gray.shape[0]
    roi = crop_gray[int(h * 0.45) : int(h * 0.95)]

    if roi.size == 0:
        return False

    th, tw = _ROM_TEMPLATE.shape
    # Scale ROI height to exactly match the template height
    scale = th / max(1, roi.shape[0])
    up_roi = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # Pad if the scaled ROI is narrower than the template
    if up_roi.shape[1] < tw:
        padded = np.zeros((th, tw), dtype=np.uint8)
        padded[:, : up_roi.shape[1]] = up_roi
        up_roi = padded

    res = cv2.matchTemplate(up_roi, _ROM_TEMPLATE, cv2.TM_CCOEFF_NORMED)
    return np.max(res) >= 0.65


def clean_location(raw: str) -> str:
    s = _TITLE_PREFIX.sub("", raw.strip())
    cleaned = _CH_SUFFIX.sub("", s).strip(" .|")

    # The OCR sometimes jumbles "Loaded ROMs:" into "addedroms:" or "Adedros:"
    lower_clean = cleaned.lower()
    if any(x in lower_clean for x in ("load", "roms", "added", "aded", "dros")):
        return "ShakeChecker"

    cleaned = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", cleaned)
    return cleaned


def is_cave_location(name: str) -> bool:
    n = name.lower()
    if any(k in n for k in _CAVE_KEYWORDS):
        return True
    return any(all(word in n for word in group) for group in _CAVE_WORD_GROUPS)


def extract_location_mask(
    frame_bgr: NDArray[np.uint8], cal: LocationCalibration
) -> NDArray[np.uint8] | None:
    h, w = frame_bgr.shape[:2]

    y1 = int(cal.top) if cal.top > 1.0 else int(h * cal.top)
    y2 = int(cal.bottom) if cal.bottom > 1.0 else int(h * cal.bottom)
    x1 = int(cal.left) if cal.left > 1.0 else int(w * cal.left)
    x2 = int(cal.right) if cal.right > 1.0 else int(w * cal.right)

    crop = frame_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(edges, kernel, iterations=1)

    # Ensure mask is uint8 for OpenCV + mypy compatibility
    return mask.astype(np.uint8, copy=False)


def read_location(frame_bgr: np.ndarray, cal: LocationCalibration) -> str:
    """OCR the top-left HUD location (cleaned), or '' if not readable."""
    import time

    global _last_mask, _last_location, _last_loc_time

    # Throttle to ~4 Hz
    if time.time() - _last_loc_time < OCR_THROTTLE_S:
        return _last_location
    _last_loc_time = time.time()

    h, w = frame_bgr.shape[:2]

    # Initial HUD crop
    y1 = int(cal.top) if cal.top > 1.0 else int(h * cal.top)
    y2 = int(cal.bottom) if cal.bottom > 1.0 else int(h * cal.bottom)
    x1 = int(cal.left) if cal.left > 1.0 else int(w * cal.left)
    x2 = int(cal.right) if cal.right > 1.0 else int(w * cal.right)
    crop = frame_bgr[y1:y2, x1:x2]
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

    # Convert to grayscale early for template matching
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    # Build mask using edge detection
    edges = cv2.Canny(gray, 40, 120)
    mask = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    # --- FAST PATH: skip OCR if mask unchanged ---
    if (
        _last_mask is not None
        and mask.shape == _last_mask.shape
        and np.array_equal(mask, _last_mask)
    ):
        return _last_location

    # --- TEMPLATE MATCHING MAIN MENU DETECTION ---
    if _is_main_menu_template(gray):
        _last_mask = mask.copy()
        _last_location = "ShakeChecker"
        return "ShakeChecker"

    ys, xs = np.where(mask > 0)

    # --- LOOSER WIDTH LIMIT (55%) ---
    w0 = crop.shape[1]
    max_width = int(w0 * 0.55)
    PADX = 8

    if len(xs) > 0:
        x1b, x2b = xs.min(), xs.max()
        x1b = max(0, x1b - PADX)
        x2b = min(w0 - 1, x2b + PADX, max_width)

        # If edges were found only past max_width, x1b will be > x2b
        crop = crop[:, :max_width] if x1b > x2b else crop[:, x1b : x2b + 1]
    else:
        crop = crop[:, :max_width]

    if crop.shape[0] == 0 or crop.shape[1] == 0:
        return _last_location

    # Resize to 48px height for CRNN
    scale = 48.0 / crop.shape[0]
    up = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # OCR
    texts = run_ocr_no_det(up, task_name="location_inference")

    cleaned = clean_location(" ".join(texts)) if texts else _last_location

    _last_mask = mask.copy()
    _last_location = cleaned
    return cleaned
