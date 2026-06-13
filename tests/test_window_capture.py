"""Tests for the window-detection logic that does not need a live window.

The enumeration itself (win32 EnumWindows) is verified manually via
`python src/app.py --list-windows`; here we cover the title/area selection
that picks the real game window among candidates.
"""

from __future__ import annotations

import pytest

import window_capture as wc
from window_capture import WINDOW_TITLE, find_pokemmo_hwnd


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
