"""Read battle text via OCR.

Two sources, two purposes:

- The chat log (bottom-left, stable window position) prints "Turn N started!" —
  the exact turn number when the chat is visible.
- The in-viewport text box (bottom of the centered viewport) shows the command
  menu (FIGHT/BAG/POKEMON/RUN) and the narration ("Gotcha! / X was caught!").
  One OCR of it drives the chat-INDEPENDENT turn counter (menu reappears each
  turn) and catch detection. It belongs to the current frame, whereas the chat
  log lags ~1s (so at the catch moment the chat still shows the PREVIOUS
  battle's catch line). The band also sits above the chat, so that stale line
  cannot leak in. See [battle_text] in calibration.toml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np
from rapidfuzz import fuzz

from battle_reader import BattleTextCalibration, ChatCalibration
from ocr_engine import run_ocr

# "Turn 2 started!" — tolerate OCR spacing/case noise.
_TURN = re.compile(r"turn\s*(\d{1,3})\s*start", re.IGNORECASE)
# Command-menu buttons; never appear in the chat log, so no stale-text collision.
_MENU_KEYWORDS = ("fight", "bag", "pokemon", "run")


@dataclass(frozen=True)
class BattleText:
    """What the in-viewport text box shows this frame."""

    menu_present: bool  # command menu up == waiting for player input (turn start)
    caught: bool  # capture banner ("Gotcha! / X was caught!")


def parse_turn_number(texts: list[str]) -> int | None:
    """Highest "Turn N started" number among OCR text lines, or None.

    NB: the catch is deliberately NOT read from the chat. The chat log lags the
    actual battle by ~1s, so at the moment a Pokemon is caught it still shows the
    PREVIOUS battle's catch line — read_battle_text reads the live in-viewport
    box instead."""
    best: int | None = None
    for line in texts:
        for m in _TURN.finditer(line):
            n = int(m.group(1))
            best = n if best is None else max(best, n)
    return best


def read_turn_number(frame_bgr: np.ndarray, cal: ChatCalibration) -> int | None:
    """Current turn number (1-based) from the chat, or None if not readable."""
    h, w = frame_bgr.shape[:2]
    crop = frame_bgr[int(h * cal.top) : int(h * cal.bottom), int(w * cal.left) : int(w * cal.right)]
    if crop.size == 0:
        return None
    up = cv2.resize(crop, None, fx=cal.upscale, fy=cal.upscale, interpolation=cv2.INTER_CUBIC)
    return parse_turn_number(run_ocr(up))


def _tokens(texts: list[str]) -> list[str]:
    out: list[str] = []
    for raw in texts:
        out.extend(t for t in re.split(r"[^A-Za-z]+", raw.lower()) if t)
    return out


def is_catch_banner(texts: list[str]) -> bool:
    """True if the OCR'd text shows a capture ("Gotcha! / X was caught!"). OCR
    mangles "Gotcha"->"Gotoha" and splits/drops "was", so we key on the
    surviving keywords rather than the exact phrase: a "caught" token, or a
    fuzzy "gotcha" match. "X fainted!" deliberately does NOT match."""
    for token in _tokens(texts):
        if "caught" in token:
            return True
        if fuzz.ratio(token, "gotcha") >= 75:  # "gotoha" ~= 83
            return True
    return False


def has_command_menu(texts: list[str], min_keywords: int) -> bool:
    """True if the OCR'd text is the command menu (FIGHT/BAG/POKEMON/RUN), i.e.
    the game is waiting for the player to choose an action — the start of a turn.
    The move submenu shows move names instead and reads no keywords."""
    toks = set(_tokens(texts))
    return sum(k in toks for k in _MENU_KEYWORDS) >= min_keywords


def read_battle_text(frame_bgr: np.ndarray, cal: BattleTextCalibration) -> BattleText:
    """OCR the in-viewport text box once; report the command-menu and catch
    state. See [battle_text] in calibration.toml for why this beats the chat."""
    h, w = frame_bgr.shape[:2]
    crop = frame_bgr[int(h * cal.top) : int(h * cal.bottom), int(w * cal.left) : int(w * cal.right)]
    if crop.size == 0:
        return BattleText(menu_present=False, caught=False)
    up = cv2.resize(crop, None, fx=cal.upscale, fy=cal.upscale, interpolation=cv2.INTER_CUBIC)
    texts = run_ocr(up)
    return BattleText(
        menu_present=has_command_menu(texts, cal.menu_keywords_min),
        caught=is_catch_banner(texts),
    )
