from __future__ import annotations

import pytest

from dex_panel import DexPanel, rarity_color_hex
from dex_session import LocationView
from dex_tracker import DexEntry
from game_time import Period

# --- pure helper ---


def test_rarity_colors_follow_the_scheme():
    assert rarity_color_hex("Common") == "#9d9d9d"
    assert rarity_color_hex("Very Common") == "#9d9d9d"  # falls back to grey
    assert rarity_color_hex("Uncommon") == "#ffffff"
    assert rarity_color_hex("Rare") == "#3fcf5f"
    assert rarity_color_hex("Very Rare") == "#4aa3ff"
    assert rarity_color_hex("Lure") == "#b86bff"
    assert rarity_color_hex("Special") == "#ffd633"
    assert rarity_color_hex("???") == "#9d9d9d"  # unknown -> grey


# --- widget smoke tests ---


@pytest.fixture(scope="module")
def qt_app():
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        pytest.skip("PyQt6 unavailable")
    yield QApplication.instance() or QApplication([])


def view(entries):
    return LocationView("ROUTE 110", "HOENN", Period.DAY, 1, entries)


def test_show_here_fills_rows_and_colors(qt_app):
    entries = [
        DexEntry(1, "Bulbasaur", (), "Lure", False),
        DexEntry(131, "Lapras", ("Water",), "Very Rare", False),
    ]
    p = DexPanel()
    p.show_here(view(entries))
    assert "2 needed" in p._subtitle.text()
    assert "Bulbasaur" in p._rows[0]["name"].text()
    assert "#b86bff" in p._rows[0]["name"].text()  # Lure -> purple
    assert "Water" in p._rows[1]["way"].text()
    assert "#4aa3ff" in p._rows[1]["name"].text()  # Very Rare -> blue
    assert p._rows[2]["w"].isVisibleTo(p) is False  # unused rows hidden


def test_overflow_shows_plus_count(qt_app):
    entries = [DexEntry(i, f"Mon{i}", (), "Common", False) for i in range(1, 9)]  # 8 uncaught
    p = DexPanel()
    p.show_here(view(entries))
    assert p._overflow.text() == "+3"
    assert p._overflow.isVisibleTo(p) is True


def test_caught_padding_marked_with_check(qt_app):
    entries = [
        DexEntry(1, "A", (), "Common", False),  # 1 uncaught
        DexEntry(131, "Lapras", ("Water",), "Very Rare", True),  # caught rare -> pads, ✓
    ]
    p = DexPanel()
    p.show_here(view(entries))
    assert "1 needed" in p._subtitle.text()
    assert "✓" in p._rows[1]["way"].text()


def test_all_caught_message(qt_app):
    entries = [DexEntry(1, "A", (), "Common", True)]  # caught, too common to pad
    p = DexPanel()
    p.show_here(view(entries))
    assert "0 needed" in p._subtitle.text()
    assert "all caught here" in p._rows[0]["name"].text()
