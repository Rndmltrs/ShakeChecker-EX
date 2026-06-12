"""Find the PokeMMO window and capture its client area (read-only).

Strictly passive: enumerates windows and grabs pixels via mss. Never sends
input, never touches the game process.
"""

from __future__ import annotations

import contextlib
import ctypes
from dataclasses import dataclass

import mss
import numpy as np
import win32gui

WINDOW_TITLE = "PokeMMO"


def set_dpi_awareness() -> None:
    """Must run at startup before any coordinate work (CLAUDE.md hard rule)."""
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE


@dataclass(frozen=True)
class ClientRect:
    left: int
    top: int
    width: int
    height: int


def find_pokemmo_hwnd() -> int | None:
    """First visible top-level window whose title starts with 'PokeMMO'."""
    found: list[int] = []

    def on_window(hwnd: int, _param: object) -> bool:
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd).startswith(WINDOW_TITLE):
            found.append(hwnd)
            return False  # stop enumeration
        return True

    # EnumWindows raises when the callback returns False to stop enumeration
    with contextlib.suppress(win32gui.error):
        win32gui.EnumWindows(on_window, None)
    return found[0] if found else None


def is_window_alive(hwnd: int) -> bool:
    return bool(win32gui.IsWindow(hwnd))


def get_client_rect(hwnd: int) -> ClientRect | None:
    """Client area of `hwnd` in screen coordinates, or None if not usable
    (window gone, minimized, or zero-sized)."""
    try:
        if win32gui.IsIconic(hwnd):
            return None
        left, top = win32gui.ClientToScreen(hwnd, (0, 0))
        _l, _t, right, bottom = win32gui.GetClientRect(hwnd)
    except win32gui.error:
        return None
    if right <= 0 or bottom <= 0:
        return None
    return ClientRect(left=left, top=top, width=right, height=bottom)


class WindowCapture:
    """Grabs BGR frames of a screen rectangle. One instance per thread (mss)."""

    def __init__(self) -> None:
        self._sct = mss.mss()

    def grab(self, rect: ClientRect) -> np.ndarray:
        shot = self._sct.grab(
            {"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height}
        )
        # mss delivers BGRA; drop alpha -> BGR, contiguous for OpenCV
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])

    def close(self) -> None:
        self._sct.close()
