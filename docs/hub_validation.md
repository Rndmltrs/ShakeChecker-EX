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
