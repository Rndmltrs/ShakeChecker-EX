import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_PATH = DATA / "location_index.json"
URL_DATA = (
    "https://raw.githubusercontent.com/PokeMMO-Tools/pokemmo-hub/main/src/data/pokemmo/monster.json"
)


def fetch_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    print("Fetching monster.json from PokeMMO-Hub...")
    try:
        raw_data = fetch_json(URL_DATA)
    except urllib.error.URLError as e:
        print(f"Error fetching data: {e}", file=sys.stderr)
        sys.exit(1)

    data_list = raw_data.values() if isinstance(raw_data, dict) else raw_data

    # Structure: locations["Region::Location"] = [encounters...]
    locations_dict = defaultdict(list)

    encounter_count = 0

    for entry in data_list:
        if not isinstance(entry, dict):
            continue

        pid = entry.get("id")
        name = entry.get("name")
        locations = entry.get("locations", [])

        if not pid or not name:
            continue

        for loc in locations:
            region = loc.get("region_name", "Unknown")
            raw_location = loc.get("location", "Unknown")

            key = f"{region}::{raw_location}"

            locations_dict[key].append(
                {
                    "id": pid,
                    "name": name,
                    "type": loc.get("type", "Unknown"),
                    "rarity": loc.get("rarity", "Unknown"),
                    "min_level": loc.get("min_level"),
                    "max_level": loc.get("max_level"),
                }
            )
            encounter_count += 1

    # Load old data for comparison
    old_locations_count = 0
    old_encounters_count = 0
    if OUT_PATH.exists():
        try:
            with open(OUT_PATH, encoding="utf-8") as f:
                old_data = json.load(f)
                old_locations_count = len(old_data)
                old_encounters_count = sum(len(v) for v in old_data.values())
        except Exception:
            pass

    # Sort keys alphabetically, and encounters inside
    sorted_output = {}
    for key in sorted(locations_dict.keys()):
        # Sort encounters by id, then type, then rarity
        sorted_encounters = sorted(
            locations_dict[key], key=lambda x: (x["id"], x["type"], x["rarity"])
        )
        sorted_output[key] = sorted_encounters

    new_locations_count = len(sorted_output)
    print(f"\nLocal data:  {old_locations_count} locations, {old_encounters_count} encounters")
    print(f"New data:    {new_locations_count} locations, {encounter_count} encounters")

    loc_diff = new_locations_count - old_locations_count
    enc_diff = encounter_count - old_encounters_count
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

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted_output, f, ensure_ascii=False, indent=1)

    print(f"Successfully wrote data to {OUT_PATH.name}")


if __name__ == "__main__":
    main()
