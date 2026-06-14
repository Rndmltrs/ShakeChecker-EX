"""Compute the in-game time period and season from the real-world UTC clock.

PokeMMO's day/night cycle is deterministic and server-anchored to UTC, so we
compute it instead of OCR-ing the HUD clock (CLAUDE.md milestone 4): one PokeMMO
day = 6 real hours, the cycle restarting at 00:00/06:00/12:00/18:00 UTC. Always
work from UTC, never local time, so daylight-saving never shifts the result.

    game_minutes = (minutes_since_utc_midnight % 360) * 4   # 0..1439

Periods (in game time):
    Morning 04:00-10:59, Day 11:00-20:59, Night 21:00-03:59

Seasons cycle monthly (4 seasons). The exact month->SEASONn mapping in the
encounter data is anchored once and verified against the game -- see SEASON_OF_MONTH.
"""

from __future__ import annotations

import datetime as _dt
import enum


class Period(enum.StrEnum):
    MORNING = "MORNING"
    DAY = "DAY"
    NIGHT = "NIGHT"


# Minutes in one in-game day, and the real-minutes:game-minutes ratio (a 6h real
# cycle maps onto a 24h game day -> 24/6 = 4 game-minutes per real-minute).
GAME_DAY_MINUTES = 1440
REAL_CYCLE_MINUTES = 360
GAME_MINUTES_PER_REAL = GAME_DAY_MINUTES // REAL_CYCLE_MINUTES  # 4

# PokeMMO season for each calendar month (1=Jan..12=Dec), as SEASON0..3 indices
# used in the encounter data. Seasons rotate monthly. ANCHOR: verify once against
# the in-game season indicator; adjust this table if the data's SEASONn differs.
# Convention used here: Spring=0, Summer=1, Autumn=2, Winter=3, with the standard
# meteorological-style grouping PokeMMO uses (season advances each month, wrapping
# every 4 months: Jan=Winter? -> see note). Kept as a single table so the mapping
# is one edit away from correct.
SEASON_OF_MONTH = {
    1: 3, 2: 0, 3: 0, 4: 0,   # Jan winter; Feb-Apr spring
    5: 1, 6: 1, 7: 1,         # May-Jul summer
    8: 2, 9: 2, 10: 2,        # Aug-Oct autumn
    11: 3, 12: 3,             # Nov-Dec winter
}


def game_minute_of_day(now_utc: _dt.datetime) -> int:
    """In-game minute-of-day (0..1439) for a UTC datetime."""
    minutes_since_midnight = now_utc.hour * 60 + now_utc.minute
    return (minutes_since_midnight % REAL_CYCLE_MINUTES) * GAME_MINUTES_PER_REAL


def period_for_game_minute(game_minute: int) -> Period:
    """Map an in-game minute-of-day to its period (see module docstring)."""
    hour = game_minute // 60
    if 4 <= hour <= 10:
        return Period.MORNING
    if 11 <= hour <= 20:
        return Period.DAY
    return Period.NIGHT  # 21-23 and 0-3


def season_for_month(month: int) -> int:
    """SEASONn index (0..3) for a calendar month (1..12)."""
    return SEASON_OF_MONTH[month]


def current_period(now_utc: _dt.datetime | None = None) -> Period:
    now = now_utc or _dt.datetime.now(_dt.UTC)
    return period_for_game_minute(game_minute_of_day(now))


def current_season(now_utc: _dt.datetime | None = None) -> int:
    now = now_utc or _dt.datetime.now(_dt.UTC)
    return season_for_month(now.month)
