from __future__ import annotations

import datetime as dt

import pytest

from game_time import (
    Period,
    current_period,
    current_season,
    game_minute_of_day,
    period_for_game_minute,
    season_for_month,
)


def utc(hour: int, minute: int = 0, month: int = 1) -> dt.datetime:
    return dt.datetime(2026, month, 1, hour, minute, tzinfo=dt.UTC)


# --- game minute / cycle anchors ---


def test_cycle_restarts_at_six_hour_anchors():
    # the cycle restarts at 00/06/12/18 UTC -> game midnight (minute 0)
    for h in (0, 6, 12, 18):
        assert game_minute_of_day(utc(h)) == 0


def test_one_real_minute_is_four_game_minutes():
    assert game_minute_of_day(utc(0, 1)) == 4
    assert game_minute_of_day(utc(0, 15)) == 60  # 15 real min -> game 01:00


def test_game_minute_wraps_within_the_six_hour_cycle():
    # 01:00 and 07:00 UTC are the same point in the 6h cycle
    assert game_minute_of_day(utc(1)) == game_minute_of_day(utc(7))


# --- periods ---


def test_period_boundaries():
    assert period_for_game_minute(4 * 60) is Period.MORNING  # 04:00 game
    assert period_for_game_minute(10 * 60 + 59) is Period.MORNING
    assert period_for_game_minute(11 * 60) is Period.DAY  # 11:00 game
    assert period_for_game_minute(20 * 60 + 59) is Period.DAY
    assert period_for_game_minute(21 * 60) is Period.NIGHT  # 21:00 game
    assert period_for_game_minute(3 * 60) is Period.NIGHT  # 03:00 game (pre-morning)
    assert period_for_game_minute(0) is Period.NIGHT  # midnight


def test_current_period_from_utc():
    # 01:00 UTC -> 60 real min -> game 04:00 -> Morning
    assert current_period(utc(1)) is Period.MORNING
    # 00:45 UTC -> game 03:00 -> Night
    assert current_period(utc(0, 45)) is Period.NIGHT
    # 02:45 UTC -> game 11:00 -> Day
    assert current_period(utc(2, 45)) is Period.DAY


# --- seasons ---


def test_every_month_maps_to_a_season_index():
    for m in range(1, 13):
        assert season_for_month(m) in (0, 1, 2, 3)


def test_season_changes_monthly_and_uses_current_month():
    assert current_season(utc(0, month=6)) == season_for_month(6)
    assert current_season(utc(0, month=12)) == season_for_month(12)


def test_invalid_month_raises():
    with pytest.raises(KeyError):
        season_for_month(13)
