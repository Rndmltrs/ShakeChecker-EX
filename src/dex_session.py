"""Tie the dex-tracker pieces together for live use.

DexSession is the stateful glue between the screen readers and the data layer:
it remembers the current region (RegionResolver), knows the active account's
caught set (CaughtStore), and turns a HUD location name into the "still needed
here" view, filtered by the current in-game time/season. It also records a
species as caught when the in-battle OT ball icon is seen.

Pure of screen capture: callers feed it the OCR'd location name and the resolved
enemy species id; this module never touches the screen. Time defaults to the
real UTC clock but is injectable for tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from account_store import CaughtStore
from dex_tracker import DexEntry, EncounterData, RegionResolver
from game_time import Period, current_period, current_season


@dataclass(frozen=True)
class LocationView:
    """What to show for the current location."""

    route: str  # display name, shown as the panel header
    region: str
    period: Period
    season: int
    entries: list[DexEntry]  # all available species (caught + uncaught), dex-sorted


class DexSession:
    def __init__(
        self,
        data: EncounterData,
        caught: CaughtStore,
        area_index: dict[str, str],
        period_fn: Callable[[], Period] = current_period,
        season_fn: Callable[[], int] = current_season,
    ) -> None:
        self._data = data
        self._caught = caught
        self._resolver = RegionResolver(data, area_index)
        self._period_fn = period_fn
        self._season_fn = season_fn
        self._logged_unknowns: set[str] | None = None

    @property
    def region(self) -> str | None:
        return self._resolver.region

    def seed_region(self, region: str | None) -> None:
        """Pre-set the tracked region (a manual override / starting hint). A later
        region-unique location still takes over automatically."""
        self._resolver.region = region.upper() if region else None

    def is_exact_location(self, hud_name: str) -> bool:
        """True if the OCR name is already perfectly spelled."""
        return self._resolver.is_exact(hud_name)

    def on_location(self, hud_name: str) -> LocationView | None:
        """Resolve the HUD location (updating the tracked region) and build the
        missing-here view for the current time/season. None if the location can't
        be matched yet (unknown name, or an ambiguous one before a region is known)."""
        hud_name = self._resolver.correct_name(hud_name)
        key = self._resolver.resolve(hud_name)
        period = self._period_fn()
        season = self._season_fn()
        if key is None:
            if hud_name == "ShakeChecker":
                return LocationView("ShakeChecker", "Main Menu", period, season, [])
            # If the name is substantial but unknown (e.g. a city), return an empty view
            # so the panel stays open. Ignore tiny strings to prevent OCR noise flickering.
            if len(hud_name.strip()) > 3:
                clean_name = hud_name.strip().title()
                if not self.is_exact_location(clean_name):
                    self._log_unknown(clean_name)

                return LocationView(clean_name, self.region or "Unknown", period, season, [])
            return None
        entries = self._data.entries_here(key, period.value, season, self._caught.caught)
        loc = self._data.location_for_key(key)
        return LocationView(loc["name"], loc["region"], period, season, entries)

    def record_caught(self, species_id: int) -> bool:
        """Mark a species OT-caught (call when the OT ball icon is seen). Returns
        True if it was newly recorded, so the caller can log it once."""
        return self._caught.add(species_id)

    def toggle_caught(self, species_id: int) -> bool:
        """Manually flip a species' caught state (overlay check-off). Returns the
        new state (True = now caught)."""
        return self._caught.toggle(species_id)

    def set_caught(self, caught: CaughtStore) -> None:
        """Swap the active account's caught store (profile switch)."""
        self._caught = caught

    def _log_unknown(self, name: str) -> None:
        """Log genuinely unknown locations to a file so the user can review them."""
        import os

        log_path = "logs/locations.log"

        # Load existing logs on first use to prevent duplicates across app restarts
        if self._logged_unknowns is None:
            self._logged_unknowns = set()
            if os.path.exists(log_path):
                with open(log_path, encoding="utf-8") as f:
                    for line in f:
                        self._logged_unknowns.add(line.strip())

        if name in self._logged_unknowns:
            return

        self._logged_unknowns.add(name)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{name}\n")
