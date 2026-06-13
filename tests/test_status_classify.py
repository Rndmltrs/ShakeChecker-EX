"""Unit tests for status-badge classification on synthetic HSV crops.

The real SLP/PAR/PSN/none cases are covered against fixtures in
test_battle_reader.py. BRN and FRZ have no fixtures (CLAUDE.md: extrapolated
hue ranges, add a synthetic test each), so they are exercised here with
constructed badge crops.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from battle_reader import Status, classify_status_box, load_calibration

CAL = load_calibration(Path(__file__).parent.parent / "calibration.toml").status


def make_badge(fill_hsv=None, *, white=False, dark_rows=6) -> np.ndarray:
    """A 20x20 HSV badge crop: a dark border/icon band, a coloured (or white)
    fill band, and a neutral remainder (neither dark, white, nor a status hue)."""
    box = np.empty((20, 20, 3), np.uint8)
    box[:, :, 0] = 110  # neutral mid-grey: not dark, not white, no status hue
    box[:, :, 1] = 0
    box[:, :, 2] = 130
    box[:dark_rows, :, 2] = 50  # dark border/icon
    fill = slice(dark_rows, dark_rows + 9)
    if white:
        box[fill, :, 1] = 10
        box[fill, :, 2] = 200
    elif fill_hsv is not None:
        box[fill, :, 0], box[fill, :, 1], box[fill, :, 2] = fill_hsv
    return box


def test_no_badge_when_no_dark_border():
    # bright field, no dark pixels -> empty no-status slot (e.g. cave background)
    assert classify_status_box(make_badge(white=True, dark_rows=0), CAL) is Status.NONE


def test_empty_box():
    assert classify_status_box(np.empty((0, 0, 3), np.uint8), CAL) is Status.NONE


def test_slp_white_field():
    assert classify_status_box(make_badge(white=True), CAL) is Status.SLP


def test_par_yellow():
    assert classify_status_box(make_badge((28, 200, 200)), CAL) is Status.PAR


def test_psn_magenta():
    assert classify_status_box(make_badge((158, 200, 200)), CAL) is Status.PSN


def test_brn_red_extrapolated():
    assert classify_status_box(make_badge((5, 210, 200)), CAL) is Status.BRN


def test_frz_cyan_extrapolated():
    assert classify_status_box(make_badge((92, 210, 220)), CAL) is Status.FRZ
