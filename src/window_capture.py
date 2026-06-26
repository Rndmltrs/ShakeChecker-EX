"""Find the PokeMMO window and capture its client area (read-only).

Strictly passive: enumerates windows and grabs pixels. Never sends
input, never touches the game process.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np
import win32con
import win32gui
import win32ui

WINDOW_TITLE = "PokeMMO"

# DwmGetWindowAttribute: the VISIBLE window rectangle (what a window screenshot
# captures), excluding the invisible DWM resize borders that GetWindowRect adds.
_DWMWA_EXTENDED_FRAME_BOUNDS = 9

# The PokeMMO client presents a window title built from Cyrillic/Greek
# homoglyphs (observed: 'РokеMМO' with Cyrillic Р U+0420, е U+0435, М U+041C)
# that looks like "PokeMMO" but is not ASCII, so a naive title match fails.
# Fold the common confusable letters back to ASCII before comparing.
_CONFUSABLES = {
    # Cyrillic -> Latin
    "А": "A",
    "В": "B",
    "Е": "E",
    "Ѕ": "S",
    "І": "I",
    "Ј": "J",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "Х": "X",
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "к": "k",
    "ѕ": "s",
    "і": "i",
    "ј": "j",
    # Greek -> Latin
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
    "Ζ": "Z",
    "ο": "o",
    "ρ": "p",
    "τ": "t",
}
_FOLD = str.maketrans(_CONFUSABLES)


def fold_confusables(text: str) -> str:
    """Map common Cyrillic/Greek homoglyphs to their ASCII lookalikes."""
    return text.translate(_FOLD)


def title_matches(title: str) -> bool:
    """True only if `title` is exactly the PokeMMO game window title (homoglyph-
    folded), not a browser tab that merely starts with 'PokeMMO'."""
    return fold_confusables(title).strip().lower() == WINDOW_TITLE.lower()


def set_dpi_awareness() -> None:
    """Must run at startup before any coordinate work."""
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE


@dataclass(frozen=True)
class ClientRect:
    left: int
    top: int
    width: int
    height: int


def iter_visible_windows() -> list[tuple[int, str]]:
    """(hwnd, title) for every visible top-level window."""
    windows: list[tuple[int, str]] = []

    def on_window(hwnd: int, _param: object) -> bool:
        try:
            if win32gui.IsWindowVisible(hwnd):
                windows.append((hwnd, win32gui.GetWindowText(hwnd)))
        except win32gui.error:
            pass
        return True

    win32gui.EnumWindows(on_window, None)
    return windows


def find_pokemmo_hwnd() -> int | None:
    """Visible window whose (homoglyph-folded) title is exactly 'PokeMMO'."""
    best: int | None = None
    best_area = -1
    for hwnd, title in iter_visible_windows():
        if not title_matches(title):
            continue
        rect = get_client_rect(hwnd)
        area = rect.width * rect.height if rect else 0
        if area > best_area:
            best, best_area = hwnd, area
    return best


def is_window_alive(hwnd: int) -> bool:
    return bool(win32gui.IsWindow(hwnd))


def get_client_rect(hwnd: int) -> ClientRect | None:
    try:
        if win32gui.IsIconic(hwnd):
            return None

        # client top-left in screen coords
        left, top = win32gui.ClientToScreen(hwnd, (0, 0))

        # client size in client coords
        c_left, c_top, c_right, c_bottom = win32gui.GetClientRect(hwnd)
    except win32gui.error:
        return None

    width = c_right - c_left
    height = c_bottom - c_top

    if width <= 0 or height <= 0:
        return None

    return ClientRect(left=left, top=top, width=width, height=height)


def get_window_rect(hwnd: int) -> ClientRect | None:
    """Full visible window rectangle (incl. title bar) in screen coordinates."""
    try:
        if win32gui.IsIconic(hwnd):
            return None
        r = wintypes.RECT()
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(_DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(r),
            ctypes.sizeof(r),
        )
        if hr != 0:  # DWM unavailable -> plain window rect
            r.left, r.top, r.right, r.bottom = win32gui.GetWindowRect(hwnd)
    except (OSError, win32gui.error):
        return None
    width, height = r.right - r.left, r.bottom - r.top
    if width <= 0 or height <= 0:
        return None
    return ClientRect(left=r.left, top=r.top, width=width, height=height)


class WindowCapture:
    """Grabs BGR frames of a specific window via GDI BitBlt.

    Purely portable: no WinRT, no MSS, no borders, no cursor flicker.
    """

    def __init__(self, game_hwnd: int) -> None:
        self.hwnd = game_hwnd
        self._lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None

    def grab(self, rect: ClientRect) -> np.ndarray | None:
        """Capture the window area defined by rect and return a BGR frame."""
        if not is_window_alive(self.hwnd):
            return None

        left, top, width, height = rect.left, rect.top, rect.width, rect.height

        try:
            # Capture directly from the desktop screen surface. This perfectly bypasses
            # DWM invisible borders, GetWindowDC DPI bugs, and negative coordinate
            # wrap-arounds on multi-monitor setups.
            desktop_dc = win32gui.GetDC(0)
            mfc_dc = win32ui.CreateDCFromHandle(desktop_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            save_dc.BitBlt(
                (0, 0),
                (width, height),
                mfc_dc,
                (left, top),  # Direct absolute screen coordinates
                win32con.SRCCOPY,
            )
            bmpinfo = bitmap.GetInfo()
            bmpstr = bitmap.GetBitmapBits(True)

            img = np.frombuffer(bmpstr, dtype=np.uint8)
            img = img.reshape((bmpinfo["bmHeight"], bmpinfo["bmWidth"], 4))
            bgr = img[:, :, :3]

            win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()

            with self._lock:
                self._latest_frame = bgr

            # Explicitly release the desktop DC to prevent GDI leaks
            win32gui.ReleaseDC(0, desktop_dc)

            return bgr.copy()
        except Exception as e:
            logging.getLogger(__name__).warning(f"GDI capture error: {e}")
            return None

    def close(self) -> None:
        # Nothing persistent to close for GDI BitBlt
        pass
