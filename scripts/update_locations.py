import contextlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from core.paths import ENCOUNTER_INDEX_PATH as OUT_PATH  # noqa: E402

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

    locations_dict = {}

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
            region = loc.get("region_name", "Unknown").upper()
            raw_location = loc.get("location", "Unknown")

            base_name = raw_location
            periods = []
            seasons = []

            if "(" in raw_location and ")" in raw_location:
                base_name = raw_location[: raw_location.rfind("(")].strip()
                conditions_str = raw_location[raw_location.rfind("(") + 1 : raw_location.rfind(")")]
                conds = [c.strip().upper() for c in conditions_str.split("/")]

                for c in conds:
                    if c in ["MORNING", "DAY", "NIGHT"]:
                        periods.append(c)
                    elif c.startswith("SEASON"):
                        with contextlib.suppress(ValueError):
                            seasons.append(int(c.replace("SEASON", "")))

            if not periods:
                periods = ["MORNING", "DAY", "NIGHT"]
            if not seasons:
                seasons = [0, 1, 2, 3]

            base_name_upper = base_name.upper()
            key = f"{region}_{base_name_upper.replace(' ', '_').replace('-', '_')}"
            key = "".join(c for c in key if c.isalnum() or c == "_").replace("__", "_")

            if key not in locations_dict:
                locations_dict[key] = {"name": base_name_upper, "region": region, "encounters": []}

            locations_dict[key]["encounters"].append(
                {
                    "id": pid,
                    "name": name,
                    "method": loc.get("type", "Unknown"),
                    "rarity": loc.get("rarity", "Unknown"),
                    "min_level": loc.get("min_level"),
                    "max_level": loc.get("max_level"),
                    "periods": periods,
                    "seasons": seasons,
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
                if "locations" in old_data:
                    old_locations_count = len(old_data["locations"])
                    old_encounters_count = sum(
                        len(v["encounters"]) for v in old_data["locations"].values()
                    )
                else:
                    old_locations_count = len(old_data)
                    old_encounters_count = sum(len(v) for v in old_data.values())
        except Exception:
            pass

    # Sort keys alphabetically, and encounters inside
    sorted_output = {}
    for key in sorted(locations_dict.keys()):
        loc_data = locations_dict[key]
        sorted_encounters = sorted(
            loc_data["encounters"], key=lambda x: (x["id"], x["method"], x["rarity"])
        )
        sorted_output[key] = {
            "name": loc_data["name"],
            "region": loc_data["region"],
            "encounters": sorted_encounters,
        }

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

    final_output = {
        "meta": {
            "source": URL_DATA,
            "note": "PokeMMO-specific spawns; time/season parsed from the source 'time' field.",
            "locations": new_locations_count,
            "encounters": encounter_count,
        },
        "locations": sorted_output,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=1)

    print(f"Successfully wrote data to {OUT_PATH.name}")


if __name__ == "__main__":
    main()
