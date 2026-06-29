"""Refresh the vendored encounter data from PokeMMOZone/PokeMMO-Data.

Downloads `location-data.json` (PokeMMO-specific spawn tables -- NOT vanilla
PokeAPI) and normalizes it into `data/encounters.json`, the file the dex
tracker reads. The source encodes time-of-day and season inside a single `time`
string (e.g. "Day/Morning/SEASON0"); we parse that into explicit `periods` and
`seasons` so the tracker can filter without re-parsing.

Run:  python scripts/update_data.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

SOURCE_URL = (
    "https://raw.githubusercontent.com/PokeMMOZone/PokeMMO-Data/main/data/location-data.json"
)
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SPECIES_PATH = DATA / "species_core.json"
OUT_PATH = DATA / "encounters.json"

# The source's three time-of-day tokens map to PokeMMO's day periods. CLAUDE.md
# (milestone 4): Morning 04:00-10:59, Day 11:00-20:59, Night 21:00-03:59 (game
# time). The token set is exactly {Morning, Day, Night} plus "ALL".
PERIODS = ("MORNING", "DAY", "NIGHT")
ALL_SEASONS = [0, 1, 2, 3]


def parse_time(time_str: str) -> tuple[list[str], list[int]]:
    """Split the source `time` field into (periods, seasons).

    Examples: "ALL" -> (all periods, all seasons); "Day" -> (["DAY"], all);
    "Day/Morning/SEASON0" -> (["DAY","MORNING"], [0]). A missing period token
    (only "ALL" or only seasons) means every period; no SEASON token means
    every season.
    """
    tokens = [t.strip() for t in time_str.split("/") if t.strip()]
    periods = [t.upper() for t in tokens if t.upper() in PERIODS]
    seasons = [int(t[len("SEASON") :]) for t in tokens if t.upper().startswith("SEASON")]
    if not periods:  # "ALL" or season-only -> every period
        periods = list(PERIODS)
    if not seasons:
        seasons = list(ALL_SEASONS)
    return periods, seasons


def load_species_names() -> dict[int, str]:
    entries = json.loads(SPECIES_PATH.read_text("utf-8"))
    return {e["id"]: e["name"] for e in entries}


def normalize(raw: dict, names: dict[int, str]) -> dict:
    """Source {key: {name, region, encounters[...]}} -> our normalized form,
    deduping identical (id, method, rarity, level, time) rows."""
    locations: dict[str, dict] = {}
    for key, loc in raw.items():
        seen: set[tuple] = set()
        encounters: list[dict] = []
        for e in loc.get("encounters", []):
            pid = e["pokemon_id"]
            time = e.get("time", "ALL")
            sig = (pid, e["type"], e["rarity"], e["min_level"], e["max_level"], time)
            if sig in seen:
                continue
            seen.add(sig)
            periods, seasons = parse_time(time)
            encounters.append(
                {
                    "id": pid,
                    "name": names.get(pid, e["pokemon"].title()),
                    "method": e["type"],
                    "rarity": e["rarity"],
                    "min_level": e["min_level"],
                    "max_level": e["max_level"],
                    "periods": periods,
                    "seasons": seasons,
                }
            )
        encounters.sort(key=lambda x: (x["id"], x["method"], x["rarity"]))
        locations[key] = {
            "name": loc["name"],
            "region": loc["region"],
            "encounters": encounters,
        }
    return locations


def main() -> None:
    print("Fetching latest location-data.json from PokeMMOZone...")
    try:
        req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:  # noqa: S310 (trusted, https)
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"Error fetching data: {e}", file=sys.stderr)
        sys.exit(1)
    names = load_species_names()
    locations = normalize(raw, names)
    total = sum(len(v["encounters"]) for v in locations.values())

    old_locations_count = 0
    old_encounters_count = 0
    if OUT_PATH.exists():
        try:
            old_data = json.loads(OUT_PATH.read_text("utf-8"))
            old_locations_count = old_data.get("meta", {}).get("locations", 0)
            old_encounters_count = old_data.get("meta", {}).get("encounters", 0)
        except Exception:
            pass

    if old_locations_count > 0 or old_encounters_count > 0:
        loc_diff = len(locations) - old_locations_count
        enc_diff = total - old_encounters_count

        print(f"\nLocal data:  {old_locations_count} locations, {old_encounters_count} encounters")
        print(f"Remote data: {len(locations)} locations, {total} encounters")
        print(f"Difference:  {loc_diff:+} locations, {enc_diff:+} encounters")

        if loc_diff == 0 and enc_diff == 0:
            print("\nYour local data is already up to date.")
            ans = input("Force overwrite anyway? [y/N]: ").strip().lower()
            if ans != "y":
                print("Aborted.")
                return
        else:
            ans = input("\nApply these updates? [y/N]: ").strip().lower()
            if ans != "y":
                print("Aborted.")
                return

    out = {
        "meta": {
            "source": SOURCE_URL,
            "note": "PokeMMO-specific spawns; time/season parsed from the source 'time' field.",
            "locations": len(locations),
            "encounters": total,
        },
        "locations": locations,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(f"\nwrote {OUT_PATH}: {len(locations)} locations, {total} encounters")


if __name__ == "__main__":
    main()
