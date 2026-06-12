"""One-off ground-truth helper: locate the enemy HP bar in fixture screenshots,
measure its fill ratio pixel-exactly and dump zoomed crops for visual checking.

This is intentionally independent of the (future) production reader: it scans
the whole top band of the image for saturated HP-bar colours instead of using
calibrated regions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
OUT = FIXTURES / "_debug_crops"

# HSV ranges (OpenCV: H 0-179)
GREEN = ((40, 120, 120), (75, 255, 255))
YELLOW = ((20, 120, 120), (39, 255, 255))
RED1 = ((0, 120, 120), (10, 255, 255))
RED2 = ((170, 120, 120), (179, 255, 255))


def color_mask(hsv: np.ndarray) -> np.ndarray:
    m = np.zeros(hsv.shape[:2], np.uint8)
    for lo, hi in (GREEN, YELLOW, RED1, RED2):
        m |= cv2.inRange(hsv, np.array(lo), np.array(hi))
    return m


def find_bar_rows(img: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Return candidate bars as (y0, y1, x0, x1) of contiguous colored blobs
    in the top 30% / left 60% of the image."""
    h, w = img.shape[:2]
    roi = img[: int(h * 0.30), : int(w * 0.60)]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    m = color_mask(hsv)
    # close small gaps (bar gloss/shading)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 9), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    bars = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        # HP bars are wide & flat; a 1-HP sliver is only a few px wide,
        # so only apply the aspect check once the blob is reasonably wide.
        if bh < 3 or bh > 20:
            continue
        if bw < 2:
            continue
        if bw > 8 and bw / bh < 2:
            continue
        bars.append((int(y), int(y + bh), int(x), int(x + bw)))
    bars.sort()
    return bars


def main() -> None:
    OUT.mkdir(exist_ok=True)
    results = {}
    for png in sorted(FIXTURES.glob("*.png")):
        img = cv2.imread(str(png))
        bars = find_bar_rows(img)
        results[png.name] = bars
        for k, (y0, y1, x0, x1) in enumerate(bars):
            # generous context crop around the bar, zoomed 6x
            cy0, cy1 = max(0, y0 - 18), min(img.shape[0], y1 + 14)
            cx0, cx1 = max(0, x0 - 30), min(img.shape[1], x1 + 220)
            crop = img[cy0:cy1, cx0:cx1]
            crop = cv2.resize(crop, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
            cv2.imwrite(str(OUT / f"{png.stem}_bar{k}.png"), crop)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    sys.exit(main())
