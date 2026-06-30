"""Unified battle lifecycle manager.

Replaces ``battle_controller.py`` + ``battle_detector.py`` + the inline
battle-glue in ``app_controller.py``.

Responsibilities
----------------
- Battle membership: wraps ``is_in_battle`` + ``debounce_battle`` to gate the
  ACTIVE / GAP / IDLE lifecycle.
- End-of-battle grace: calls ``battle_end_grace`` and tracks the brightness
  spike that fast-ends a wild battle when the dark UI disappears.
- Turn tracking: feeds ``debounce_menu`` + ``TurnTracker.observe_menu`` each
  frame; feeds chat OCR into ``apply_chat_turn`` for authoritative corrections.
- Species identification: manages the OCR thread-pool future and drives the
  internal state machine (_BattleState) that keeps the UI stable during
  identification and Pokémon swaps.
- UI output: assembles the ``BattleUpdate`` dataclass every frame.

What this module does NOT own
------------------------------
- Pixel operations  → battle_vision.BattleVision
- Turn math         → battle_logic.apply_chat_turn / TurnTracker
- HP smoothing      → HpSettler
- Status smoothing  → StatusSettler
- Catch probability → catch_calc
"""

from __future__ import annotations

import enum
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QRect

from battle.battle_context import BattleContext, BattleTimeline
from battle.battle_logic import (
    apply_chat_turn,
    battle_end_grace,
    debounce_battle,
    debounce_menu,
    is_in_battle,
)
from battle.battle_reader import BattleState, Calibration, Status
from battle.battle_vision import BattleScene
from battle.catch_calc import ball_probs, battle_context, chain_for, format_line
from battle.catch_chain import CatchChain
from battle.hp_settler import HpSettler
from battle.status_settler import StatusSettler
from battle.turn_tracker import TurnTracker
from core.game_time import current_game_minute, is_dusk_ball_night
from core.services import AppConfig, BattleServices, OcrServices
from dex.location_reader import is_cave_location

log = logging.getLogger("shakechecker")


# ---------------------------------------------------------------------------
# Internal FSM state (private to this module)
# ---------------------------------------------------------------------------


class _BattleState(enum.Enum):
    """Internal state machine for the species-identification lifecycle.

    Transitions are driven by named private methods on BattleManager. Each
    state has a clear, single responsibility so the per-frame logic in
    _update_single() reads as a state dispatch, not a flag soup.

    SCANNING
        The battle has just started (or a new Pokémon is incoming after a
        swap). Waiting for: (a) the trainer/wild classification to resolve,
        and (b) the first stable command menu to appear. Shows
        "Reading battle…" on the overlay.

    IDENTIFYING
        Classification is done and the menu is stable. An OCR future has been
        submitted. Waiting for the thread-pool result. Shows "Reading…" but
        with HP visible.

    TRACKING
        Species is locked (``ctx.species`` is set). Normal per-frame HP /
        status / turn loop. Name-banner pixel diffs are monitored here; if a
        diff is detected the state transitions to SWAPPING.

    SWAPPING
        A pixel diff in the name banner suggests the trainer switched to a new
        Pokémon. A new OCR future has been submitted. The OLD species is still
        shown on the UI (no blank flash). When the future resolves:
        - Different name → confirm swap, reset HP/status, → TRACKING.
        - Same name (false alarm from attack-animation noise) → no-op, → TRACKING.
    """

    SCANNING = "scanning"
    IDENTIFYING = "identifying"
    TRACKING = "tracking"
    SWAPPING = "swapping"


# ---------------------------------------------------------------------------
# Public interface types
# ---------------------------------------------------------------------------


@dataclass
class BattleInput:
    """Everything the Manager needs per frame, assembled by app_controller."""

    scene: BattleScene  # Semantic snapshot from BattleVision
    frame: Any  # Raw BGR numpy frame (for OCR submission)
    timer_active: bool  # Whether the timer ball is enabled
    rect: QRect  # Client-area rect (for overlay positioning)
    chat_turn: int | None  # Latest turn from async chat OCR, or None


@dataclass
class BattleUpdate:
    """Output produced by the Manager each frame for the UI and app controller."""

    caught_species_id: int | None  # Non-None if a new OT catch was detected
    log_line: str | None  # Line to emit to the console log
    is_multi: bool  # True while a horde is active (multi bars)
    panel_state: dict[str, Any] | None  # Arguments for BattlePanel.update()
    is_loading: bool = False  # True while identification is in progress


class BattleDetectorState(enum.Enum):
    IDLE = "idle"
    GAP = "gap"
    ACTIVE = "active"


# ---------------------------------------------------------------------------
# BattleManager
# ---------------------------------------------------------------------------


class BattleManager:
    """Single entry point for all battle logic.

    Instantiate once per app session. Call ``step()`` each frame while a
    battle may be in progress. Call outside of battles is safe (returns an
    IDLE detector state quickly).
    """

    def __init__(
        self,
        *,
        species_override: dict | None,
        status_override: str | None,
        cal: Calibration,
        balls: list[dict],
        status_rates: dict[str, float],
        pool: ThreadPoolExecutor,
        ocr: OcrServices,
        services: BattleServices,
        config: AppConfig,
    ) -> None:
        # ── Injected dependencies ──────────────────────────────────────────
        self.species_override = species_override
        self.status_override = status_override
        self.cal = cal
        self.balls = balls
        self.status_rates = status_rates
        self.pool = pool
        self.ocr = ocr
        self.config = config

        # ── Stateful services (retained across the session) ────────────────
        self.chat = ocr.chat_reader
        self.turns: TurnTracker = services.turns
        self.hp: HpSettler = services.hp
        self.status: StatusSettler = services.status
        self._chain: CatchChain = services.chain

        # ── Battle-lifetime context + timeline ────────────────────────────
        self.ctx = BattleContext()
        self.tl = BattleTimeline()

        # ── FSM state ─────────────────────────────────────────────────────
        self._state = _BattleState.SCANNING

        # ── OCR future ────────────────────────────────────────────────────
        self._name_future: Future[dict | None] | None = None

        # ── Menu debounce (raw, streak, stable) ───────────────────────────
        self._menu_raw: bool = False
        self._menu_streak: int = 0
        self._menu_stable: bool = False

        # ── Battle-membership debounce ─────────────────────────────────────
        self._battle_debounce: int = 0
        self._stable_in_battle: bool = False
        self._last_seen_battle: float = 0.0

        # ── Overlay-removal detection ──────────────────────────────────────
        # Tracks the brightness of the dark command panel while in battle so a
        # sudden spike (the dark UI disappearing → bright overworld) can fast-
        # end a wild battle without waiting for the full grace period.
        self._battle_overlay_brightness: float | None = None
        self._was_ui_present: bool = False

        # ── Misc session-level state ───────────────────────────────────────
        self.last_line: str = ""  # last console line (for dedup)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def step(self, inp: BattleInput) -> tuple[BattleDetectorState, BattleUpdate]:
        """Process one frame.  Returns (detector_state, update)."""
        scene = inp.scene
        now = scene.now

        # ── Step 1: Battle membership + lifecycle ──────────────────────────
        # is_in_battle uses the same signals the old BattleDetector used: HP
        # bars present, OR menu/action/catch banner (so the battle stays alive
        # during 2-turn moves where the bar disappears).
        if scene.battle_text is not None:
            is_active = is_in_battle(scene.state, scene.battle_text)
        else:
            is_active = scene.state in (BattleState.SINGLE, BattleState.MULTI)

        self._stable_in_battle, self._battle_debounce = debounce_battle(
            is_active, self._battle_debounce
        )
        raw_in_battle = self._stable_in_battle

        # ── Step 2: Overlay-removal fast-exit (wild battles only) ─────────
        # While in battle (or during the grace gap), track the UI brightness
        # baseline. If it spikes suddenly AND we know it's a wild battle
        # (is_trainer == False), the dark overlay has been removed → overworld
        # is back → end the battle immediately without waiting for the grace
        # period. For trainer battles we never use this heuristic because the
        # UI stays dark during Pokémon switches (the "learning a move" gap).
        in_battle_or_gap = raw_in_battle or (self._last_seen_battle > 0.0)
        if in_battle_or_gap:
            if scene.hud_present:
                self._was_ui_present = True

            # Continuously update the brightness baseline while the panel is up
            if raw_in_battle and scene.hud_present:
                self._battle_overlay_brightness = scene.ui_brightness

            # Check for a brightness spike → fast-end only on wild battles
            if self._battle_overlay_brightness is not None:
                baseline = self._battle_overlay_brightness
                if baseline >= 15.0:
                    delta = 10.0 if baseline < 50.0 else 20.0
                    if (
                        scene.ui_brightness > baseline + delta
                        and not scene.is_trainer
                        and not self.ctx.is_trainer  # also check the locked value
                    ):
                        self._last_seen_battle = 0.0
                        raw_in_battle = False
                        self._stable_in_battle = False
                        self._battle_debounce = 0
                        self._battle_overlay_brightness = None

        # ── Step 3: Compute grace period ──────────────────────────────────
        # Use the locked ctx.is_trainer (not the per-frame scene.is_trainer)
        # because the locked value is the authoritative classification for this
        # battle.
        grace = battle_end_grace(
            self.ctx.is_trainer,
            scene.hud_present,
            trainer_s=self.config.trainer_end_grace_s,
            anim_s=self.config.battle_anim_grace_s,
            normal_s=self.config.battle_end_grace_s,
        )

        # ── Step 4: Detector state ─────────────────────────────────────────
        if raw_in_battle:
            self._last_seen_battle = now
            det_state = BattleDetectorState.ACTIVE
        elif self._last_seen_battle > 0.0:
            since = now - self._last_seen_battle
            if since <= grace:
                det_state = BattleDetectorState.GAP
            else:
                self._last_seen_battle = 0.0
                self._was_ui_present = False
                self._battle_overlay_brightness = None
                det_state = BattleDetectorState.IDLE
        else:
            det_state = BattleDetectorState.IDLE

        # Build an empty update to return if we're not actively in battle
        empty_update = BattleUpdate(
            caught_species_id=None,
            log_line=None,
            is_multi=False,
            panel_state=None,
            is_loading=True,
        )

        if det_state != BattleDetectorState.ACTIVE:
            return det_state, empty_update

        # ── Step 5: Per-frame battle logic ─────────────────────────────────
        update = self._tick_battle(inp)
        return det_state, update

    def reset(self, now: float) -> None:
        """Reset all per-battle state. Called by app_controller on BattleStarted."""
        self.ctx = BattleContext(
            battle_start=now,
            down_guard_s=self.config.turn_down_guard_s,
            start_grace_s=self.config.battle_start_grace_s,
        )
        self.tl = BattleTimeline()
        self._state = _BattleState.SCANNING

        if self._name_future is not None:
            self._name_future.cancel()
            self._name_future = None

        self.turns.reset()
        self.hp.reset()
        self.status.reset()
        self.chat.reset()
        self.species_override = None
        self.status_override = None
        self._menu_raw = False
        self._menu_streak = 0
        self._menu_stable = False
        self.last_line = ""

    def force_refresh(self) -> None:
        """UI-triggered: discard cached species and re-identify from scratch."""
        self.ctx.species = None
        self.ctx.trainer_decided = False
        self.status_override = None
        self._state = _BattleState.SCANNING
        if self._name_future is not None:
            self._name_future.cancel()
            self._name_future = None
        self.hp.reset()
        self.status.reset()

    # -----------------------------------------------------------------------
    # Internal: per-frame battle tick
    # -----------------------------------------------------------------------

    def _tick_battle(self, inp: BattleInput) -> BattleUpdate:
        """Run all per-frame battle logic. Only called when det_state == ACTIVE."""
        scene = inp.scene
        now = scene.now

        update = BattleUpdate(
            caught_species_id=None,
            log_line=None,
            is_multi=False,
            panel_state=None,
            is_loading=(self._state in (_BattleState.SCANNING, _BattleState.IDENTIFYING)),
        )

        # ── Location (dusk-ball state) ────────────────────────────────────
        # Read once per battle from the location OCR passed through the scene.
        if not self.ctx.location_set and scene.location_text:
            self.ctx.location_set = True
            cave = is_cave_location(scene.location_text)
            night = is_dusk_ball_night(current_game_minute())
            self.ctx.dusk_active = cave or night
            bits = [b for b, on in (("cave", cave), ("night", night)) if on]
            note = f" ({'+'.join(bits)} → Dusk Ball boosted)" if bits else ""
            log.info("location: %s%s", scene.location_text, note)

        # ── Chat OCR → authoritative turn correction ──────────────────────
        # The chat reader is an async background reader; poll() returns the
        # latest turn if one has been read since the last poll, else None.
        # submit() fires a new OCR job at most every 1.5 s.
        chat_turn = inp.chat_turn
        if inp.timer_active and now - self.ctx.last_chat_submit >= 1.5:
            if scene.battle_text is not None:
                self.chat.submit(inp.frame)
            self.ctx.last_chat_submit = now

        if chat_turn is not None and chat_turn != self.ctx.last_chat_turn:
            self.ctx.last_chat_turn = chat_turn
            log.debug(
                "chat: Turn %d  (counter Turn %d)",
                chat_turn,
                self.turns.turns_completed + 1,
            )

        asleep = (
            scene.state is BattleState.SINGLE
            and bool(scene.bars)
            and scene.bars[0].status is Status.SLP
        )
        outcome = apply_chat_turn(
            self.turns,
            chat_turn,
            asleep=asleep,
            now=now,
            last_advance=self.ctx.last_advance,
            down_guard_s=self.ctx.down_guard_s,
            battle_start=self.ctx.battle_start,
            start_grace_s=self.ctx.start_grace_s,
        )
        if outcome in ("down", "up"):
            log.debug(
                "chat corrected %s → Turn %d",
                outcome.upper(),
                self.turns.turns_completed + 1,
            )

        # ── Menu debounce → TurnTracker ───────────────────────────────────
        # debounce_menu() filters out 1-frame menu flickers during horde/double
        # animations that would otherwise over-count turns.
        self._menu_raw, self._menu_streak, self._menu_stable = debounce_menu(
            scene.menu_present,
            self._menu_raw,
            self._menu_streak,
            self._menu_stable,
            threshold=self.config.menu_stable_frames,
        )
        before = self.turns.turns_completed
        self.turns.observe_menu(self._menu_stable, scene.action_present)
        if self.turns.turns_completed > before:
            self.ctx.last_advance = now
            log.debug("menu → Turn %d", self.turns.turns_completed + 1)

        # ── Trainer detection ──────────────────────────────────────────────
        # scene.is_trainer is already corrected for horde-remnants by Vision.
        # We apply a two-sided delay:
        #   → Positive (trainer confirmed): lock immediately when the menu appears, to avoid
        #     false positives from wild encounter slide-in animations.
        #   → Negative (no strip seen): wait for the menu to appear. This filters the
        #     transition animation where a fake HP bar at the name-banner row
        #     makes the strip check fail on the first 1–2 frames.
        if (
            not self.ctx.trainer_decided
            and scene.menu_present
            and scene.state is BattleState.SINGLE
        ):
            self._on_trainer_decided(is_trainer=scene.is_trainer)

        # ── Catch streak ──────────────────────────────────────────────────
        # bt.caught is the raw "Gotcha!" banner. Require two consecutive frames
        # to avoid false positives from the animation's first flash frame.
        if scene.caught_present and not self.ctx.caught_logged and self.ctx.species:
            update.log_line = f"caught {self.ctx.species['name']}!"
            self.ctx.caught_logged = True
            self._on_catch(self.ctx.species)
            if self.ctx.species.get("id"):
                update.caught_species_id = self.ctx.species["id"]

        # ── Dispatch by battle state ───────────────────────────────────────
        if scene.state is BattleState.SINGLE:
            self._update_single(scene, update, inp.frame)
        elif scene.state is BattleState.MULTI:
            update.is_multi = True
            update.is_loading = False
            if self.last_line != "multi":
                update.log_line = "multiple enemy bars (horde): waiting for one to remain"
                self.last_line = "multi"
            update.panel_state = {
                "dex_id": 0,
                "name": "Multi Battle",
                "catch_rate": None,
                "turn": self.turns.turns_completed + 1,
                "probs": {},
                "level": None,
                "status": None,
                "hp_pct": None,
                "alpha": False,
                "is_trainer": False,
                "ev_yield": {},
            }

        return update

    # -----------------------------------------------------------------------
    # Internal: per-frame single-battle logic
    # -----------------------------------------------------------------------

    def _update_single(self, scene: BattleScene, update: BattleUpdate, frame: Any) -> None:
        """Update the panel state for a confirmed SINGLE-enemy battle."""
        bar = scene.bars[0]

        hp_pct = self.hp.update(bar.hp_pct)
        status = self.status_override or self.status.update(bar.status.value)

        # ── Species override ───────────────────────────────────────────────
        if self.species_override is not None:
            self.ctx.species = self.species_override
            if self._state is _BattleState.SCANNING:
                self._state = _BattleState.TRACKING

        # ── Name-banner pixel diff (TRACKING only) ─────────────────────────
        # Vision already ran the diff and set scene.name_changed. We only act
        # on it in TRACKING state — in other states there is no stable banner
        # to compare against.
        elif self._state is _BattleState.TRACKING and scene.name_changed:
            self._on_name_changed(scene)

        # ── OCR pipeline ──────────────────────────────────────────────────
        # Submit a new OCR future when in IDENTIFYING. For SWAPPING, wait until
        # the menu is stable again to ensure the new name is fully rendered.
        if self._state in (_BattleState.IDENTIFYING, _BattleState.SWAPPING):
            self._drive_ocr(scene, bar, frame)

        # ── Begin Identification ───────────────────────────────────────────
        # Start OCR immediately to load the Pokémon's basic info into the panel,
        # even before the battle type is decided.
        if self._state is _BattleState.SCANNING and self.ctx.species is None:
            self._begin_identification()

        # ── OT caught-icon ─────────────────────────────────────────────────
        # Only check in wild battles (Vision already filters trainer=True).
        # Only fire once per battle to avoid repeated dex writes.
        if (
            not self.ctx.caught_icon_seen
            and self.ctx.species is not None
            and self.ctx.species.get("id")
            and scene.caught_icon_present
        ):
            self.ctx.caught_icon_seen = True
            update.caught_species_id = self.ctx.species["id"]

        # ── Build panel state ──────────────────────────────────────────────
        is_trainer_ui: bool | None = self.ctx.is_trainer if self.ctx.trainer_decided else None

        if self.ctx.is_trainer:
            enemy_types = tuple(self.ctx.species.get("types", [])) if self.ctx.species else ()
            update.panel_state = {
                "dex_id": self.ctx.species.get("id", 0) if self.ctx.species else 0,
                "name": self.ctx.species["name"] if self.ctx.species else "Trainer's Pokémon",
                "catch_rate": None,
                "turn": self.turns.turns_completed + 1,
                "probs": {},
                "level": self.ctx.species.get("level") if self.ctx.species else None,
                "status": status if status != "none" else None,
                "hp_pct": hp_pct,
                "alpha": False,
                "is_trainer": True,
                "enemy_types": enemy_types,
                "ev_yield": self.ctx.species.get("ev_yield", {}) if self.ctx.species else {},
            }
            turn_note = f"turn {self.turns.turns_completed + 1}"
            if self.turns.turns_asleep:
                turn_note += f", asleep {self.turns.turns_asleep}"
            line = f"[{turn_note}] Trainer's Pokémon HP {hp_pct:5.1f}% [{status}]"
        elif self.ctx.species is None:
            update.panel_state = {
                "dex_id": 0,
                "name": "Reading...",
                "catch_rate": None,
                "turn": self.turns.turns_completed + 1,
                "probs": {},
                "level": None,
                "status": status if status != "none" else None,
                "hp_pct": hp_pct,
                "alpha": False,
                "is_trainer": is_trainer_ui,
                "ev_yield": {},
            }
            line = f"{'?':12.12s} HP {hp_pct:5.1f}% [{status}]"
        else:
            sp = self.ctx.species
            turn_note = f"turn {self.turns.turns_completed + 1}"
            if self.turns.turns_asleep:
                turn_note += f", asleep {self.turns.turns_asleep}"
            ctx = battle_context(
                sp,
                turns_completed=self.turns.turns_completed,
                turns_asleep=self.turns.turns_asleep,
                enemy_asleep=status == "slp",
                dusk_active=self.ctx.dusk_active,
                repeat_chain=chain_for(self._chain, sp),
            )
            probs_list = ball_probs(
                hp_pct, sp["catch_rate"], self.status_rates[status], self.balls, ctx
            )
            line = f"[{turn_note}] " + format_line(sp["name"], hp_pct, status, probs_list)
            overlay_probs = {name: p for name, p in probs_list if p is not None}
            update.panel_state = {
                "dex_id": sp.get("id", -1),
                "name": sp["name"],
                "catch_rate": sp["catch_rate"],
                "turn": self.turns.turns_completed + 1,
                "probs": overlay_probs,
                "level": sp.get("level"),
                "status": status,
                "hp_pct": hp_pct,
                "alpha": bool(sp.get("alpha")),
                "is_trainer": is_trainer_ui,
                "enemy_types": tuple(sp.get("types", [])) if sp else (),
                "ev_yield": sp.get("ev_yield", {}),
            }

        if line != self.last_line:
            if update.log_line:
                log.info(update.log_line)
            update.log_line = line
            self.last_line = line

    # -----------------------------------------------------------------------
    # Internal: FSM transition methods
    # -----------------------------------------------------------------------

    def _on_trainer_decided(self, *, is_trainer: bool) -> None:
        """Trainer/wild classification finalised.

        Called once per battle, after either:
        - Vision confirmed a trainer strip (is_trainer=True), or
        - The menu has been stable for > 15 frames with no strip (is_trainer=False).

        Locking the classification here unblocks the SCANNING → IDENTIFYING
        transition so OCR can begin on a frame guaranteed to show a real HP bar
        (not a transition-animation artefact).
        """
        self.ctx.is_trainer = is_trainer
        self.ctx.trainer_decided = True
        log.info("battle type: %s", "trainer" if is_trainer else "wild")

    def _begin_identification(self) -> None:
        """Begin species identification.

        Transitions SCANNING → IDENTIFYING. _drive_ocr() will submit the first
        OCR future on the next frame.
        """
        self._state = _BattleState.IDENTIFYING
        # _drive_ocr() will submit the future on the next frame

    def _on_name_changed(self, scene: BattleScene) -> None:
        """Vision pixel diff exceeded threshold → possible Pokémon swap.

        Transitions TRACKING → SWAPPING. The current species stays on the UI
        during the swap to prevent a blank flash. A new OCR future is submitted
        and _on_ocr_result() will confirm or deny the swap when it resolves.
        """
        self._state = _BattleState.SWAPPING
        # Cancel any in-flight future from a previous swap verification
        if self._name_future is not None:
            self._name_future.cancel()
            self._name_future = None
        # _drive_ocr() will submit a new future on the next frame

    def _on_ocr_result(self, sp: dict | None) -> None:
        """OCR thread completed. Handle based on current FSM state.

        IDENTIFYING:
            Lock the species and transition to TRACKING.

        SWAPPING:
            Compare the new name to the cached species.
            - Different name → confirmed swap → update species, reset HP/status.
            - Same name (false alarm from attack animation noise) → no-op.
            Either way, transition back to TRACKING.
        """
        if self._state is _BattleState.IDENTIFYING:
            if sp is not None:
                self.ctx.species = sp
                rate_str = "??" if sp["catch_rate"] is None else sp["catch_rate"]
                log.info("identified: %s (catch rate %s)", sp["name"], rate_str)
                self._state = _BattleState.TRACKING
            # If sp is None (OCR failed) stay in IDENTIFYING to retry next frame

        elif self._state is _BattleState.SWAPPING and sp is not None:
            current_name = self.ctx.species.get("name") if self.ctx.species else None
            if sp["name"] != current_name:
                log.info("confirmed swap: %s → %s", current_name, sp["name"])
                self.ctx.species = sp
                self.hp.reset()
                self.status.reset()
            else:
                log.debug(
                    "swap verification: same name (%s) — attack-animation noise",
                    sp["name"],
                )
                if self._menu_stable:
                    self._state = _BattleState.TRACKING

    def _drive_ocr(self, scene: BattleScene, bar: Any, frame: Any) -> None:
        """Submit or poll the OCR future when in IDENTIFYING or SWAPPING.

        Submits a new future if none is in flight. When the future completes,
        calls _on_ocr_result() to handle the result and drive the FSM.

        Also handles the level-only refinement: if a species is cached but its
        level is unknown, a background re-read can fill it in without clearing
        the species.
        """
        # Level refinement in TRACKING (carried over from old controller logic):
        # if species is known but level is still None, submit an OCR re-read.
        if (
            self._state is _BattleState.TRACKING
            and self.ctx.species is not None
            and self.ctx.species.get("level") is None
        ):
            if self._name_future is None and self.ocr.name_reader is not None:
                self._name_future = self.pool.submit(self.ocr.name_reader.read, frame, bar)
            elif self._name_future is not None and self._name_future.done():
                sp = self._name_future.result()
                self._name_future = None
                if (
                    sp is not None
                    and sp.get("level") is not None
                    and self.ctx.species is not None
                    and sp["name"] == self.ctx.species.get("name")
                ):
                    self.ctx.species["level"] = sp["level"]
                    log.info("identified level: %d", sp["level"])
            return

        # Normal OCR submission for IDENTIFYING / SWAPPING
        if self._name_future is None and self.ocr.name_reader is not None:
            if frame is not None:
                # frame copy is made here so the vision thread doesn't race
                self._name_future = self.pool.submit(self.ocr.name_reader.read, frame, bar)
        elif self._name_future is not None and self._name_future.done():
            sp = self._name_future.result()
            self._name_future = None
            self._on_ocr_result(sp)

    # -----------------------------------------------------------------------
    # Internal: catch helper
    # -----------------------------------------------------------------------

    def _on_catch(self, species: dict) -> None:
        sid = species.get("id")
        if sid is None:
            return
        length = self._chain.record_catch(sid)
        log.debug("repeat chain: %s x%d", species.get("name"), length)
