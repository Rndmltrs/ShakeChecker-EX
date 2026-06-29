import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtGui import QWindow
from PyQt6.QtWidgets import QWidget

from ui.battle_panel import BattlePanel
from ui.dex_panel import DexPanel
from ui.ui_overlay import bring_overlay_above_game, scale_for_window

if TYPE_CHECKING:
    from core.settings_controller import Settings
    from core.window_capture import ClientRect

log = logging.getLogger("shakechecker")


class UIManager:
    """Coordinates the visibility, docking, and scaling of the overlay panels."""

    def __init__(
        self,
        battle_panel: BattlePanel,
        dex_panel: DexPanel | None,
        settings: "Settings",
    ):
        self.battle_panel = battle_panel
        self.dex_panel = dex_panel
        self.settings = settings
        self.mode_override = "auto" if self.settings.auto_switch else "dex"

        self._owner_windows: dict[int, QWindow | None] = {}

    def _set_owner(self, widget: QWidget | None, owner_hwnd: int) -> None:
        if widget is not None:
            # Force Qt to create the native window handle even if the widget hasn't been shown yet
            widget.winId()
            handle = widget.windowHandle()

            if handle:
                if owner_hwnd == 0:
                    # Remove transient parent and cleanup tracking dict
                    if id(widget) in self._owner_windows:
                        del self._owner_windows[id(widget)]
                    handle.setTransientParent(None)
                else:
                    # Keep the wrapper alive so GC doesn't break the transient-parent link
                    proxy = QWindow.fromWinId(int(owner_hwnd))  # type: ignore[arg-type]
                    self._owner_windows[id(widget)] = proxy
                    handle.setTransientParent(proxy)

    def attach_to_window(self, hwnd: int) -> None:
        self._set_owner(self.battle_panel, hwnd)
        self._set_owner(self.dex_panel, hwnd)
        bring_overlay_above_game(self.battle_panel)
        if self.dex_panel is not None:
            bring_overlay_above_game(self.dex_panel)

    def detach_window(self) -> None:
        self._set_owner(self.battle_panel, 0)
        self._set_owner(self.dex_panel, 0)
        self.battle_panel.hide_battle()
        if self.dex_panel is not None:
            self.dex_panel.hide_panel()

    def toggle_mode(self, in_battle: bool) -> None:
        if self.dex_panel is not None:
            self.dex_panel._hide_popups()
        if self.mode_override == "auto":
            self.mode_override = "dex" if in_battle else "battle"
        elif self.mode_override == "dex":
            self.mode_override = "battle"
        else:
            self.mode_override = "dex"

        self.apply_mode_change(in_battle, f"manual mode override: {self.mode_override}")

    def apply_mode_change(self, in_battle: bool, log_msg: str | None = None) -> None:
        if log_msg:
            log.info(log_msg)

    def handle_auto_switch_toggled(self, in_battle: bool) -> None:
        if self.dex_panel is not None:
            self.dex_panel._hide_popups()
        if self.settings.auto_switch:
            self.mode_override = "auto"
        else:
            self.mode_override = "dex" if in_battle else "battle"
        self.apply_mode_change(in_battle, f"auto switch toggled, mode is now: {self.mode_override}")

    def enforce_mode_ui(self, in_battle: bool, client_rect: "ClientRect") -> None:
        """Applies manual mode override UI forcing and syncs panel positions."""
        if self.mode_override == "dex":
            if self.battle_panel.isVisible():
                self.battle_panel.hide()
            if in_battle and self.dex_panel is not None and not self.dex_panel.isVisible():
                self.dex_panel.show()
        elif self.mode_override == "battle":
            if self.dex_panel is not None and self.dex_panel.isVisible():
                self.dex_panel.hide_panel()
            if not in_battle and not self.battle_panel.isVisible():
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

        elif self.mode_override == "auto":
            if in_battle and self.dex_panel is not None and self.dex_panel.isVisible():
                self.dex_panel.hide_panel()
            elif not in_battle and self.battle_panel.isVisible():
                self.battle_panel.hide_battle()

        self.sync_panel_positions()

    def sync_panel_positions(self) -> None:
        """Sync positions so toggling doesn't cause panels to jump"""
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

    def on_battle_start(self) -> None:
        if self.settings.auto_switch:
            self.mode_override = "auto"

    def on_battle_end(self) -> None:
        if self.settings.auto_switch:
            self.mode_override = "auto"

    def update_battle_panel(
        self, update_state: dict[str, Any] | None, client_rect: "ClientRect", is_loading: bool
    ) -> None:
        if self.mode_override != "dex":
            self.battle_panel.set_loading(is_loading)
            if update_state is not None:
                self.battle_panel.apply_scale(
                    self.settings.battle_scale or scale_for_window(client_rect.height)
                )
                self.battle_panel.show_battle(**update_state)
                self.battle_panel.dock_to(client_rect.left, client_rect.top, client_rect.width)

    def update_dex_panel(
        self, view: Any, client_rect: "ClientRect", is_loading: bool, in_battle: bool
    ) -> None:
        if self.dex_panel is not None:
            self.dex_panel.set_loading(is_loading)

            if view is not None and (
                self.mode_override == "dex"
                or (self.mode_override == "auto" and self.settings.auto_switch and not in_battle)
            ):
                self.dex_panel.apply_scale(
                    self.settings.dex_scale or scale_for_window(client_rect.height)
                )
                if self.mode_override != "battle":
                    self.dex_panel.show_here(view)
                self.dex_panel.dock_to(client_rect.left, client_rect.top, client_rect.width)
