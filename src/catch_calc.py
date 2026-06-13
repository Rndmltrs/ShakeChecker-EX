"""Pure catch-probability math (Gen 3/4 formula as used by PokeMMO).

Ported 1:1 from the PokeMMO Hub implementation
(src/hooks/useCatchRate.jsx, github.com/PokeMMO-Tools/pokemmo-hub).
This module performs no I/O; ball and status multipliers are plain arguments
(tables live in src/data/balls.json and src/data/status_rates.json).
"""

from __future__ import annotations

X_CAP = 255.0
SHAKE_SCALE = 65536.0


def x_value(
    hp_fraction: float,
    base_catch_rate: float,
    ball_rate: float = 1.0,
    status_rate: float = 1.0,
) -> float:
    """The pre-shake quantity `x`; catch is guaranteed at x >= 255.

    `hp_fraction` is currentHP / maxHP in (0, 1]; max HP cancels out of the
    original formula, so the fraction read off the HP bar is sufficient.
    """
    if not 0.0 < hp_fraction <= 1.0:
        raise ValueError(f"hp_fraction must be in (0, 1], got {hp_fraction}")
    if base_catch_rate <= 0:
        raise ValueError(f"base_catch_rate must be positive, got {base_catch_rate}")
    return ((3.0 - 2.0 * hp_fraction) / 3.0) * base_catch_rate * ball_rate * status_rate


def catch_probability(
    hp_fraction: float,
    base_catch_rate: float,
    ball_rate: float = 1.0,
    status_rate: float = 1.0,
) -> float:
    """Probability in [0, 1] that a single throw catches (four shake checks)."""
    x = x_value(hp_fraction, base_catch_rate, ball_rate, status_rate)
    if x >= X_CAP:
        return 1.0
    y = SHAKE_SCALE / (X_CAP / x) ** 0.25
    return (y / SHAKE_SCALE) ** 4
