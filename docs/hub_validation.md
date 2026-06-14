# Validation against PokeMMO Hub (Milestone 1)

Date: 2026-06-13. Source compared:
`https://github.com/PokeMMO-Tools/pokemmo-hub`, `src/hooks/useCatchRate.jsx` (branch `main`).

## Formula comparison

Hub source (verbatim):

```js
const x = (((max_hp * 3 - current_hp * 2) * 1 * pkmn_rate * pokeball.rate) / (max_hp * 3)) * status.rate
const y = (65536 / (Math.sqrt(Math.sqrt(255 / x))))
const z = (y / 65536) * (y / 65536) * (y / 65536) * (y / 65536) * 100
```

`src/catch_calc.py` is algebraically identical:

- `(max_hp*3 - current_hp*2) / (max_hp*3)` ≡ `(3 - 2p) / 3` with `p = current/max`
  (max HP cancels; only the bar fraction is needed).
- `sqrt(sqrt(255/x))` ≡ `(255/x) ** 0.25`.
- `(y/65536)^4` is the four-shake-check probability; we cap at `x >= 255 -> P = 1`
  (the Hub `z` formula exceeds 100 there and is clamped in its UI).

## Table comparison

- Ball rates in `src/data/balls.json` match the Hub list exactly
  (Poke 1, Great 1.5, Ultra 2, Heal 1.25, Net 3.5, Nest 4, Dusk 2.5, Quick 5,
  Timer 4, Repeat 2.5, Luxury 2, Dream 4; all flat, no conditions).
- Status rates match: none 1, SLP 2, FRZ 2, PAR 1.5. PSN/BRN are absent from
  the Hub list; `src/data/status_rates.json` carries them as 1.0 with an open
  question marker (see CLAUDE.md).

## Spot checks (computed by `catch_calc.py`)

| Case | x | P |
|---|---|---|
| Bulbasaur (rate 45), 100% HP, SLP, Poke Ball | 30.00 | 11.76% |
| Rate 45, 65.1% HP, none, Poke Ball | 25.47 | 9.99% |
| Rate 45, 4.6% HP, SLP, Ultra Ball | 174.48 | 68.42% |
| Rate 25, 100% HP, none, Great Ball | 12.50 | 4.90% |
| Rate 45, 1.0% HP, SLP, Quick Ball | 447.00 | 100% (x ≥ 255) |

The Bulbasaur case is the documented reference from pokemmohub.com (11.8%,
CLAUDE.md) and is pinned in `tests/test_catch_calc.py`.

## Conditional ball multipliers (PokeMMO, not the flat Hub model)

The Hub models every ball as a flat multiplier. PokeMMO actually applies
conditions — verified against the PokeMMO Wiki and the PokeMMO-specific catch
calculator `c4vv/CatchCalc` (`pokeballs.js`). Ported into `catch_calc.py`
(`BALL_RULES`) / `src/data/balls.json`:

| Ball | Multiplier | Condition |
|---|---|---|
| Quick | 5.0 else 1.0 | first turn only (`turns_completed == 0`) |
| Timer | `1 + min(3, turns_completed*0.3)` (max 4) | ramps per completed turn |
| Net | 3.5 else 1.0 | enemy is Water or Bug type |
| Nest | `min(max(7 - 0.2*(level-1), 1), 4)` | low enemy level |
| Dusk | 2.5 else 1.0 | night / cave |
| Dream | `min(4, 1 + turns_asleep)` | scales with turns the enemy slept (0-3 → 1x-4x) |
| Luxury | 1.0 | (Hub had 2.0 — wrong; Luxury is friendship, not catch) |
| Repeat | 1.0 (placeholder) | CatchCalc uses a chain count; unconfirmed, left at 1.0 |
| Poke/Great/Ultra/Heal | 1 / 1.5 / 2 / 1.25 | flat |

The flat balls and the core formula are confirmed against
pokemmo.help/capture-chance — Roselia (rate 150, 50% HP, no status): Poke
39.21% (we compute 39.22%, a 65535-vs-65536 rounding artefact), Great 58.82%.

Turn-dependent balls (Quick, Timer, Dream) need the battle turn / sleep-turn
counter; until it lands the app assumes turn 1 with no accrued sleep
(`turns_completed = turns_asleep = 0`), which is correct for the first turn
(Quick ×5, Timer ×1, Dream ×1). The Hub's flat Dream ×4 was wrong — Dream is
×1 against a non-sleeping target. Dusk (night/cave) and Repeat (caught-before)
depend on data that arrives in milestone 4 and currently resolve to ×1.

Sources: [PokeMMO Wiki — Quick Ball](https://pokemmo.shoutwiki.com/wiki/Quick_Ball),
[c4vv/CatchCalc](https://github.com/c4vv/CatchCalc).
