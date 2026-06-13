import json
from pathlib import Path

import pytest

from catch_calc import catch_probability, x_value

DATA = Path(__file__).parent.parent / "src" / "data"
BALLS = {b["id"]: b["rate"] for b in json.loads((DATA / "balls.json").read_text("utf-8"))["balls"]}
STATUS = json.loads((DATA / "status_rates.json").read_text("utf-8"))["rates"]


def test_bulbasaur_reference_case():
    # Bulbasaur (rate 45), 100% HP, Sleep, Poke Ball -> x = 30, P = 11.8%
    # (matches pokemmohub.com, see CLAUDE.md)
    x = x_value(1.0, 45, BALLS["poke"], STATUS["slp"])
    assert x == pytest.approx(30.0)
    p = catch_probability(1.0, 45, BALLS["poke"], STATUS["slp"])
    assert p == pytest.approx(0.118, abs=0.0005)


def test_status_rate_table():
    # Pin the catch multipliers: SLP/FRZ x2, PAR/PSN/BRN x1.5 (minor-status
    # bonus; PSN/BRN absent from Hub but confirmed x1.5 in-game), none x1.
    assert STATUS == {
        "none": 1.0,
        "slp": 2.0,
        "frz": 2.0,
        "par": 1.5,
        "psn": 1.5,
        "brn": 1.5,
    }


def test_guaranteed_catch_at_x_cap():
    # full HP contributes factor 1/3, so rate 255 with ball x3 gives x = 255 exactly -> 100%
    assert catch_probability(1.0, 255, ball_rate=3.0) == 1.0
    # anything above the cap stays 100%
    assert catch_probability(1.0, 255, ball_rate=4.0) == 1.0
    # just below the cap is < 100%
    assert catch_probability(1.0, 254, ball_rate=3.0) < 1.0


def test_lower_hp_increases_probability():
    full = catch_probability(1.0, 45)
    half = catch_probability(0.5, 45)
    sliver = catch_probability(0.01, 45)
    assert full < half < sliver


def test_one_third_hp_factor():
    # at p = 1/3 the HP factor is (3 - 2/3) / 3 = 7/9
    assert x_value(1 / 3, 90) == pytest.approx(90 * 7 / 9)


def test_status_and_ball_multipliers_compose():
    base = x_value(1.0, 45)
    assert x_value(1.0, 45, BALLS["ultra"], STATUS["par"]) == pytest.approx(base * 2.0 * 1.5)


def test_probability_bounds():
    for rate in (3, 45, 120, 200):
        for hp in (1.0, 0.5, 0.01):
            p = catch_probability(hp, rate)
            assert 0.0 < p <= 1.0


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        x_value(0.0, 45)
    with pytest.raises(ValueError):
        x_value(1.5, 45)
    with pytest.raises(ValueError):
        x_value(1.0, 0)
