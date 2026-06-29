"""Pure data structures for the dex domain.

These classes hold the domain state (encounters, caught lists, locations) and
are decoupled from session logic or screen reading.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

from core.account_store import _safe_account
from core.game_time import Period


@dataclass(frozen=True)
class DexEntry:
    id: int  # National Dex id (sort key / display order)
    name: str
    ways: tuple[str, ...]  # how to encounter it here; empty = plain grass/cave walking
    rarity: str  # the rarest rarity among this species' active encounters here
    caught: bool  # already OT-caught on the active account


@dataclass(frozen=True)
class LocationView:
    """What to show for the current location."""

    route: str  # display name, shown as the panel header
    region: str
    period: Period
    season: int
    entries: list[DexEntry]  # all available species (caught + uncaught), dex-sorted


# Rarity ordering (higher = rarer) for picking a species' headline rarity and for
# ranking the "rarest already-caught" entries the hybrid list pads with.
_RARITY_RANK = {
    "Very Rare": 6,
    "Rare": 5,
    "Special": 4,
    "Lure": 3,
    "Uncommon": 2,
    "Horde": 1,
    "Common": 1,
    "Very Common": 0,
}
# Once everything common is caught, the list pads its tail with caught species of
# these "notable" rarities (user choice) so the rares stay visible.
PAD_RARITIES = frozenset({"Lure", "Rare", "Very Rare"})

# Same channel-suffix strip used for the cave heuristic, kept local to avoid a
# circular import with location_reader.
_CH_SUFFIX = re.compile(r"\b(?:ch|cb|c|gh|oh|0h)\.?\s*(?:\d+)?(?:[^a-z0-9]*)$", re.IGNORECASE)
# Default fuzzy threshold (rapidfuzz ratio 0-100) for tolerating OCR noise.
MATCH_THRESHOLD = 82.0


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


# A "Special"-rarity encounter is a roaming phenomenon; label it by its method.
_PHENO = {
    "Grass": "Grass Pheno",
    "Water": "Water Pheno",
    "Shadow": "Shadow Pheno",
    "Dust Cloud": "Dust Pheno",
    "Fishing": "Fishing Pheno",
}
# Ambient walking encounters at normal rarity -- the default, so no tag.
_WALK = {"Grass", "Cave", "Inside"}
# The three fishing rods. When a species is on two or more of them, collapse them
# to a single "Rod" (you can fish it; the exact rod hardly matters and the full
# "Good Rod/Old Rod/Super Rod" is far too long); a single rod stays specific.
_RODS = {"Old Rod", "Good Rod", "Super Rod"}


def _compact_ways(ways: set[str]) -> tuple[str, ...]:
    rods = ways & _RODS
    if len(rods) >= 2:
        ways = (ways - rods) | {"Rod"}
    return tuple(sorted(ways))


def encounter_tag(method: str, rarity: str) -> str:
    """A short label for HOW to find a species via one encounter, or "" for the
    default (walking in plain grass/cave). Phenomena (Special rarity) read as
    "<Pheno>"; everything non-walking (surf Water, fishing rods, Headbutt, Rocks,
    Honey Tree, Dark Grass, Shadow) reads as the method. Lure is NOT a way -- it
    is a rarity (shown by colour), so a Lure spawn's way is just its method."""
    if rarity == "Special":
        return _PHENO.get(method, f"{method} Pheno")
    if method in _WALK:
        return ""
    return method


def available_here(encounters: list[dict], period: str, season: int) -> list[dict]:
    """The encounters active at this period AND season."""
    return [e for e in encounters if period in e["periods"] and season in e["seasons"]]


def location_entries(
    encounters: list[dict],
    period: str,
    season: int,
    caught: set[int],
    legendaries: set[int],
) -> list[DexEntry]:
    """All non-legendary species available now (caught AND uncaught), deduped by
    id with their encounter ways and headline (rarest) rarity, sorted by dex id.
    The caught flag lets the display show a to-do list and pad it with rares."""
    by_id: dict[int, dict] = {}
    for e in available_here(encounters, period, season):
        pid = e["id"]
        if pid in legendaries:
            continue
        slot = by_id.setdefault(pid, {"name": e["name"], "ways": set(), "rarities": set()})
        tag = encounter_tag(e["method"], e["rarity"])
        if tag:
            slot["ways"].add(tag)
        slot["rarities"].add(e["rarity"])
    entries = []
    for pid, slot in sorted(by_id.items()):
        rarity = max(slot["rarities"], key=lambda r: _RARITY_RANK.get(r, 0))
        entries.append(
            DexEntry(pid, slot["name"], _compact_ways(slot["ways"]), rarity, pid in caught)
        )
    return entries


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

    def location_for_key(self, key: str) -> dict:
        """The full location record (name, region, encounters) for a key."""
        return self._locations[key]

    def _candidate_keys(self, norm: str, region_u: str | None) -> list[str]:
        """All location keys matching a normalized name (region-filtered): exact
        normalized matches if any, else the best fuzzy match for OCR noise. The
        number tokens must match exactly so fuzzy can't turn "Route 5" into
        "Route 35"; only the word part is matched fuzzily."""

        def in_region(key: str) -> bool:
            return region_u is None or self._locations[key]["region"].upper() == region_u

        exact = [k for k in self._by_norm.get(norm, []) if in_region(k)]
        if exact:
            return exact
        qd = _digits(norm)
        candidates = {
            n: keys
            for n, keys in self._by_norm.items()
            if _digits(n) == qd and any(in_region(k) for k in keys)
        }
        if not candidates:
            return []
        best = process.extractOne(norm, candidates.keys(), scorer=fuzz.ratio)
        if best is None or best[1] < MATCH_THRESHOLD:
            return []
        return [k for k in candidates[best[0]] if in_region(k)]

    def match_location(self, hud_name: str, region: str | None = None) -> str | None:
        """Resolve an OCR'd HUD location name to a data key.

        With a region hint, only that region's locations are considered (so the
        shared "Route 5" name is unambiguous). Returns None if nothing clears the
        threshold or the name is ambiguous across regions with no usable hint.
        """
        norm = _normalize(hud_name)
        if not norm:
            return None
        keys = self._candidate_keys(norm, region.upper() if region else None)
        return keys[0] if len(keys) == 1 else None

    def is_exact(self, hud_name: str) -> bool:
        """True if the normalized name is an exact match for a known location."""
        norm = _normalize(hud_name)
        return norm in self._by_norm

    def regions_for_name(self, hud_name: str) -> set[str]:
        """The set of regions a HUD location name could belong to (ignoring any
        hint). A single-element set means the name pins the region down."""
        norm = _normalize(hud_name)
        if not norm:
            return set()
        return {self._locations[k]["region"] for k in self._candidate_keys(norm, None)}

    def entries_here(self, key: str, period: str, season: int, caught: set[int]) -> list[DexEntry]:
        """All non-legendary species available now at a location (caught + uncaught)."""
        loc = self._locations.get(key)
        if loc is None:
            return []
        return location_entries(loc["encounters"], period, season, caught, self._legendaries)

    def missing_here(self, key: str, period: str, season: int, caught: set[int]) -> list[DexEntry]:
        """Just the uncaught entries (convenience for the dev scripts)."""
        return [e for e in self.entries_here(key, period, season, caught) if not e.caught]


class CaughtStore:
    """The caught-species set for one account (accounts/<account>/caught.json)."""

    def __init__(self, path: Path, caught: set[int]) -> None:
        self.path = path
        self.caught = caught

    @classmethod
    def for_account(cls, userdata_dir: Path | str, account: str) -> CaughtStore:
        path = Path(userdata_dir) / "accounts" / _safe_account(account) / "caught.json"
        caught: set[int] = set()
        if path.exists():
            caught = {int(x) for x in json.loads(path.read_text("utf-8")).get("caught", [])}
        return cls(path, caught)

    def has(self, species_id: int) -> bool:
        return species_id in self.caught

    def add(self, species_id: int) -> bool:
        """Record a caught species. Returns True if it was newly added (so the
        caller can persist / log only on a real change)."""
        if species_id in self.caught:
            return False
        self.caught.add(species_id)
        self.save()
        return True

    def remove(self, species_id: int) -> bool:
        """Un-mark a species (manual correction). Returns True if it was present."""
        if species_id not in self.caught:
            return False
        self.caught.discard(species_id)
        self.save()
        return True

    def toggle(self, species_id: int) -> bool:
        """Flip the caught state. Returns the new state (True = now caught)."""
        if species_id in self.caught:
            self.remove(species_id)
            return False
        self.add(species_id)
        return True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"caught": sorted(self.caught)}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
