"""Download and vendor the overlay sprites from the PokeAPI sprites repo.

Pokemon: animated Gen-5 (Black/White) GIFs -- the same PkParaiso-origin set the
community callouts use -- keyed by National Dex id. Animated GIFs only exist up
to id 649 (end of Gen 5); for later ids we fall back to a static sprite so the
overlay never has a blank slot. Balls: the item icons.

Idempotent: existing files are skipped, so re-runs only fetch what is missing.
These are Nintendo/Game-Freak fan assets, vendored for local use only.

A handful of ids (1026-1052) have no sprite anywhere: they are PokeMMO's own
event-custom creatures (Robosanta, the "Elfbot" line, Pumpaladin, a DEBUG
entry), all obtainable=false, so they never appear as a normal wild encounter.
The overlay sprite loader shows a placeholder for them.

    python scripts/fetch_sprites.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SPRITES = DATA / "sprites"
POKEMON_DIR = SPRITES / "pokemon"
ITEMS_DIR = SPRITES / "items"

RAW = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites"
# Pokemon sprite fallback chain (first hit wins); .gif is animated, .png static.
POKEMON_SOURCES = (
    ("gif", f"{RAW}/pokemon/versions/generation-v/black-white/animated/{{id}}.gif"),
    ("png", f"{RAW}/pokemon/versions/generation-v/black-white/{{id}}.png"),
    ("png", f"{RAW}/pokemon/{{id}}.png"),
)
ITEM_URL = f"{RAW}/items/{{slug}}.png"


def ball_slug(name: str) -> str:
    """'Poké Ball' -> 'poke-ball' (PokeAPI item filename)."""
    return name.lower().replace("é", "e").replace(" ", "-")


def fetch(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def save_pokemon(dex_id: int) -> str:
    """Fetch one Pokemon sprite via the fallback chain. Returns the outcome tag."""
    existing = list(POKEMON_DIR.glob(f"{dex_id}.*"))
    if existing:
        return "skip"
    for kind, template in POKEMON_SOURCES:
        data = fetch(template.format(id=dex_id))
        if data:
            (POKEMON_DIR / f"{dex_id}.{kind}").write_bytes(data)
            return "gif" if kind == "gif" else "static"
    return "missing"


def save_ball(name: str) -> bool:
    slug = ball_slug(name)
    out = ITEMS_DIR / f"{slug}.png"
    if out.exists():
        return True
    data = fetch(ITEM_URL.format(slug=slug))
    if data:
        out.write_bytes(data)
        return True
    return False


def main() -> None:
    POKEMON_DIR.mkdir(parents=True, exist_ok=True)
    ITEMS_DIR.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(ROOT / "src"))
    from core.paths import SPECIES_INDEX_PATH

    raw_species = json.loads(SPECIES_INDEX_PATH.read_text("utf-8"))
    species = (
        raw_species.get("species", raw_species) if isinstance(raw_species, dict) else raw_species
    )
    balls = json.loads((DATA / "balls.json").read_text("utf-8"))["balls"]

    print(f"Balls ({len(balls)}):")
    for b in balls:
        ok = save_ball(b["name"])
        print(f"  {'ok ' if ok else 'XX '} {b['name']} -> {ball_slug(b['name'])}.png")

    counts = {"gif": 0, "static": 0, "skip": 0, "missing": 0}
    missing: list[int] = []
    print(f"\nPokemon ({len(species)}):")
    for i, sp in enumerate(species, 1):
        tag = save_pokemon(sp["id"])
        counts[tag] += 1
        if tag == "missing":
            missing.append(sp["id"])
        if i % 50 == 0 or i == len(species):
            print(f"  {i}/{len(species)}  {counts}")
        if tag in ("gif", "static"):
            time.sleep(0.05)  # be polite to the CDN

    print(f"\nDone. {counts}")
    if missing:
        print(f"No sprite for {len(missing)} ids: {missing}", file=sys.stderr)


if __name__ == "__main__":
    main()
