from __future__ import annotations

import contextlib
import enum
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtGui import QWindow
from PyQt6.QtWidgets import QApplication, QWidget

from battle.battle_manager import BattleDetectorState, BattleInput, BattleManager
from battle.battle_reader import Calibration
from battle.battle_vision import BattleVision
from core import paths
from core.services import AppConfig, OcrServices
from core.settings_controller import SettingsController, SettingsUpdate
from core.vision_controller import VisionController
from core.window_capture import (
    WindowCapture,
    find_pokemmo_hwnd,
    get_client_rect,
    get_window_rect,
    is_window_alive,
)
from dex.dex_controller import DexController, DexFrame
from dex.dex_session import DexSession
from ui.battle_panel import BattlePanel
from ui.dex_panel import DexPanel
from ui.ui_manager import UIManager
from ui.ui_overlay import scale_for_window


class AppState(enum.Enum):
    WAITING = "waiting"
    IDLE = "idle"
    BATTLE = "battle"


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
        battle_manager: BattleManager,
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

        self.battle_manager = battle_manager
        self.dex_controller = dex_controller
        self.settings_controller = settings_controller
        self._battle_vision = BattleVision()
        self.ui_manager = UIManager(self.battle_panel, self.dex_panel, self.settings)

        self.battle_panel.set_hidden_names(self.settings_controller.hidden_ball_names())

        self.vision_controller = vision_controller

        if self.dex_panel is not None:
            self.dex_panel.on_mode_toggle = lambda: self.ui_manager.toggle_mode(
                self.state == AppState.BATTLE
            )
            self.dex_panel.on_settings_click = lambda anchor: self.settings_controller.show(
                mode="dex", anchor_pos=anchor
            )

        self.battle_panel.on_settings_click = lambda anchor: self.settings_controller.show(
            mode="battle", anchor_pos=anchor
        )
        self.battle_panel.on_mode_toggle = lambda: self.ui_manager.toggle_mode(
            self.state == AppState.BATTLE
        )
        self.battle_panel.get_ball_state = self.settings_controller.ball_state
        self.battle_panel.on_toggle_ball = self.settings_controller.toggle_ball
        self.battle_panel.on_set_all_balls = self.settings_controller.set_all_balls
        self.battle_panel.on_force_refresh = self._force_refresh_battle
        self.settings_controller.panel.on_dump_debug = self._on_dump_debug

        self._last_hud = ""  # last resolved HUD location (drives dex panel refresh)
        self._loc_ocr_raw = ""  # last raw OCR text (tracks what the screen actually shows)
        self._dex_log = ""  # last printed dex panel text (console dedup)

        if self.dex_panel is not None and self.dex is not None:
            self.dex_panel.on_toggle_caught = self._dex_toggle_caught
            self.dex_panel.on_force_refresh = self._force_refresh_loc
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

        # Inter-Process Communication (IPC): Watch for a quit signal file created by the
        # PowerShell launcher.
        self._quit_timer = QTimer()
        self._quit_timer.timeout.connect(self._check_quit)
        self._quit_timer.start(1000)

        QTimer.singleShot(0, self.step)

    def _check_quit(self) -> None:
        if os.path.exists(".shakechecker_quit"):
            with contextlib.suppress(OSError):
                os.remove(".shakechecker_quit")
            from PyQt6.QtWidgets import QApplication

            QApplication.quit()

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
        return (
            self.config.battle_frame_s
            if self.state is AppState.BATTLE
            else self.config.idle_frame_s
        )

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
        if self.ui_manager.mode_override == "auto":
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
                self.ui_manager.sync_panel_positions()
                if self.battle_panel.isVisible():
                    self.battle_panel.apply_scale(
                        self.settings.battle_scale or scale_for_window(client_rect.height)
                    )
                    self.battle_panel.dock_to(client_rect.left, client_rect.top, client_rect.width)
                if self.dex_panel is not None and self.dex_panel.isVisible():
                    self.dex_panel.apply_scale(
                        self.settings.dex_scale or scale_for_window(client_rect.height)
                    )
                    self.dex_panel.dock_to(client_rect.left, client_rect.top, client_rect.width)

        # Handle Ball toggles
        if update.settings_changed:
            self.battle_panel.set_hidden_names(self.settings_controller.hidden_ball_names())

        # Handle Mode overrides
        if update.toggle_auto_switch:
            self.ui_manager.handle_auto_switch_toggled(self.state == AppState.BATTLE)
            if self.ui_manager.mode_override == "dex":
                self._refresh_dex_panel()

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
                        self.dex_panel.apply_scale(
                            self.settings.dex_scale or scale_for_window(client_rect.height)
                        )
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
        now = time.monotonic()

        if self.state is AppState.WAITING:
            self.hwnd = find_pokemmo_hwnd()
            if self.hwnd is None:
                return self.config.waiting_poll_s
            log.info("PokeMMO window found")
            self.state = AppState.IDLE
            self.capture.hwnd = self.hwnd
            self.ui_manager.attach_to_window(self.hwnd)

        assert self.hwnd is not None
        # Capture the FULL window (matches the full-window fixtures the CV regions
        # are calibrated on); dock the overlay to the client area (below the HUD).
        win_rect = get_window_rect(self.hwnd)
        client_rect = get_client_rect(self.hwnd)
        if win_rect is None or client_rect is None:
            if not is_window_alive(self.hwnd):
                log.info("window lost, waiting...")
                if self.hwnd is not None:
                    self.ui_manager.detach_window()
                    self.hwnd = None
                if self.capture is not None:
                    self.capture.hwnd = 0
                self.state = AppState.WAITING
            return self.config.waiting_poll_s

        if self.capture is None:
            return self.config.waiting_poll_s

        frame = self.capture.grab(client_rect)
        if frame is None:
            return 0.05
        self._last_frame = frame

        needs_reading = (self.ui_manager.mode_override != "dex") or (
            self.state == AppState.BATTLE
            and (self.battle_manager.ctx.species is None or self.battle_manager.ctx.is_trainer)
        )

        vision = self.vision_controller.step(frame, needs_reading, False)

        if vision is None:
            return self._frame_interval()

        reading = vision.battle_reading_raw
        bt = vision.battle_text_raw

        # Build the semantic BattleScene from raw vision output
        scene = self._battle_vision.step(
            frame,
            reading,
            bt,
            vision.enemy_count,
            self.cal,
            hud_present=vision.hud_present,
            ui_brightness=vision.ui_brightness,
            location_text=self._loc_ocr_raw,
            now=now,
            known_species=self.battle_manager.ctx.species,
        )

        det_state, update = self.battle_manager.step(
            BattleInput(
                scene=scene,
                frame=frame.copy(),
                timer_active=("timer" not in self.settings.hidden_balls)
                and (self.ui_manager.mode_override != "dex"),
                rect=QRect(
                    client_rect.left,
                    client_rect.top,
                    client_rect.width,
                    client_rect.height,
                ),
                chat_turn=self.ocr.chat_reader.poll(),
            )
        )

        if det_state == BattleDetectorState.ACTIVE:
            if self.state is not AppState.BATTLE:
                self.state = AppState.BATTLE
                self.ui_manager.on_battle_start()
                log.info("battle detected")
                self.battle_manager.reset(now)
                self._battle_vision.reset()
                return self._frame_interval()

            if (
                update.caught_species_id
                and self.dex is not None
                and self.dex.record_caught(update.caught_species_id)
            ):
                log.info("dex: recorded OT-caught from UI")

            self.ui_manager.update_battle_panel(update.panel_state, client_rect, update.is_loading)
        elif det_state == BattleDetectorState.GAP:
            log.debug(
                "battle gap: hud=%s state=%s menu=%s action=%s caught=%s",
                scene.hud_present,
                scene.state.name,
                scene.menu_present,
                scene.action_present,
                scene.caught_present,
            )
        elif det_state == BattleDetectorState.IDLE:
            if self.state is AppState.BATTLE:
                self.state = AppState.IDLE
                self.ui_manager.on_battle_end()
                self.last_line = ""
                if not self.battle_manager.ctx.caught_logged:
                    log.info("battle ended")
                self.vision_controller.reset()
                # Show the dex panel at once, from the pre-battle location (you can't
                # move during a battle, so it's still valid) -- no wait for the next
                # throttled OCR tick. _last_loc_check is reset so OCR re-confirms soon.
                self.dex_controller.reset_loc_check()
                if (
                    self.dex_panel is not None
                    and self.dex is not None
                    and self.settings.auto_switch
                ):
                    # Restore the dex panel immediately using the pre-battle location
                    # (position hasn't changed during the battle). If the location
                    # isn't known yet, show a loading state so the panel is visible;
                    # the next throttled OCR tick will fill it in.
                    view = self.dex_controller.get_current_view()
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
        if self.dex is not None:
            in_battle = self.state == AppState.BATTLE
            h, w = frame.shape[:2]
            y1 = (
                int(self.cal.location.top)
                if self.cal.location.top > 1.0
                else int(h * self.cal.location.top)
            )
            y2 = (
                int(self.cal.location.bottom)
                if self.cal.location.bottom > 1.0
                else int(h * self.cal.location.bottom)
            )
            x1 = (
                int(self.cal.location.left)
                if self.cal.location.left > 1.0
                else int(w * self.cal.location.left)
            )
            x2 = (
                int(self.cal.location.right)
                if self.cal.location.right > 1.0
                else int(w * self.cal.location.right)
            )
            hud_crop = frame[y1:y2, x1:x2]

            dex_frame = DexFrame(hud_crop=hud_crop, now=now, in_battle=in_battle)
            dex_update = self.dex_controller.step(dex_frame)

            self._loc_ocr_raw = dex_update.location_text

            if self.dex_panel is not None:
                self.dex_panel.set_loading(dex_update.is_loading)
            if dex_update.log_line and dex_update.log_line != getattr(self, "_dex_log", None):
                log.info(dex_update.log_line)
                self._dex_log = dex_update.log_line

            self.ui_manager.update_dex_panel(
                dex_update.location_view, client_rect, dex_update.is_loading, in_battle
            )

        self.ui_manager.enforce_mode_ui(self.state == AppState.BATTLE, client_rect)

        return self._frame_interval()

    def _cleanup(self) -> None:
        if self.capture is not None:
            self.capture.close()
        self.pool.shutdown(wait=False)
        self.loc_pool.shutdown(wait=False)

    def _refresh_dex_panel(self) -> None:
        """Re-render the panel for the current location (after a toggle/profile
        change) so the moved species and counts update immediately."""
        if self.dex_panel is None:
            return

        view = self.dex_controller.get_current_view()
        if view is not None:
            self.dex_panel.show_here(view)

    def _on_dump_debug(self) -> None:
        if hasattr(self, "_last_frame") and self._last_frame is not None:
            from core.debug_dump import trigger_debug_dump

            reading = getattr(self.vision_controller, "_last_reading", None)
            trigger_debug_dump(self._last_frame, reading, self.cal)

    def _dex_toggle_caught(self, dex_id: int) -> None:
        """Called when a user manually clicks a dex panel entry."""
        self.dex_controller.toggle_caught(dex_id)
        log.info(f"dex: manually toggled species {dex_id}")
        self._refresh_dex_panel()

    def _force_refresh_loc(self) -> None:
        if hasattr(self, "dex_controller"):
            self.dex_controller.force_refresh()
        self._last_hud = ""
        log.info("Forced location refresh via Dex panel")

    def _force_refresh_battle(self) -> None:
        if hasattr(self, "battle_manager"):
            self.battle_manager.force_refresh()
        log.info("Forced battle state refresh via Battle panel")
