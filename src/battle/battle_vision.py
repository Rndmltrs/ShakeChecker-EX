"""Seal all pixel-level operations behind a single semantic snapshot.

The Vision layer is the ONLY code that touches raw numpy frames after capture.
Everything above this layer receives a ``BattleScene`` — a plain dataclass of
booleans and scalars — and never imports cv2 or numpy directly.

What happens here, each frame:
- HP bars are read (delegated to ``battle_reader``).
- Horde-remnant logic is applied so ``is_trainer`` is already correct.
- ``is_trainer_battle()`` is run against the lone bar (if applicable).
- The name-banner region is pixel-diffed to detect Pokémon swaps.
- The caught-icon region is checked for the OT Poké Ball icon.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from battle.battle_logic import is_horde_remnant
from battle.battle_reader import (
    BarReading,
    BattleReading,
    BattleState,
    BattleText,
    Calibration,
    is_trainer_battle,
    read_caught_icon,
)

log = logging.getLogger("shakechecker")

# Pixel-diff threshold: mean absolute difference in a half-res greyscale crop of
# the name-banner region that is considered a *real* change (i.e. a different
# Pokémon) rather than compression noise or an attack animation.
_NAME_DIFF_THRESHOLD = 2.0


class BattleScene:
    """A single, semantic snapshot of the battle state for one frame.

    Produced by ``BattleVision.step()`` and consumed by ``BattleManager``.
    All fields are plain Python scalars/booleans — no numpy arrays.
    """

    __slots__ = (
        # ── Battle membership ──────────────────────────────────────────────
        "state",  # BattleState: SINGLE / MULTI / NO_BATTLE
        "bars",  # tuple[BarReading, ...]: HP bars this frame
        # ── Raw UI signals ─────────────────────────────────────────────────
        "menu_present",  # bool: command menu (FIGHT/BAG/…) is up
        "action_present",  # bool: committed-action narration visible
        "caught_present",  # bool: "Gotcha!" catch banner visible
        "hud_present",  # bool: dark command panel (battle overlay) is up
        "ui_brightness",  # float: mean brightness of the HUD region
        # ── Trainer / horde classification ────────────────────────────────
        "is_trainer",  # bool: True only if trainer strip confirmed *and*
        #       not a horde-remnant bar
        "horde_flag",  # bool: a horde layout was seen this battle
        # ── Change signals ─────────────────────────────────────────────────
        "name_changed",  # bool: pixel diff in name-banner region
        "caught_icon_present",  # bool: OT Poké Ball icon next to name
        # ── Pass-throughs ──────────────────────────────────────────────────
        "battle_text",  # BattleText | None: raw text signals (for is_in_battle)
        "location_text",  # str | None
        "now",  # float: monotonic timestamp
    )

    def __init__(
        self,
        *,
        state: BattleState,
        bars: tuple[BarReading, ...],
        menu_present: bool,
        action_present: bool,
        caught_present: bool,
        hud_present: bool,
        ui_brightness: float,
        is_trainer: bool,
        horde_flag: bool,
        name_changed: bool,
        caught_icon_present: bool,
        battle_text: BattleText | None,
        location_text: str | None,
        now: float,
    ) -> None:
        self.state = state
        self.bars = bars
        self.menu_present = menu_present
        self.action_present = action_present
        self.caught_present = caught_present
        self.hud_present = hud_present
        self.ui_brightness = ui_brightness
        self.is_trainer = is_trainer
        self.horde_flag = horde_flag
        self.name_changed = name_changed
        self.caught_icon_present = caught_icon_present
        self.battle_text = battle_text
        self.location_text = location_text
        self.now = now


class BattleVision:
    """Per-frame pixel-to-semantics converter.

    Carries the minimal per-battle cross-frame state that belongs in the
    vision layer: the horde flag and the last name-banner crop for diffing.
    Everything else is stateless (called with the raw frame + calibration).
    """

    def __init__(self) -> None:
        # Whether a horde layout was seen at any point this battle. Needed by
        # is_horde_remnant() to suppress false trainer detections when a horde
        # narrows to one bar.
        self._was_horde: bool = False

        # Half-resolution greyscale crop of the name-banner region from the
        # previous frame. Used for pixel-diff swap detection.
        self._last_name_crop: np.ndarray | None = None

    def reset(self) -> None:
        """Call at the start of each battle to clear cross-frame state."""
        self._was_horde = False
        self._last_name_crop = None

    def step(
        self,
        frame: np.ndarray,
        reading: BattleReading | None,
        bt: BattleText | None,
        enemy_count: int,
        cal: Calibration,
        hud_present: bool,
        ui_brightness: float,
        location_text: str | None,
        now: float,
        known_species: dict | None = None,
    ) -> BattleScene:
        """Produce a ``BattleScene`` from one raw captured frame.

        Args:
            frame: Full BGR frame from the capture.
            reading: Raw HP-bar reading from ``VisionController`` (may be None
                     if vision was skipped this tick).
            bt: Raw battle-text reading (may be None).
            enemy_count: Number of distinct enemy sprites seen this frame.
            cal: Calibration constants.
            hud_present: Whether the dark command panel is visible.
            ui_brightness: Mean brightness of the HUD region.
            location_text: Last resolved location string (may be None).
            now: Monotonic timestamp for this frame.
            known_species: The currently cached species dict (from the Manager).
                           Used to gate name-diff checking — we only diff when
                           a species is already locked, to avoid false positives
                           during the initial identification phase.
        """
        if reading is None:
            # Vision was skipped (dex-mode throttle or no window). Return a
            # minimal scene so the Manager can still run the grace-period timer.
            return BattleScene(
                state=BattleState.NO_BATTLE,
                bars=(),
                menu_present=bt.menu_present if bt is not None else False,
                action_present=bt.action if bt is not None else False,
                caught_present=bt.caught if bt is not None else False,
                hud_present=hud_present,
                ui_brightness=ui_brightness,
                is_trainer=False,
                horde_flag=self._was_horde,
                name_changed=False,
                caught_icon_present=False,
                battle_text=bt,
                location_text=location_text,
                now=now,
            )

        # ── Horde tracking ────────────────────────────────────────────────
        # Update the cross-frame flag if a horde layout is confirmed this tick.
        if reading.is_horde or enemy_count > 1:
            self._was_horde = True

        bars = reading.bars

        # ── Trainer / horde-remnant classification ────────────────────────
        # A lone bar that is actually a horde-remnant MUST NOT trigger trainer
        # detection: the fainted horde members below it look like party icons.
        # is_horde_remnant() catches both conditions (saw a horde earlier, or
        # the bar is right of the canonical single-enemy x-slot).
        is_trainer_result = False
        if reading.state is BattleState.SINGLE and bars:
            bar = bars[0]
            x_frac = bar.x / frame.shape[1]
            if not is_horde_remnant(self._was_horde, x_frac, cal.hp_bar.remnant_x_frac):
                is_trainer_result = is_trainer_battle(frame, bar, cal.trainer)

        # ── Name-banner pixel diff ────────────────────────────────────────
        # Only diff when we have a locked species — during Identifying there is
        # no stable banner to compare against. The diff is done on a half-res
        # greyscale crop to stay fast and resolution-independent.
        name_changed = False
        if reading.state is BattleState.SINGLE and bars and known_species is not None:
            bar = bars[0]
            c = cal.name
            h, w = frame.shape[:2]
            y0, y1 = bar.y + c.dy0, bar.y + c.dy1
            x0, x1 = bar.x + c.dx0, bar.x + c.dx1
            if 0 <= y0 < y1 <= h and 0 <= x0 < x1 <= w:
                crop = frame[y0:y1, x0:x1]
                if crop.size > 0:
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    small = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
                    if (
                        self._last_name_crop is not None
                        and self._last_name_crop.shape == small.shape
                    ):
                        diff = cv2.absdiff(small, self._last_name_crop)
                        if np.mean(diff) > _NAME_DIFF_THRESHOLD:
                            log.debug(
                                "name-banner pixel diff %.1f > %.1f — possible swap",
                                np.mean(diff),
                                _NAME_DIFF_THRESHOLD,
                            )
                            name_changed = True
                    self._last_name_crop = small

        # ── OT caught-icon check ──────────────────────────────────────────
        # Only relevant in wild battles (trainers don't show the OT icon).
        caught_icon_present = False
        if reading.state is BattleState.SINGLE and bars and not is_trainer_result:
            caught_icon_present = read_caught_icon(frame, bars[0], cal.caught_icon)

        return BattleScene(
            state=reading.state,
            bars=bars,
            menu_present=bt.menu_present if bt is not None else False,
            action_present=bt.action if bt is not None else False,
            caught_present=bt.caught if bt is not None else False,
            hud_present=hud_present,
            ui_brightness=ui_brightness,
            is_trainer=is_trainer_result,
            horde_flag=self._was_horde,
            name_changed=name_changed,
            caught_icon_present=caught_icon_present,
            battle_text=bt,
            location_text=location_text,
            now=now,
        )
