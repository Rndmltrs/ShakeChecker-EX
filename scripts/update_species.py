"""Parse the PokeMMO-Hub pokemon-data.json dump into ShakeChecker's normalized species_core.json."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_PATH = DATA / "species_core.json"
REMOTE_URL = (
    "https://raw.githubusercontent.com/PokeMMOZone/PokeMMO-Data/main/data/pokemon-data.json"
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


def main() -> None:
    print("Fetching latest pokemon-data.json from PokeMMOZone...")
    try:
        req = urllib.request.Request(REMOTE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"Error fetching data: {e}", file=sys.stderr)
        sys.exit(1)

    entries = []
    for key, data in raw.items():
        pid = data.get("id")
        if not pid:
            continue

        # Extract properly capitalized name if available, otherwise fallback
        name = data.get("name_translations", {}).get("en", {}).get("name")
        if not name:
            name = data.get("name", key).title()

        name = name.replace("’", "'")

        types = [t.upper() for t in data.get("types", [])]
        catch_rate = data.get("capture_rate")
        obtainable = data.get("obtainable", False)

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
            }
        )

    # Read the old data first to preserve custom PokeMMO IDs (e.g., event bosses)
    old_ids = set()
    old_count = 0
    if OUT_PATH.exists():
        try:
            with open(OUT_PATH, encoding="utf-8") as f:
                old_data = json.load(f)
                old_count = len(old_data)
                old_ids = {e["id"] for e in old_data if "id" in e}

                # Merge back any old species that don't exist in the new dataset
                new_ids = {e["id"] for e in entries}
                for old_entry in old_data:
                    if old_entry["id"] not in new_ids:
                        entries.append(old_entry)
        except Exception:
            pass

    # Deduplicate types to ensure consistency (e.g. single ['FIRE'] instead of ['FIRE', 'FIRE'])
    for entry in entries:
        entry["types"] = list(dict.fromkeys(entry["types"]))

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
            print(f"  - [{s['id']}] {s['name']} (Types: {', '.join(s['types'])})")

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

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)

    print(f"\nSuccessfully wrote {len(entries)} species to {OUT_PATH.name}")


if __name__ == "__main__":
    main()
