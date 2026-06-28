import logging
from dataclasses import dataclass
from typing import Any, Callable

from core.account_store import AccountConfig, delete_account_data
from core.settings_store import Settings
from core.services import AppConfig
from ui.settings_panel import SettingsPanel

log = logging.getLogger("shakechecker")

@dataclass
class SettingsUpdate:
    battle_panel_state: dict[str, Any] | None = None
    dex_panel_state: dict[str, Any] | None = None
    log_line: str | None = None
    scale_changed: bool = False
    refresh_dex: bool = False
    settings_changed: bool = False
    
    # Domain intents to route to DexController
    new_profile: str | None = None
    deleted_profile: str | None = None
    toggle_keep_caught: bool = False
    new_region: str | None = None
    
    # Domain intents to route to AppController
    toggle_auto_switch: bool = False


class SettingsController:
    def __init__(
        self,
        *,
        settings: Settings,
        balls: list[dict],
        config: AppConfig,
        get_region: Callable[[], str | None],
        on_update: Callable[[SettingsUpdate], None],
    ):
        self.settings = settings
        self.balls = balls
        self.config = config
        self.get_region = get_region
        self.on_update = on_update
        
        self.panel = SettingsPanel()
        
        # Wire up callbacks
        self.panel.on_choose_profile = self._on_choose_profile
        self.panel.on_create_profile = self._on_choose_profile
        self.panel.on_remove_profile = self._on_remove_profile
        self.panel.get_profiles = self._get_profiles
        
        self.panel.get_keep_caught = lambda: self.settings.keep_caught
        self.panel.on_toggle_keep_caught = self._on_toggle_keep_caught
        
        self.panel.get_auto_switch = lambda: self.settings.auto_switch
        self.panel.on_toggle_auto_switch = self._on_toggle_auto_switch
        
        self.panel.get_click_to_catch = lambda: self.settings.click_to_catch
        self.panel.on_toggle_click_to_catch = self._on_toggle_click_to_catch
        
        self.panel.get_current_region = self.get_region
        self.panel.on_override_region = self._on_override_region
        
        self.panel.get_dex_scale = lambda: self.settings.dex_scale
        self.panel.on_set_dex_scale = self._on_set_dex_scale
        
        self.panel.get_battle_scale = lambda: self.settings.battle_scale
        self.panel.on_set_battle_scale = self._on_set_battle_scale

    def show(self, mode: str, anchor_pos) -> None:
        """Proxy to show the settings panel."""
        self.panel.show(mode=mode, anchor_pos=anchor_pos)

    def close(self) -> None:
        """Proxy to close the settings panel."""
        self.panel.close()

    # --- Profile Logic ---
    def _get_profiles(self) -> tuple[str | None, list[str]]:
        cfg = AccountConfig.load(self.config.userdata_path)
        return cfg.active, cfg.accounts

    def _on_choose_profile(self, name: str) -> None:
        cfg = AccountConfig.load(self.config.userdata_path)
        account = cfg.use(name)
        log.info(f"dex: active account '{account}'")
        self.on_update(SettingsUpdate(new_profile=account, refresh_dex=True))

    def _on_remove_profile(self, name: str) -> None:
        cfg = AccountConfig.load(self.config.userdata_path)
        cfg.delete(name)
        delete_account_data(self.config.userdata_path, name)
        account = cfg.active or cfg.use("default")
        log.info(f"dex: deleted profile '{name}', active now '{account}'")
        self.on_update(SettingsUpdate(deleted_profile=account, refresh_dex=True))

    # --- Toggles ---
    def _on_toggle_keep_caught(self) -> None:
        now = self.settings.toggle_keep_caught()
        log.info(f"dex: keep-caught {'on' if now else 'off'}")
        self.on_update(SettingsUpdate(settings_changed=True, toggle_keep_caught=True, refresh_dex=True))

    def _on_toggle_auto_switch(self) -> None:
        now = self.settings.toggle_auto_switch()
        self.on_update(SettingsUpdate(settings_changed=True, toggle_auto_switch=True))

    def _on_toggle_click_to_catch(self) -> None:
        self.settings.toggle_click_to_catch()
        self.on_update(SettingsUpdate(settings_changed=True))

    # --- Region & Scale ---
    def _on_override_region(self, region: str | None) -> None:
        log.info(f"dex: region override set to: {region if region else 'Auto'}")
        self.on_update(SettingsUpdate(new_region=region, refresh_dex=True))

    def _on_set_dex_scale(self, scale: float | None) -> None:
        self.settings.set_dex_scale(scale)
        log.info(f"dex: scale override set to {scale if scale else 'Auto'}")
        self.on_update(SettingsUpdate(settings_changed=True, scale_changed=True))

    def _on_set_battle_scale(self, scale: float | None) -> None:
        self.settings.set_battle_scale(scale)
        log.info(f"battle: scale override set to {scale if scale else 'Auto'}")
        self.on_update(SettingsUpdate(settings_changed=True, scale_changed=True))

    # --- Ball Visibility ---
    def hidden_ball_names(self) -> set[str]:
        """Hidden ball NAMES for the overlay (it keys by name; settings store ids)."""
        return {b["name"] for b in self.balls if b["id"] in self.settings.hidden_balls}

    def ball_state(self) -> tuple[list[tuple[str, str]], set[str]]:
        return [(b["id"], b["name"]) for b in self.balls], set(self.settings.hidden_balls)

    def toggle_ball(self, ball_id: str) -> None:
        self.settings.toggle_ball(ball_id)
        self.on_update(SettingsUpdate(settings_changed=True))

    def set_all_balls(self, show: bool) -> None:
        self.settings.set_all_balls([b["id"] for b in self.balls], show)
        self.on_update(SettingsUpdate(settings_changed=True))
