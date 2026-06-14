"""Tests for the window-detection logic that does not need a live window.

The enumeration itself (win32 EnumWindows) is verified manually via
`python src/app.py --list-windows`; here we cover the title/area selection
that picks the real game window among candidates.
"""

from __future__ import annotations

import pytest

import window_capture as wc
from window_capture import WINDOW_TITLE, find_pokemmo_hwnd, fold_confusables, title_matches

# The PokeMMO client's homoglyph title: Cyrillic Р(U+0420) е(U+0435) М(U+041C)
# mixed with ASCII o, k, M, O -> looks like "PokeMMO".
HOMOGLYPH_TITLE = "РokеMМO"


def test_fold_confusables_maps_homoglyphs_to_ascii():
    assert fold_confusables(HOMOGLYPH_TITLE) == "PokeMMO"
    assert fold_confusables("PokeMMO") == "PokeMMO"  # ASCII unchanged


def test_title_matches_accepts_exact_ascii_and_homoglyphs():
    assert title_matches("PokeMMO")
    assert title_matches("PokeMMO ")  # trailing whitespace tolerated
    assert title_matches(HOMOGLYPH_TITLE)


def test_title_matches_rejects_non_game_windows():
    # Browser tabs that merely START with or contain "PokeMMO" must not match
    assert not title_matches("PokeMMO Help - Google Chrome")
    assert not title_matches("pokemmo infernape best build - Google Suche - Google Chrome")
    assert not title_matches("(17) ... - PokeMMO Stream Recap - YouTube - Google Chrome")
    assert not title_matches("Pokémon-Mod mit Fangwahrscheinlichkeit - Claude - Google Chrome")
    assert not title_matches("Visual Studio Code")


def install_fake_windows(
    monkeypatch: pytest.MonkeyPatch,
    windows: list[tuple[int, str]],
    rects: dict[int, wc.ClientRect | None],
) -> None:
    monkeypatch.setattr(wc, "iter_visible_windows", lambda: windows)
    monkeypatch.setattr(wc, "get_client_rect", lambda hwnd: rects.get(hwnd))


def test_no_match_returns_none(monkeypatch):
    install_fake_windows(monkeypatch, [(1, "Notepad"), (2, "Discord")], {})
    assert find_pokemmo_hwnd() is None


def test_single_match(monkeypatch):
    install_fake_windows(
        monkeypatch,
        [(1, "Notepad"), (2, f"{WINDOW_TITLE}")],
        {2: wc.ClientRect(0, 0, 1280, 720)},
    )
    assert find_pokemmo_hwnd() == 2


def test_finds_homoglyph_titled_window(monkeypatch):
    install_fake_windows(
        monkeypatch,
        [(1, "Visual Studio Code"), (2, HOMOGLYPH_TITLE)],
        {2: wc.ClientRect(1087, 38, 2352, 1401)},
    )
    assert find_pokemmo_hwnd() == 2


def test_prefers_largest_client_area(monkeypatch):
    # a zero-sized helper window with the same title prefix must not win
    install_fake_windows(
        monkeypatch,
        [(1, "PokeMMO"), (2, "PokeMMO Updater"), (3, "PokeMMO")],
        {
            1: wc.ClientRect(0, 0, 0, 0),
            2: wc.ClientRect(0, 0, 400, 120),
            3: wc.ClientRect(0, 0, 1920, 1080),
        },
    )
    assert find_pokemmo_hwnd() == 3


def test_match_without_client_rect_is_last_resort(monkeypatch):
    # minimized/unusable match (no rect) still beats no match at all
    install_fake_windows(monkeypatch, [(5, "PokeMMO")], {5: None})
    assert find_pokemmo_hwnd() == 5
