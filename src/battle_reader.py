"""Detect battle state and read enemy HP bars from a captured frame.

Detection is structural, not position-based: within a configurable search
region, saturated green/yellow/red fill runs are located and validated
against the fixed bar geometry (218 px inner width, white crosshatch for the
empty part — see fixtures/expected.json _meta). This keeps the reader robust
against window size, resolution and the orange stat-stage boxes the game
draws next to the bar.

Pure/injectable: functions take a BGR frame (numpy) plus a Calibration; no
capture or global state in this module.
"""

from __future__ import annotations

import enum
import tomllib
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel


class HpColor(enum.StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class BattleState(enum.Enum):
    NO_BATTLE = "no_battle"
    SINGLE = "single"
    MULTI = "multi"  # double battle / horde: ignored in v1


@dataclass(frozen=True)
class BarReading:
    hp_pct: float  # (0, 100]
    color: HpColor
    x: int  # fill start, frame coords
    y: int  # bar middle row, frame coords


@dataclass(frozen=True)
class BattleReading:
    state: BattleState
    bars: tuple[BarReading, ...]


class HsvCalibration(BaseModel):
    sat_min: int
    val_min: int
    green_h: tuple[int, int]
    yellow_h: tuple[int, int]
    red_h_low: tuple[int, int]
    red_h_high: tuple[int, int]


class EmptyBarCalibration(BaseModel):
    val_min: int
    sat_max: int
    min_light_ratio: float


class FrameCalibration(BaseModel):
    sat_mean_max: float
    val_std_max: float
    val_mean_min: float
    val_mean_max: float
    search_px: int


class HpBarCalibration(BaseModel):
    inner_width_px: int
    width_tolerance_px: int
    full_fill_min_px: int
    search_top: float
    search_bottom: float
    search_left: float
    search_right: float
    min_fill_height_px: int
    max_fill_height_px: int
    min_fill_width_px: int
    merge_y_px: int
    hsv: HsvCalibration
    frame: FrameCalibration
    empty: EmptyBarCalibration


class Calibration(BaseModel):
    hp_bar: HpBarCalibration


def load_calibration(path: Path | str) -> Calibration:
    with open(path, "rb") as f:
        return Calibration.model_validate(tomllib.load(f))


def _fill_mask(hsv: np.ndarray, cal: HpBarCalibration) -> np.ndarray:
    c = cal.hsv
    mask = np.zeros(hsv.shape[:2], np.uint8)
    for h_lo, h_hi in (c.green_h, c.yellow_h, c.red_h_low, c.red_h_high):
        mask |= cv2.inRange(
            hsv,
            np.array([h_lo, c.sat_min, c.val_min]),
            np.array([h_hi, 255, 255]),
        )
    return mask


def _classify_color(median_hue: float, cal: HsvCalibration) -> HpColor:
    if cal.green_h[0] <= median_hue <= cal.green_h[1]:
        return HpColor.GREEN
    if cal.yellow_h[0] <= median_hue <= cal.yellow_h[1]:
        return HpColor.YELLOW
    return HpColor.RED


def _fill_run(
    hsv: np.ndarray, y: int, x_seed: int, cal: HpBarCalibration
) -> tuple[int, int] | None:
    """Contiguous saturated run on row `y` containing `x_seed` (1 px gaps ok)."""
    row = hsv[y]
    colored = (row[:, 1] >= cal.hsv.sat_min) & (row[:, 2] >= cal.hsv.val_min)
    if not colored[x_seed]:
        return None
    x0 = x_seed
    gap = 0
    while x0 > 0 and gap <= 1:
        gap = gap + 1 if not colored[x0 - 1] else 0
        x0 -= 1
    x0 += gap
    x1 = x_seed
    gap = 0
    limit = min(len(colored) - 1, x_seed + cal.inner_width_px + cal.width_tolerance_px)
    while x1 < limit and gap <= 1:
        gap = gap + 1 if not colored[x1 + 1] else 0
        x1 += 1
    x1 -= gap
    return x0, x1


def _empty_part_is_crosshatch(
    hsv: np.ndarray, y: int, fill_x0: int, fill_x1: int, cal: HpBarCalibration
) -> bool:
    """Validate that the rest of the bar (right of the fill) is the light
    crosshatch pattern, distinguishing a real HP bar from colored scenery."""
    start = fill_x1 + 3
    end = fill_x0 + cal.inner_width_px - 3
    if end > hsv.shape[1]:
        return False
    seg = hsv[y, start:end]
    if len(seg) < 4:
        return True  # nothing left to check; fill width already near-full
    light = (seg[:, 2] >= cal.empty.val_min) & (seg[:, 1] <= cal.empty.sat_max)
    return float(np.mean(light)) >= cal.empty.min_light_ratio


def _is_frame_outline_row(hsv: np.ndarray, y: int, x0: int, cal: HpBarCalibration) -> bool:
    if not 0 <= y < hsv.shape[0] or x0 + cal.inner_width_px > hsv.shape[1]:
        return False
    seg = hsv[y, x0 : x0 + cal.inner_width_px]
    f = cal.frame
    return (
        float(np.mean(seg[:, 1])) <= f.sat_mean_max
        and float(np.std(seg[:, 2])) <= f.val_std_max
        and f.val_mean_min <= float(np.mean(seg[:, 2])) <= f.val_mean_max
    )


def _has_bar_frame(
    hsv: np.ndarray, fill_top: int, fill_bottom: int, x0: int, cal: HpBarCalibration
) -> bool:
    """The bar's gray outline runs the full inner width directly above and
    below the fill; scenery and icons have no such uniform line."""
    s = cal.frame.search_px
    above = any(_is_frame_outline_row(hsv, y, x0, cal) for y in range(fill_top - s, fill_top))
    if not above:
        return False
    return any(
        _is_frame_outline_row(hsv, y, x0, cal) for y in range(fill_bottom + 1, fill_bottom + s + 1)
    )


def read_enemy_bars(frame_bgr: np.ndarray, cal: Calibration) -> list[BarReading]:
    """Find and measure all enemy HP bars in the frame, top to bottom."""
    c = cal.hp_bar
    h, w = frame_bgr.shape[:2]
    y0, y1 = int(h * c.search_top), int(h * c.search_bottom)
    x0, x1 = int(w * c.search_left), int(w * c.search_right)
    roi = frame_bgr[y0:y1, x0:x1]
    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hsv_full = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

    mask = _fill_mask(hsv_roi, c)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 9), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

    bars: list[BarReading] = []
    for i in range(1, n):
        bx, by, bw, bh, _area = stats[i]
        if not (c.min_fill_height_px <= bh <= c.max_fill_height_px):
            continue
        if bw < c.min_fill_width_px:
            continue
        # back to frame coordinates, measure on the blob's middle row
        fy = y0 + by + bh // 2
        fx = x0 + bx
        run = _fill_run(hsv_full, fy, fx, c)
        if run is None:
            continue
        rx0, rx1 = run
        fill_w = rx1 - rx0 + 1
        if fill_w > c.inner_width_px + c.width_tolerance_px:
            continue  # wider than a bar can be: scenery / UI panel
        if fill_w < c.full_fill_min_px and not _empty_part_is_crosshatch(hsv_full, fy, rx0, rx1, c):
            continue
        if not _has_bar_frame(hsv_full, y0 + by, y0 + by + bh - 1, rx0, c):
            continue
        hues = hsv_full[fy, rx0 : rx1 + 1, 0].astype(float)
        color = _classify_color(float(np.median(hues)), c.hsv)
        hp_pct = min(100.0, 100.0 * fill_w / c.inner_width_px)
        bars.append(BarReading(hp_pct=round(hp_pct, 1), color=color, x=rx0, y=fy))

    # merge duplicate detections of the same bar (multiple blobs per fill)
    bars.sort(key=lambda b: (b.y, b.x))
    merged: list[BarReading] = []
    for bar in bars:
        if merged and abs(bar.y - merged[-1].y) <= c.merge_y_px:
            if bar.hp_pct > merged[-1].hp_pct:
                merged[-1] = bar
            continue
        merged.append(bar)
    return merged


def read_battle(frame_bgr: np.ndarray, cal: Calibration) -> BattleReading:
    bars = read_enemy_bars(frame_bgr, cal)
    if not bars:
        state = BattleState.NO_BATTLE
    elif len(bars) == 1:
        state = BattleState.SINGLE
    else:
        state = BattleState.MULTI
    return BattleReading(state=state, bars=tuple(bars))
