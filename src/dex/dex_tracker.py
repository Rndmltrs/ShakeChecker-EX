"""Decide which species spawn at the current location that you still need.

Pure/injectable: the matching and missing-list logic take plain data so they are
unit-tested without files or screen capture. EncounterData wraps the vendored
`encounter_index.json` (built by scripts/update_data.py) plus the legendary exclusion
list and exposes the two operations the app needs:

- match_location(hud_name, region): map the OCR'd HUD location to a data key.
  The HUD shows only the bare name, but "Route 5" exists in several regions, so a
  region hint disambiguates; without one an ambiguous name returns None.
- missing_here(key, period, season, caught): the spawn list for that location at
  the given time/season, minus legendaries and minus what you've already caught,
  deduped by species and sorted by National Dex id (the display order).
"""

from __future__ import annotations

from dex.dex_structures import (
    _RARITY_RANK,
    MATCH_THRESHOLD,
    PAD_RARITIES,
    DexEntry,
    EncounterData,
    _normalize,
)


def display_order(entries: list[DexEntry], keep_caught: bool = False) -> list[DexEntry]:
    """The full ordered list for the (scrollable) panel.

    Uncaught species always come first, sorted by dex id. The caught tail depends
    on the mode (issue #16):

    - keep_caught=True: every caught species, by dex id (shown checked at the
      bottom -- nothing is removed from the list).
    - keep_caught=False: only the already-caught Lure/Rare/Very Rare ones, rarest
      first (the old behaviour -- common caught species are hidden).
    """
    uncaught = sorted((e for e in entries if not e.caught), key=lambda e: e.id)
    if keep_caught:
        caught = sorted((e for e in entries if e.caught), key=lambda e: e.id)
    else:
        caught = sorted(
            (e for e in entries if e.caught and e.rarity in PAD_RARITIES),
            key=lambda e: (-_RARITY_RANK[e.rarity], e.id),
        )
    return uncaught + caught


class RegionResolver:
    """Tracks the current region so ambiguous location names ("Route 5" exists in
    Kanto and Unova) resolve correctly, with no manual region input.

    The HUD shows only the bare location name. As soon as a name pins the region
    (it exists in exactly one region -- forests, caves, most named places), we
    adopt it; switching regions means passing through such a place (e.g. the
    harbour town you arrive in), so the region is taken over automatically.
    Ambiguous names then resolve against the remembered region. Encounter-less
    towns aren't in the data and simply don't change the region.
    """

    def __init__(self, data: EncounterData, area_index: dict[str, str]) -> None:
        self._data = data
        self._area_index = area_index
        self.region: str | None = None

    def reset(self) -> None:
        self.region = None

    def resolve(self, hud_name: str) -> str | None:
        """Location key for the current HUD name, updating the tracked region when
        the name determines it. Returns None if unmatched or still ambiguous."""
        norm = _normalize(hud_name)
        if not norm:
            return None

        if norm in self._area_index:
            self.region = self._area_index[norm].upper()
            if not self._data.is_exact(hud_name):
                return None
        else:
            regions = self._data.regions_for_name(hud_name)
            if len(regions) == 1:
                self.region = next(iter(regions))  # name pins the region -> adopt/switch

        return self._data.match_location(hud_name, self.region)

    def correct_name(self, hud_name: str) -> str:
        """Attempt to fix an incomplete OCR name by mapping it to the closest known
        town or route, ensuring the UI always displays cleanly spelled locations."""
        norm = _normalize(hud_name)
        if not norm:
            return hud_name

        if norm in self._area_index:
            return norm.title()

        from rapidfuzz import fuzz, process

        best_town = process.extractOne(norm, self._area_index.keys(), scorer=fuzz.ratio)
        if best_town and best_town[1] >= MATCH_THRESHOLD:
            return best_town[0].title()

        # Try routes using the digits-restricted fuzzy match
        keys = self._data._candidate_keys(norm, self.region.upper() if self.region else None)
        if keys:
            names = {self._data._locations[k]["name"] for k in keys}
            if len(names) == 1:
                return next(iter(names))

        return hud_name

    def is_exact(self, hud_name: str) -> bool:
        """True if the normalized name exactly matches a known route or encounter-less town."""
        norm = _normalize(hud_name)
        return norm in self._area_index or self._data.is_exact(hud_name)
