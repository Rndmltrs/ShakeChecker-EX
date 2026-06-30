# PokeMMO Game Mechanics & Domain Rules

This document outlines the hard constraints, game math, and screen-reading mechanics that drive ShakeChecker. It serves as the product specification for how the application interacts with the PokeMMO client.

## 1. Hard Operating Constraints

ShakeChecker is a **passive screen-reader**. It strictly adheres to the following constraints:
- **No Input Automation:** No key presses, no mouse clicks into the game. This is non-negotiable to comply with PokeMMO terms of service.
- **No Memory Reading:** No injection, no network interception, and no reading of process memory. Screen capture only.
- **Relative Coordinates:** All screen regions are defined as percentages relative to the game window's client area. The game window can be any size and can be moved at runtime without breaking the OCR.

## 2. The Catch Formula

PokeMMO uses a modified **Gen 3/4 catch formula**. ShakeChecker's implementation (`src/battle/catch_calc.py`) is ported 1:1 from the open-source PokeMMO Hub. 

With `p = currentHP / maxHP` (read as a fraction from the HP bar, meaning max HP cancels out):

```text
x = ((3 - 2p) / 3) * base_catch_rate * ball_rate * status_rate
if x > 255: P(catch) = 100%
else:
    y = 65536 / (255 / x) ** 0.25
    P(catch) = (y / 65536) ** 4      # four shake checks
```

### Modifiers & PokeMMO Deviations
- **Status Rates:** Sleep ×2, Freeze ×2, Paralysis ×1.5, None ×1. 
  - *PokeMMO Deviation:* Poison and Burn apply a minor-status bonus of ×1.5 (unlike mainline Gen 5).
- **Ball Multipliers:** 
  - Poke ×1, Great ×1.5, Ultra ×2, Heal ×1.25, Luxury ×2, Net ×3.5, Nest ×4, Dusk ×2.5, Quick ×5, Timer ×4, Repeat ×2.5, Dream ×4.
  - *Note:* In v1, ball multipliers are treated as flat multipliers matching the PokeMMO Hub implementation.
- **No Level Bonus:** Level modifiers and critical captures are not modeled in the current formula.

## 3. Data Sources

ShakeChecker relies on specific single-sources of truth to avoid drifting from game reality.

- **`species_index.json`:** The single source of truth for base catch rates and typing. This is the only file the runtime reads for catch math.
  - **Schema:** `{id, name, types, catch_rate, obtainable}` (where `id` is the National Dex order).
  - **Sources:** Catch rates, names, typings, and EVs originate from the [PokeMMO Hub](https://github.com/PokeMMO-Tools/pokemmo-hub).
  - **Unpublished Rates:** `catch_rate` is explicitly `null` for species with no published rate (e.g., roaming Latias, Latios, Mesprit, Cresselia). The overlay safely handles this by displaying `??`.
  - **Hand Corrections:** The roaming birds/beasts (Articuno, Zapdos, Moltres, Raikou, Entei, Suicune) have a catch rate of `3` per the in-client PokeMMO catch calculator, overriding the Hub's default of `5`. Do not "re-sync" these back from the Hub.

- **`encounter_index.json`** PokeMMO-specific spawn tables tracking which Pokémon appear on which routes. 
  - **Source:** Parsed and inverted directly from `monster.json` provided by [PokeMMO Hub](https://github.com/PokeMMO-Tools/pokemmo-hub).
  - **Constraint:** Do NOT use vanilla PokeAPI encounter tables, as PokeMMO heavily modifies spawns for MMO balance (e.g., Alphas, Swarms, custom level brackets).

### Data Update Path
When game updates introduce new mechanics or spawn shifts, data must be refreshed by pulling the latest dumps from PokeMMO Hub:
1. Execute `scripts/update_species.py` to pull the latest `monster.json` and `catchRates.json` to generate the normalized `species_index.json`.
2. Execute `scripts/update_locations.py` to parse and invert the `monster.json` encounter data into a location-first hierarchy (`encounter_index.json`).

## 4. Vision & OCR Mechanics

The application reads the screen using OpenCV and RapidOCR, utilizing specific techniques to filter out animation noise.

- **HP% Tracking:** Crops the enemy HP bar region and uses color-masking for green/yellow/red hues to measure the filled width vs total width. This guarantees accurate readings regardless of the current color state.
- **Status Detection:** PokeMMO status badges share the exact same shape and only differ by color. The app detects badge *presence* (pixel activity vs. empty baseline) and classifies it by dominant hue (e.g., yellow=PAR, purple=PSN).
- **Name OCR:** Crops the name region, upscales 2-3x, runs OCR, and then fuzzy-matches against the known `species_index.json` list. It never trusts raw OCR output. 
  - *Language constraint:* All matching currently assumes the English client.
- **Turn Counter:** Increments by 1 every time the move-selection UI disappears (indicating the player committed an action).

## 5. Game Time & Overworld Clock

The overworld PokeMMO clock is deterministic and anchored to UTC server time. ShakeChecker calculates the game period (Morning, Day, Night) strictly via math, bypassing the need to OCR the HUD clock.

- One PokeMMO day = 6 real hours.
- A new PokeMMO day starts at `00:00`, `06:00`, `12:00`, and `18:00` UTC.
- **Formula:** `game_minutes = (minutes_since_utc_midnight % 360) * 4`
- **Periods:** Morning (`04:00-10:59`), Day (`11:00-20:59`), Night (`21:00-03:59`). 

*Always compute from UTC, never local time, ensuring Daylight Savings Time safety.*
