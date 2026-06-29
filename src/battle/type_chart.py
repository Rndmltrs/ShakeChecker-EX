from __future__ import annotations

# Gen 5 Type Effectiveness Matrix (No Fairy type)
# Rows: Attacking Type
# Cols: Defending Type
# The value is the multiplier (2.0 for Super Effective, 0.5 for Not Very Effective, 0.0 for Immune)

TYPES = [
    "NORMAL",
    "FIRE",
    "WATER",
    "ELECTRIC",
    "GRASS",
    "ICE",
    "FIGHTING",
    "POISON",
    "GROUND",
    "FLYING",
    "PSYCHIC",
    "BUG",
    "ROCK",
    "GHOST",
    "DRAGON",
    "DARK",
    "STEEL",
]

# Helper to look up type index
TYPE_IDX = {t: i for i, t in enumerate(TYPES)}

# 17x17 Matrix
# Order must strictly match the TYPES list above.
CHART = [
    # Defending type:
    # NRM  FIR  WAT  ELE  GRA  ICE  FIG  POI  GRO  FLY  PSY  BUG  ROC  GHO  DRA  DAR  STE
    [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 0.0, 1.0, 1.0, 0.5],  # NORMAL
    [1.0, 0.5, 0.5, 1.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 0.5, 1.0, 0.5, 1.0, 2.0],  # FIRE
    [1.0, 2.0, 0.5, 1.0, 0.5, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 1.0, 2.0, 1.0, 0.5, 1.0, 1.0],  # WATER
    [
        1.0,
        1.0,
        2.0,
        0.5,
        0.5,
        1.0,
        1.0,
        1.0,
        0.0,
        2.0,
        1.0,
        1.0,
        1.0,
        1.0,
        0.5,
        1.0,
        1.0,
    ],  # ELECTRIC
    [1.0, 0.5, 2.0, 1.0, 0.5, 1.0, 1.0, 0.5, 2.0, 0.5, 1.0, 0.5, 2.0, 1.0, 0.5, 1.0, 0.5],  # GRASS
    [1.0, 0.5, 0.5, 1.0, 2.0, 0.5, 1.0, 1.0, 2.0, 2.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 0.5],  # ICE
    [
        2.0,
        1.0,
        1.0,
        1.0,
        1.0,
        2.0,
        1.0,
        0.5,
        1.0,
        0.5,
        0.5,
        0.5,
        2.0,
        0.0,
        1.0,
        2.0,
        2.0,
    ],  # FIGHTING
    [1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 0.5, 0.5, 1.0, 1.0, 1.0, 0.5, 0.5, 1.0, 1.0, 0.0],  # POISON
    [1.0, 2.0, 1.0, 2.0, 0.5, 1.0, 1.0, 2.0, 1.0, 0.0, 1.0, 0.5, 2.0, 1.0, 1.0, 1.0, 2.0],  # GROUND
    [1.0, 1.0, 1.0, 0.5, 2.0, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 2.0, 0.5, 1.0, 1.0, 1.0, 0.5],  # FLYING
    [
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        2.0,
        2.0,
        1.0,
        1.0,
        0.5,
        1.0,
        1.0,
        1.0,
        1.0,
        0.0,
        0.5,
    ],  # PSYCHIC
    [1.0, 0.5, 1.0, 1.0, 2.0, 1.0, 0.5, 0.5, 1.0, 0.5, 2.0, 1.0, 1.0, 0.5, 1.0, 2.0, 0.5],  # BUG
    [1.0, 2.0, 1.0, 1.0, 1.0, 2.0, 0.5, 1.0, 0.5, 2.0, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 0.5],  # ROCK
    [0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 2.0, 1.0, 0.5, 0.5],  # GHOST
    [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 0.5],  # DRAGON
    [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 2.0, 1.0, 0.5, 0.5],  # DARK
    [1.0, 0.5, 0.5, 0.5, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0, 1.0, 1.0, 0.5],  # STEEL
]


def calculate_effectiveness(defender_types: tuple[str, ...]) -> dict[float, list[str]]:
    """
    Given the defender's types (e.g. ("WATER", "FLYING")), calculates the net
    multiplier for every possible attacking type.
    Returns a dictionary grouping attacking types by multiplier.
    Filters out neutral (1.0) effectiveness.
    """
    results: dict[float, list[str]] = {4.0: [], 2.0: [], 0.5: [], 0.25: [], 0.0: []}

    # If the defender has no known types, everything is 1x (which is filtered out)
    if not defender_types:
        return results

    for atk in TYPES:
        atk_idx = TYPE_IDX[atk]

        multiplier = 1.0
        for def_type in defender_types:
            if def_type not in TYPE_IDX:
                continue
            def_idx = TYPE_IDX[def_type]
            multiplier *= CHART[atk_idx][def_idx]

        if multiplier != 1.0 and multiplier in results:
            results[multiplier].append(atk)

    return results
