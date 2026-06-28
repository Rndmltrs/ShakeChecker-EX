from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import numpy as np
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QWindow

from battle.battle_logic import battle_end_grace, debounce_battle, is_in_battle
from battle.battle_reader import BattleState, Calibration, Status, is_battle_ui_present, read_battle
from battle.battle_controller import BattleController, BattleFrame

from core.account_store import AccountConfig

from core.app_state import AppState
from core import paths
from core.game_time import current_game_minute, is_dusk_ball_night
from core.settings_store import Settings
from dex.dex_controller import DexController, DexFrame
from core.window_capture import WindowCapture, find_pokemmo_hwnd, get_client_rect, get_window_rect, is_window_alive

from dex.dex_session import DexSession
from dex.dex_structures import LocationView

from ui.battle_panel import BattlePanel
from ui.dex_panel import DexPanel
from ui.ui_overlay import scale_for_window
from core.settings_controller import SettingsController, SettingsUpdate
from core.vision_controller import VisionController
from core.services import OcrServices, AppConfig

log = logging.getLogger("shakechecker")

class AppController:
    """One poll step per QTimer tick: capture -> read -> update overlay + console.

    Driven by a QTimer (not a blocking while-loop) so the Qt event loop keeps
    running between steps and the overlay's animated sprite plays. State that the
    old loop kept in locals lives on the instance. The console output is retained
    as a debug log alongside the overlay.
    """

    def __init__(
        self,
        *,
        pool: ThreadPoolExecutor,
        loc_pool: ThreadPoolExecutor,
        ocr: OcrServices,
        capture: WindowCapture,
        battle_panel: BattlePanel,
        settings_controller: SettingsController,
        battle_controller: BattleController,
        dex_controller: DexController,
        vision_controller: VisionController,
        config: AppConfig,
        species_override: dict | None,
        status_override: str | None,
        cal: Calibration,
        dex: DexSession | None = None,
        dex_panel: DexPanel | None = None,
    ) -> None:
        self.species_override = species_override
        self.status_override = status_override
        self.cal = cal
        self.battle_panel = battle_panel
        self.dex = dex  # None if the dex data couldn't be loaded
        self.dex_panel = dex_panel  # overworld "missing here" overlay
        self.settings = settings_controller.settings
        self.capture = capture
        
        self.pool = pool
        self.loc_pool = loc_pool
        self.ocr = ocr
        self.config = config

        self.state = AppState.WAITING
        self.hwnd: int | None = None
        self.last_seen_battle = 0.0
        
        self.battle_controller = battle_controller
        self.dex_controller = dex_controller
        self.mode_override: str = "auto" if self.settings.auto_switch else "dex"
        self.settings_controller = settings_controller
        
        self.battle_panel.set_hidden_names(self.settings_controller.hidden_ball_names())

        self.vision_controller = vision_controller

        if self.dex_panel is not None:
            self.dex_panel.on_mode_toggle = self._on_mode_toggle
            self.dex_panel.on_settings_click = lambda anchor: self.settings_controller.show(
                mode="dex", anchor_pos=anchor
            )

        self.battle_panel.on_settings_click = lambda anchor: self.settings_controller.show(
            mode="battle", anchor_pos=anchor
        )
        self.battle_panel.on_mode_toggle = self._on_mode_toggle
        self.battle_panel.get_ball_state = self.settings_controller.ball_state
        self.battle_panel.on_toggle_ball = self.settings_controller.toggle_ball
        self.battle_panel.on_set_all_balls = self.settings_controller.set_all_balls
        
        self._last_hud = ""  # last resolved HUD location (drives dex panel refresh)
        self._loc_read = False  # location OCR'd this battle yet
        self._loc_ocr_raw = ""  # last raw OCR text (tracks what the screen actually shows)
        self._last_loc_mask: np.ndarray | None = None  # fast visual delta for location OCR
        self._loc_future: Future[str] | None = None  # background Location OCR task
        self._name_future: Future[dict[Any, Any] | None] | None = None  # background Name OCR task
        self._battle_loc_future: Future[Any] | None = None

        self._was_horde = False  # read_battle horde hint (read every tick, so init here)
        self._battle_debounce: int = 0  # frame counter for debounce_battle
        self._stable_in_battle: bool = False  # debounced battle membership
        self._last_loc_check = 0.0  # last IDLE location OCR (throttle)
        self._dex_log = ""  # last printed dex panel text (console dedup)

        if self.dex_panel is not None and self.dex is not None:
            self.dex_panel.on_toggle_caught = self._dex_toggle_caught
            self.dex_panel.get_keep_caught = lambda: self.settings.keep_caught
            self.dex_panel.get_click_to_catch = lambda: self.settings.click_to_catch

    def start(self) -> None:
        log.info(f"ShakeChecker v{paths.APP_VERSION}")
        if self.species_override or self.status_override:
            species_src = (
                f"override {self.species_override['name']}"
                if self.species_override
                else "OCR from screen"
            )
            status_src = (
                f"override {self.status_override}" if self.status_override else "from screen"
            )
            log.info(f"override mode active - species: {species_src}, status: {status_src}")
        log.info("loading OCR neural networks...")
        from core import ocr_engine

        def _load_ocr() -> None:
            ocr_engine.preload()
        self.pool.submit(_load_ocr)
        log.info("waiting for PokeMMO window...")
        QTimer.singleShot(0, self.step)

    def step(self) -> None:
        # One bad frame (a transient capture/OCR hiccup) must never kill the loop:
        # if _tick raised, the next singleShot would never be scheduled and the
        # overlay would freeze for good. Log it and carry on at the normal cadence.
        try:
            interval_s = self._tick()
        except Exception:
            log.exception("tick failed; continuing")
            interval_s = self._frame_interval()
        QTimer.singleShot(int(interval_s * 1000), self.step)

    def _frame_interval(self) -> float:
        return self.config.battle_frame_s if self.state is AppState.BATTLE else self.config.idle_frame_s

    def _apply_mode_change(self, log_msg: str) -> None:
        self.settings_controller.close()
        if self.mode_override == "dex":
            self.battle_panel.hide()
        elif self.mode_override == "battle" and self.dex_panel is not None:
            self.dex_panel.hide_panel()
        QApplication.processEvents()

        log.info(log_msg)
        if self.mode_override == "dex":
            self._refresh_dex_panel()
        self._tick()

    def _on_mode_toggle(self) -> None:
        if self.dex_panel is not None:
            self.dex_panel._hide_popups()
        if self.mode_override == "auto":
            self.mode_override = "dex" if self.state == AppState.BATTLE else "battle"
        elif self.mode_override == "dex":
            self.mode_override = "battle"
        else:
            self.mode_override = "dex"
        self._apply_mode_change(f"manual mode override: {self.mode_override}")

    def _handle_settings_update(self, update: SettingsUpdate) -> None:
        if update.settings_changed:
            self.settings.save()

        # Handle UI scale updates
        if update.scale_changed and self.hwnd is not None:
            client_rect = get_client_rect(self.hwnd)
            if client_rect is not None:
                if self.battle_panel.isVisible():
                    new_scale = self.settings.battle_scale or scale_for_window(client_rect.height)
                    self.battle_panel.apply_scale(new_scale)
                    self.battle_panel.dock_to(client_rect.left, client_rect.top, client_rect.width)
                if self.dex_panel is not None and self.dex_panel.isVisible():
                    new_scale = self.settings.dex_scale or scale_for_window(client_rect.height)
                    self.dex_panel.apply_scale(new_scale)
                    self.dex_panel.dock_to(client_rect.left, client_rect.top, client_rect.width)

        # Handle Ball toggles
        if update.settings_changed:
            self.battle_panel.set_hidden_names(self.settings_controller.hidden_ball_names())

        # Handle Mode overrides
        if update.toggle_auto_switch:
            if self.dex_panel is not None:
                self.dex_panel._hide_popups()
            if self.settings.auto_switch:
                self.mode_override = "auto"
            else:
                self.mode_override = "dex" if self.state == AppState.BATTLE else "battle"
            self._apply_mode_change(f"auto switch toggled, mode is now: {self.mode_override}")

        # Handle Dex Intents
        if update.new_profile:
            self.dex_controller.load_profile(update.new_profile)
        if update.deleted_profile:
            self.dex_controller.load_profile(update.deleted_profile)
        if update.new_region:
            self.dex_controller.override_region(update.new_region)
            if self._loc_ocr_raw:
                # Force an immediate dex update using the last location
                view = self.dex.on_location(self.dex_controller._last_hud) if self.dex else None
                if view is not None and self.dex_panel is not None and self.hwnd is not None:
                    client_rect = get_client_rect(self.hwnd)
                    if client_rect is not None:
                        self.dex_panel.apply_scale(self.settings.dex_scale or scale_for_window(client_rect.height))
                        self.dex_panel.show_here(view)
                        self.dex_panel.dock_to(client_rect.left, client_rect.top, client_rect.width)
        
        if update.refresh_dex:
            self._refresh_dex_panel()



    def _set_owner(self, widget: QWidget | None, owner_hwnd: int) -> None:
        if widget is not None:
            from PyQt6.QtGui import QWindow

            # Force Qt to create the native window handle even if the widget hasn't been shown yet
            widget.winId()
            handle = widget.windowHandle()

            if handle:
                if owner_hwnd == 0:
                    # Remove transient parent and cleanup tracking dict
                    if hasattr(self, "_owner_windows") and id(widget) in self._owner_windows:
                        del self._owner_windows[id(widget)]
                    handle.setTransientParent(None)

                else:
                    # Ensure the tracking dict exists with a proper type annotation
                    if not hasattr(self, "_owner_windows"):
                        self._owner_windows: dict[int, QWindow | None] = {}

                    # Keep the wrapper alive so GC doesn't break the transient-parent link
                    proxy = QWindow.fromWinId(int(owner_hwnd))  # type: ignore[arg-type]
                    self._owner_windows[id(widget)] = proxy
                    handle.setTransientParent(proxy)

    def _tick(self) -> float:

        if self.state is AppState.WAITING:
            self.hwnd = find_pokemmo_hwnd()
            if self.hwnd is None:
                return self.config.waiting_poll_s
            log.info("PokeMMO window found")
            self.state = AppState.IDLE
            self.capture.hwnd = self.hwnd
            self._set_owner(self.battle_panel, self.hwnd)
            self._set_owner(self.dex_panel, self.hwnd)

            # Nudge panels above the game window once at startup
            from ui.ui_overlay import bring_overlay_above_game

            if self.battle_panel is not None:
                bring_overlay_above_game(self.battle_panel)
            if self.dex_panel is not None:
                bring_overlay_above_game(self.dex_panel)

        assert self.hwnd is not None
        # Capture the FULL window (matches the full-window fixtures the CV regions
        # are calibrated on); dock the overlay to the client area (below the HUD).
        win_rect = get_window_rect(self.hwnd)
        client_rect = get_client_rect(self.hwnd)
        if win_rect is None or client_rect is None:
            if not is_window_alive(self.hwnd):
                log.info("window lost, waiting...")
                if self.hwnd is not None:
                    self._set_owner(self.battle_panel, 0)
                    self._set_owner(self.dex_panel, 0)
                    self.hwnd = None
                if self.capture is not None:
                    self.capture.hwnd = 0
                self.state = AppState.WAITING
                self.battle_panel.hide_battle()
                if self.dex_panel is not None:
                    self.dex_panel.hide_panel()
            return self.config.waiting_poll_s

        if self.capture is None:
            return self.config.waiting_poll_s

        frame = self.capture.grab(client_rect)
        if frame is None:
            return 0.05
        self._last_frame = frame
        now = time.monotonic()
        
        needs_reading = (self.mode_override != "dex") or (
            self.state == AppState.BATTLE and getattr(self.battle_controller, "cached", None) is None
        )
        
        vision_hint = self.battle_controller.get_vision_hint() if hasattr(self, "battle_controller") else False
        vision = self.vision_controller.step(frame, needs_reading, vision_hint)
        
        if vision is None:
            return self._frame_interval()
            
        reading = vision.battle_reading_raw
        bt = vision.battle_text_raw
        ui_present = vision.hud_present
        
        if needs_reading and reading is not None:
            self._stable_in_battle, self._battle_debounce = debounce_battle(
                is_in_battle(reading.state, bt), self._battle_debounce
            )
            in_battle = self._stable_in_battle
        else:
            self._stable_in_battle, self._battle_debounce = debounce_battle(
                bt.menu_present or bt.action or bt.caught, self._battle_debounce
            )
            in_battle = self._stable_in_battle

        grace = battle_end_grace(
            self.battle_controller._is_trainer if hasattr(self, "battle_controller") else False,
            ui_present,
            trainer_s=self.config.trainer_end_grace_s,
            anim_s=self.config.battle_anim_grace_s,
            normal_s=self.config.battle_end_grace_s,
        )

        if in_battle:
            self.last_seen_battle = now
            if self.state is not AppState.BATTLE:
                self.state = AppState.BATTLE
                log.info("battle detected")
                self.battle_controller.reset(now)
                if self.dex_panel is not None:
                    self.dex_panel.hide_panel()
            
            b_frame = BattleFrame(
                frame=frame,
                battle_reading_raw=reading,
                battle_text_raw=bt,
                enemy_count=vision.enemy_count,
                rect=client_rect,
                now=now,
                location_text=self._loc_ocr_raw
            )
            timer_active = ("timer" not in self.settings.hidden_balls) and (self.mode_override != "dex")
            update = self.battle_controller.step(b_frame, timer_active)
            
            if update.caught_species_id and self.dex is not None:
                if self.dex.record_caught(update.caught_species_id):
                    log.info(f"dex: recorded OT-caught from UI")

            if self.mode_override != "dex" and update.panel_state is not None:
                self.battle_panel.apply_scale(self.settings.battle_scale or scale_for_window(client_rect.height))
                self.battle_panel.show_battle(**update.panel_state)
                self.battle_panel.dock_to(client_rect.left, client_rect.top, client_rect.width)
        elif self.state is AppState.BATTLE and now - self.last_seen_battle <= grace:
            # In a battle but no battle signal this frame (animation gap). Log what
            # dropped out so a false "battle ended" can be diagnosed: which signal
            # is missing and whether ui_present held the grace at the longer value.
            log.debug(
                "battle gap: ui=%s state=%s menu=%s action=%s caught=%s grace=%.1f since=%.2f",
                ui_present,
                reading.state.name,
                bt.menu_present,
                bt.action,
                bt.caught,
                grace,
                now - self.last_seen_battle,
            )
        elif self.state is AppState.BATTLE and now - self.last_seen_battle > grace:
            self.state = AppState.IDLE
            self.last_line = ""
            if not self.battle_controller._caught_printed:  # after a catch we already said "caught X!"
                log.info("battle ended")
            self._battle_debounce = 0
            self._stable_in_battle = False
            self.vision_controller.reset()
            self.battle_panel.hide_battle()
            # Show the dex panel at once, from the pre-battle location (you can't
            # move during a battle, so it's still valid) -- no wait for the next
            # throttled OCR tick. _last_loc_check is reset so OCR re-confirms soon.
            self.dex_controller.reset_loc_check()
            if self.dex_panel is not None and self.dex is not None and self.settings.auto_switch:
                # Restore the dex panel immediately using the pre-battle location
                # (position hasn't changed during the battle). If the location
                # isn't known yet, show a loading state so the panel is visible;
                # the next throttled OCR tick will fill it in.
                view = self.dex.on_location(self.dex_controller._last_hud) if self.dex_controller._last_hud else None
                self.dex_panel.apply_scale(
                    self.settings.dex_scale or scale_for_window(client_rect.height)
                )
                if view is not None:
                    self.dex_panel.show_here(view)
                else:
                    self.dex_panel.show()
                self.dex_panel.dock_to(client_rect.left, client_rect.top, client_rect.width)

        # Walking around (not in battle): refresh the "missing here" dex panel from
        # the HUD location on a throttle (location OCR is slow, location changes
        # slowly). Skipped during battles, where the location is read once instead.
        if not in_battle and self.dex is not None:
            h, w = frame.shape[:2]
            y1 = int(self.cal.location.top) if self.cal.location.top > 1.0 else int(h * self.cal.location.top)
            y2 = int(self.cal.location.bottom) if self.cal.location.bottom > 1.0 else int(h * self.cal.location.bottom)
            x1 = int(self.cal.location.left) if self.cal.location.left > 1.0 else int(w * self.cal.location.left)
            x2 = int(self.cal.location.right) if self.cal.location.right > 1.0 else int(w * self.cal.location.right)
            hud_crop = frame[y1:y2, x1:x2]

            dex_frame = DexFrame(hud_crop=hud_crop, now=now, in_battle=in_battle)
            update = self.dex_controller.step(dex_frame)
            
            self._loc_ocr_raw = update.location_text
            
            if self.dex_panel is not None:
                self.dex_panel.set_loading(update.is_loading)
            
            if update.log_line and update.log_line != getattr(self, "_dex_log", None):
                log.info(update.log_line)
                self._dex_log = update.log_line
                
            if self.mode_override == "dex" or (
                self.mode_override == "auto"
                and self.settings.auto_switch
                and self.state != AppState.BATTLE
            ):
                if self.dex_panel is not None and update.location_view is not None:
                    self.dex_panel.apply_scale(
                        self.settings.dex_scale or scale_for_window(client_rect.height)
                    )
                    if self.mode_override != "battle":
                        self.dex_panel.show_here(update.location_view)
                    self.dex_panel.dock_to(client_rect.left, client_rect.top, client_rect.width)

        # Apply manual mode override UI forcing
        if self.mode_override == "dex":
            if self.battle_panel.isVisible():
                self.battle_panel.hide()
            if (
                self.state == AppState.BATTLE
                and self.dex_panel is not None
                and not self.dex_panel.isVisible()
            ):
                self.dex_panel.show()
        elif self.mode_override == "battle":
            if self.dex_panel is not None and self.dex_panel.isVisible():
                self.dex_panel.hide_panel()
            if self.state == AppState.IDLE and not self.battle_panel.isVisible():
                self.battle_panel.apply_scale(
                    self.settings.battle_scale or scale_for_window(client_rect.height)
                )
                self.battle_panel.show_battle(
                    dex_id=0,
                    name="—",
                    catch_rate=None,
                    turn=0,
                    probs={},
                    is_empty=True,
                )
        # Sync positions so toggling doesn't cause panels to jump
        bp_pos = getattr(self.battle_panel, "_last_pos", None)
        dp_pos = getattr(self.dex_panel, "_last_pos", None) if self.dex_panel is not None else None

        if self.battle_panel.isVisible() and bp_pos is not None:
            if self.dex_panel is not None:
                self.dex_panel._last_pos = bp_pos
                self.dex_panel.move(*bp_pos)
        elif (
            self.dex_panel is not None
            and self.dex_panel.isVisible()
            and dp_pos is not None
            or self.battle_panel.isVisible()
            and bp_pos is None
            and dp_pos is not None
        ):
            self.battle_panel._last_pos = dp_pos
            self.battle_panel.move(*dp_pos)
        elif (
            self.dex_panel is not None
            and self.dex_panel.isVisible()
            and dp_pos is None
            and bp_pos is not None
        ):
            self.dex_panel._last_pos = bp_pos
            self.dex_panel.move(*bp_pos)

        return self._frame_interval()

    def _cleanup(self) -> None:
        if self.capture is not None:
            self.capture.close()
        self.pool.shutdown(wait=False)
        self.loc_pool.shutdown(wait=False)

    def _refresh_dex_panel(self) -> None:
        """Re-render the panel for the current location (after a toggle/profile
        change) so the moved species and counts update immediately."""
        if self.dex is None or self.dex_panel is None:
            return
        if not self.dex_controller._last_hud:
            if getattr(self.dex_controller, "_loc_future", None) is not None:
                from core.game_time import Period
                from dex.dex_structures import LocationView

                dummy_view = LocationView(
                    route="Reading location...",
                    region="Please wait",
                    period=Period.DAY,
                    season=0,
                    entries=[],
                )
                self.dex_panel.show_here(dummy_view)
            return

        view = self.dex.on_location(self.dex_controller._last_hud)
        if view is not None:
            self.dex_panel.show_here(view)
    def _dex_toggle_caught(self, dex_id: int) -> None:
        if self.dex is None:
            return
        now = self.dex.toggle_caught(dex_id)
        log.info(f"dex: {'marked' if now else 'un-marked'} #{dex_id} as caught")
        self._refresh_dex_panel()
