"""Second pass: measure exact fill run on the middle row of each detected bar.

Total inner bar width is 218 px (constant across all fixtures incl. 1920x1080,
verified from the full-health bars). Fill %% = run width / 218.
"""

from __future__ import annotations

import sys
from pathlib import Path

import colorsys

import cv2
import numpy as np

from measure_fixture_hp import FIXTURES, find_bar_rows

TOTAL = 218


def classify_hue(h: float) -> str:
    # OpenCV hue 0-179
    if 40 <= h <= 75:
        return "green"
    if 20 <= h < 40:
        return "yellow"
    return "red"


def fill_run(img: np.ndarray, y: int, x_hint: int) -> tuple[int, int, str] | None:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    row = hsv[y]
    colored = (row[:, 1] >= 80) & (row[:, 2] >= 80)
    # restrict to the bar neighbourhood
    lo, hi = max(0, x_hint - 15), min(img.shape[1], x_hint + 280)
    xs = [x for x in range(lo, hi) if colored[x]]
    if not xs:
        return None
    # longest contiguous run allowing 1px gaps
    runs, start, prev = [], xs[0], xs[0]
    for x in xs[1:]:
        if x - prev > 2:
            runs.append((start, prev))
            start = x
        prev = x
    runs.append((start, prev))
    x0, x1 = max(runs, key=lambda r: r[1] - r[0])
    hues = hsv[y, x0 : x1 + 1, 0].astype(float)
    return x0, x1, classify_hue(float(np.median(hues)))


def main() -> None:
    for png in sorted(FIXTURES.glob("*.png")):
        if png.name.startswith("overworld"):
            continue
        img = cv2.imread(str(png))
        for y0, y1, bx0, bx1 in find_bar_rows(img):
            y_mid = (y0 + y1) // 2
            r = fill_run(img, y_mid, bx0)
            if r is None:
                continue
            x0, x1, color = r
            w = x1 - x0 + 1
            print(
                f"{png.name:48s} y={y_mid:3d} x0={x0:4d} x1={x1:4d} "
                f"w={w:3d} fill={100 * w / TOTAL:5.1f}% {color}"
            )


if __name__ == "__main__":
    sys.exit(main())
