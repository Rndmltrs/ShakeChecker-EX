import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    import sys

    sys.path.insert(0, str(root / "src"))
    from core.paths import SPECIES_INDEX_PATH as new_path

    old_path = root / "data" / "species_index_old.json"

    if not old_path.exists():
        print(f"Error: {old_path.name} not found.")
        return
    if not new_path.exists():
        print(f"Error: {new_path.name} not found.")
        return

    with open(old_path, encoding="utf-8") as f:
        r = json.load(f)
        species_list = r.get("species", r) if isinstance(r, dict) else r
        old_data = {item["id"]: item for item in species_list}

    with open(new_path, encoding="utf-8") as f:
        r = json.load(f)
        species_list = r.get("species", r) if isinstance(r, dict) else r
        new_data = {item["id"]: item for item in species_list}

    added = []
    removed = []
    modified = []

    for pid, new_item in new_data.items():
        if pid not in old_data:
            added.append(new_item)
        else:
            old_item = old_data[pid]
            diffs = []
            for k in ["name", "types", "catch_rate", "obtainable"]:
                if old_item.get(k) != new_item.get(k):
                    diffs.append(f"{k}: {old_item.get(k)} -> {new_item.get(k)}")
            if diffs:
                modified.append((pid, new_item["name"], diffs))

    for pid, old_item in old_data.items():
        if pid not in new_data:
            removed.append(old_item)

    print("--- DIFF SUMMARY ---")
    print(f"Added: {len(added)}")
    print(f"Removed: {len(removed)}")
    print(f"Modified: {len(modified)}\n")

    if modified:
        print("MODIFICATIONS:")
        for pid, name, diffs in modified:
            print(f"  [{pid}] {name}:")
            for d in diffs:
                print(f"    - {d}")

    if added:
        print("\nADDED:")
        for a in added:
            print(f"  [{a['id']}] {a['name']}")

    if removed:
        print("\nREMOVED:")
        for r in removed:
            print(f"  [{r['id']}] {r['name']}")


if __name__ == "__main__":
    main()
