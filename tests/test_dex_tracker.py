from __future__ import annotations

from pathlib import Path

import pytest

from dex_tracker import EncounterData, MissingEntry, RegionResolver, compute_missing

ROOT = Path(__file__).parent.parent
ENCOUNTERS = ROOT / "src" / "data" / "encounters.json"
LEGENDARIES = ROOT / "src" / "data" / "legendaries.json"


def enc(id, name, method="Grass", periods=("MORNING", "DAY", "NIGHT"), seasons=(0, 1, 2, 3)):
    return {
        "id": id,
        "name": name,
        "method": method,
        "rarity": "Common",
        "min_level": 5,
        "max_level": 5,
        "periods": list(periods),
        "seasons": list(seasons),
    }


# --- compute_missing (pure) ---


def test_filters_by_period_and_season():
    encs = [
        enc(1, "Bulbasaur", periods=("NIGHT",)),
        enc(2, "Ivysaur", seasons=(1,)),
        enc(3, "Venusaur"),  # all times/seasons
    ]
    missing = compute_missing(encs, "DAY", 0, caught=set(), legendaries=set())
    assert [m.id for m in missing] == [3]  # only the all-times one is active now


def test_excludes_caught_and_legendaries():
    encs = [enc(1, "Bulbasaur"), enc(150, "Mewtwo"), enc(16, "Pidgey")]
    missing = compute_missing(encs, "DAY", 0, caught={1}, legendaries={150})
    assert [m.id for m in missing] == [16]


def test_dedupes_by_species_and_collects_methods_sorted_by_id():
    encs = [
        enc(16, "Pidgey", method="Grass"),
        enc(16, "Pidgey", method="Dark Grass"),
        enc(1, "Bulbasaur", method="Grass"),
    ]
    missing = compute_missing(encs, "DAY", 0, caught=set(), legendaries=set())
    assert [m.id for m in missing] == [1, 16]  # dex order
    pidgey = next(m for m in missing if m.id == 16)
    assert pidgey.methods == ("Dark Grass", "Grass")


def test_empty_when_all_caught():
    encs = [enc(1, "Bulbasaur"), enc(16, "Pidgey")]
    assert compute_missing(encs, "DAY", 0, caught={1, 16}, legendaries=set()) == []


# --- EncounterData against the real vendored file ---


@pytest.fixture(scope="module")
def data() -> EncounterData:
    return EncounterData.load(ENCOUNTERS, LEGENDARIES)


def test_real_data_loads():
    d = EncounterData.load(ENCOUNTERS, LEGENDARIES)
    assert d.location_name("KANTO_VIRIDIAN_FOREST") == "VIRIDIAN FOREST"


def test_match_exact_name(data):
    assert data.match_location("Viridian Forest") == "KANTO_VIRIDIAN_FOREST"


def test_match_tolerates_channel_suffix_and_case(data):
    assert data.match_location("ROCK TUNNEL Ch. 2") == "KANTO_ROCK_TUNNEL"


def test_match_tolerates_ocr_noise(data):
    # a stray trailing char like OCR sometimes adds
    assert data.match_location("Viridian Forestl") == "KANTO_VIRIDIAN_FOREST"


def test_ambiguous_route_needs_region_hint(data):
    # "Route 5" exists in multiple regions -> ambiguous without a hint
    assert data.match_location("Route 5") is None
    assert data.match_location("Route 5", region="Kanto") == "KANTO_ROUTE_5"


def test_unknown_location_returns_none(data):
    assert data.match_location("Nonexistent Place 999") is None


def test_route_number_must_match_exactly_not_fuzzily(data):
    # Johto has no Route 5; it must NOT fuzzy-collapse into "Route 35".
    assert data.match_location("Route 5", region="Johto") is None
    assert data.match_location("Route 35", region="Johto") == "JOHTO_ROUTE_35"


# --- region resolution (stateful) ---


def test_regions_for_name(data):
    assert data.regions_for_name("Viridian Forest") == {"KANTO"}
    assert data.regions_for_name("Route 5") == {"KANTO", "UNOVA"}  # ambiguous
    assert data.regions_for_name("Nowhere 999") == set()


def test_resolver_pins_region_from_unique_location(data):
    r = RegionResolver(data)
    # ambiguous name before any region is known -> unresolved
    assert r.resolve("Route 5") is None
    # a region-unique location pins Kanto
    assert r.resolve("Viridian Forest") == "KANTO_VIRIDIAN_FOREST"
    assert r.region == "KANTO"
    # now the ambiguous route resolves against the remembered region
    assert r.resolve("Route 5") == "KANTO_ROUTE_5"


def test_resolver_takes_over_region_on_switch(data):
    r = RegionResolver(data)
    r.resolve("Viridian Forest")  # Kanto
    assert r.region == "KANTO"
    # arriving at a Unova-unique place switches the region (the harbour-town case)
    assert r.resolve("Pinwheel Forest") == "UNOVA_PINWHEEL_FOREST"
    assert r.region == "UNOVA"
    # the same ambiguous "Route 5" now resolves to Unova, not Kanto
    assert r.resolve("Route 5") == "UNOVA_ROUTE_5"


def test_missing_here_excludes_legendaries_and_caught(data):
    key = "KANTO_VIRIDIAN_FOREST"
    full = data.missing_here(key, "DAY", 0, caught=set())
    assert all(isinstance(m, MissingEntry) for m in full)
    assert [m.id for m in full] == sorted(m.id for m in full)  # dex-sorted
    # catching the first removes exactly it
    first = full[0].id
    after = data.missing_here(key, "DAY", 0, caught={first})
    assert first not in {m.id for m in after}
    assert len(after) == len(full) - 1
