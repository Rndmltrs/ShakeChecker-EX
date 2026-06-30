"""Parse the PokeMMO-Hub pokemon-data.json dump into ShakeChecker's normalized
species_index.json."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
from core.paths import SPECIES_INDEX_PATH as OUT_PATH  # noqa: E402

URL_DATA = (
    "https://raw.githubusercontent.com/PokeMMO-Tools/pokemmo-hub/main/src/data/pokemmo/monster.json"
)
URL_RATES = (
    "https://raw.githubusercontent.com/PokeMMO-Tools/pokemmo-hub/main/src/data/catchRates.json"
)

# PokeMMO Catch Calculator manual overrides (defaults in Hub are 5)
LEGENDARY_OVERRIDES = {
    144: 3,  # Articuno
    145: 3,  # Zapdos
    146: 3,  # Moltres
    243: 3,  # Raikou
    244: 3,  # Entei
    245: 3,  # Suicune
}


def fetch_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    print("Fetching latest data dumps from PokeMMO-Hub...")
    try:
        raw_data = fetch_json(URL_DATA)
        raw_rates = fetch_json(URL_RATES)
    except urllib.error.URLError as e:
        print(f"Error fetching data: {e}", file=sys.stderr)
        sys.exit(1)

    rates_map = {item["id"]: item["rate"] for item in raw_rates if "id" in item and "rate" in item}

    # Load existing data early to preserve names and missing catch rates
    old_data = []
    old_map = {}
    old_ids = set()
    old_count = 0
    if OUT_PATH.exists():
        try:
            with open(OUT_PATH, encoding="utf-8") as f:
                raw = json.load(f)
                old_data = raw.get("species", raw) if isinstance(raw, dict) else raw
                old_count = len(old_data)
                old_map = {e["id"]: e for e in old_data if "id" in e}
                old_ids = set(old_map.keys())
        except Exception:
            pass

    entries = []

    # Depending on the source, raw_data might be a list or a dict.
    data_list = raw_data.values() if isinstance(raw_data, dict) else raw_data

    for data in data_list:
        if not isinstance(data, dict):
            continue

        pid = data.get("id")
        if not pid:
            continue

        old_entry = old_map.get(pid, {})

        name = data.get("name", "").replace("’", "'")

        types = [t.upper() for t in data.get("types", [])]

        catch_rate = rates_map.get(pid)
        # Preserve old catch rates if the new API is missing them (e.g. for custom forms)
        if catch_rate is None and old_entry and "catch_rate" in old_entry:
            catch_rate = old_entry["catch_rate"]
        obtainable = data.get("obtainable", False)

        ev_yield = {}
        yields = data.get("yields", {})

        # Fallback to old 'stats' format if 'yields' doesn't exist
        if not yields and "stats" in data:
            for stat in data.get("stats", []):
                effort = stat.get("effort", 0)
                if effort > 0:
                    ev_yield[stat.get("stat_name")] = effort
        else:
            if yields.get("ev_hp"):
                ev_yield["hp"] = yields["ev_hp"]
            if yields.get("ev_attack"):
                ev_yield["attack"] = yields["ev_attack"]
            if yields.get("ev_defense"):
                ev_yield["defense"] = yields["ev_defense"]
            if yields.get("ev_sp_attack"):
                ev_yield["special-attack"] = yields["ev_sp_attack"]
            if yields.get("ev_sp_defense"):
                ev_yield["special-defense"] = yields["ev_sp_defense"]
            if yields.get("ev_speed"):
                ev_yield["speed"] = yields["ev_speed"]

        # Apply hardcoded overrides
        if pid in LEGENDARY_OVERRIDES:
            catch_rate = LEGENDARY_OVERRIDES[pid]

        entries.append(
            {
                "id": pid,
                "name": name,
                "types": types,
                "catch_rate": catch_rate,
                "obtainable": obtainable,
                "ev_yield": ev_yield,
            }
        )

    # Merge back any old species that don't exist in the new dataset
    new_ids = {e["id"] for e in entries}
    for old_entry in old_data:
        if old_entry["id"] not in new_ids:
            entries.append(old_entry)

    # Deduplicate types to ensure consistency (e.g. single ['FIRE'] instead of ['FIRE', 'FIRE'])
    for entry in entries:
        entry_types = entry.get("types")
        if isinstance(entry_types, list):
            entry["types"] = list(dict.fromkeys(entry_types))

    # Sort strictly by National Dex ID
    entries.sort(key=lambda x: x["id"])

    new_count = len(entries)
    print(f"\nLocal data:  {old_count} species")
    print(f"New data:    {new_count} species")
    print(f"Difference:  {new_count - old_count:+} species")

    new_species = [e for e in entries if e["id"] not in old_ids]
    if new_species:
        print("\nNew species found:")
        for s in new_species:
            s_types = s.get("types")
            types_str = (
                ", ".join(str(t) for t in s_types) if isinstance(s_types, list) else "Unknown"
            )
            print(f"  - [{s['id']}] {s['name']} (Types: {types_str})")

    if new_count - old_count == 0:
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

    final_output = {
        "meta": {"source": URL_DATA, "catch_rates": URL_RATES, "species": len(entries)},
        "species": entries,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=1)

    print(f"\nSuccessfully wrote {len(entries)} species to {OUT_PATH.name}")


if __name__ == "__main__":
    main()
