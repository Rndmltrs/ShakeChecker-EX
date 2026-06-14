"""Decide which species spawn at the current location that you still need.

Pure/injectable: the matching and missing-list logic take plain data so they are
unit-tested without files or screen capture. EncounterData wraps the vendored
`encounters.json` (built by scripts/update_data.py) plus the legendary exclusion
list and exposes the two operations the app needs:

- match_location(hud_name, region): map the OCR'd HUD location to a data key.
  The HUD shows only the bare name, but "Route 5" exists in several regions, so a
  region hint disambiguates; without one an ambiguous name returns None.
- missing_here(key, period, season, caught): the spawn list for that location at
  the given time/season, minus legendaries and minus what you've already caught,
  deduped by species and sorted by National Dex id (the display order).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

# Same channel-suffix strip used for the cave heuristic, kept local to avoid a
# circular import with location_reader.
_CH_SUFFIX = re.compile(r"\s*ch\.?\s*\d+.*$", re.IGNORECASE)
# Default fuzzy threshold (rapidfuzz ratio 0-100) for tolerating OCR noise.
MATCH_THRESHOLD = 82.0


@dataclass(frozen=True)
class MissingEntry:
    id: int  # National Dex id (sort key / display order)
    name: str
    methods: tuple[str, ...]  # encounter methods it appears under here (Grass, Water, ...)


def _normalize(name: str) -> str:
    """Lowercase, drop the channel suffix and punctuation, collapse whitespace.
    'Viridian Forest Ch. 2' / 'VIRIDIAN FOREST' both -> 'viridian forest'."""
    s = _CH_SUFFIX.sub("", name.strip().lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _digits(name: str) -> tuple[str, ...]:
    """The number tokens in a name. 'route 5' -> ('5',). Used to keep fuzzy
    matching from collapsing 'Route 5' into 'Route 35' (a substring win)."""
    return tuple(re.findall(r"\d+", name))


def available_here(encounters: list[dict], period: str, season: int) -> list[dict]:
    """The encounters active at this period AND season."""
    return [
        e for e in encounters if period in e["periods"] and season in e["seasons"]
    ]


def compute_missing(
    encounters: list[dict],
    period: str,
    season: int,
    caught: set[int],
    legendaries: set[int],
) -> list[MissingEntry]:
    """Species available now that are neither legendary nor already caught,
    deduped by id (collecting the methods) and sorted by dex id."""
    by_id: dict[int, dict] = {}
    for e in available_here(encounters, period, season):
        pid = e["id"]
        if pid in caught or pid in legendaries:
            continue
        slot = by_id.setdefault(pid, {"name": e["name"], "methods": set()})
        slot["methods"].add(e["method"])
    return [
        MissingEntry(pid, slot["name"], tuple(sorted(slot["methods"])))
        for pid, slot in sorted(by_id.items())
    ]


class EncounterData:
    """Loads the vendored encounter + legendary data and answers location/missing
    queries. Read-only; safe to share."""

    def __init__(self, locations: dict[str, dict], legendaries: set[int]) -> None:
        self._locations = locations
        self._legendaries = legendaries
        # normalized name -> [keys] (a name can repeat across regions)
        self._by_norm: dict[str, list[str]] = {}
        for key, loc in locations.items():
            self._by_norm.setdefault(_normalize(loc["name"]), []).append(key)

    @classmethod
    def load(cls, encounters_path: Path | str, legendaries_path: Path | str) -> EncounterData:
        enc = json.loads(Path(encounters_path).read_text("utf-8"))["locations"]
        leg = set(json.loads(Path(legendaries_path).read_text("utf-8"))["ids"])
        return cls(enc, leg)

    def location_name(self, key: str) -> str:
        return self._locations[key]["name"]

    def match_location(self, hud_name: str, region: str | None = None) -> str | None:
        """Resolve an OCR'd HUD location name to a data key.

        With a region hint, only that region's locations are considered (so the
        shared "Route 5" name is unambiguous). Tries an exact normalized match
        first, then a fuzzy match for OCR noise. Returns None if nothing clears
        the threshold or the name is ambiguous across regions with no hint.
        """
        norm = _normalize(hud_name)
        if not norm:
            return None
        region_u = region.upper() if region else None

        def in_region(key: str) -> bool:
            return region_u is None or self._locations[key]["region"].upper() == region_u

        exact = [k for k in self._by_norm.get(norm, []) if in_region(k)]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return None  # ambiguous (same name in multiple regions, no usable hint)

        # A name's number tokens must match exactly so fuzzy matching can't turn
        # "Route 5" into "Route 35"; the word part is still matched fuzzily.
        qd = _digits(norm)
        candidates = {
            n: keys
            for n, keys in self._by_norm.items()
            if _digits(n) == qd and any(in_region(k) for k in keys)
        }
        if not candidates:
            return None
        best = process.extractOne(norm, candidates.keys(), scorer=fuzz.WRatio)
        if best is None or best[1] < MATCH_THRESHOLD:
            return None
        keys = [k for k in candidates[best[0]] if in_region(k)]
        return keys[0] if len(keys) == 1 else None

    def missing_here(
        self, key: str, period: str, season: int, caught: set[int]
    ) -> list[MissingEntry]:
        loc = self._locations.get(key)
        if loc is None:
            return []
        return compute_missing(loc["encounters"], period, season, caught, self._legendaries)
