from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import numpy as np
from PyQt6.QtCore import QRect

from battle.battle_logic import apply_chat_turn, debounce_menu, is_horde_remnant
from battle.battle_reader import BattleState, Calibration, Status, is_trainer_battle, read_caught_icon
from battle.catch_calc import ball_probs, battle_context, format_line, chain_for

from core.game_time import current_game_minute, is_dusk_ball_night
from dex.location_reader import is_cave_location
from core.services import OcrServices, BattleServices, AppConfig

log = logging.getLogger("shakechecker")

@dataclass
class BattleFrame:
    frame: np.ndarray
    battle_reading_raw: Any
    battle_text_raw: Any
    enemy_count: int
    rect: QRect
    now: float
    location_text: str

@dataclass
class BattleUpdate:
    caught_species_id: int | None
    log_line: str | None
    is_multi: bool
    panel_state: dict[str, Any] | None

class BattleController:
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
        self.species_override = species_override
        self.status_override = status_override
        self.cal = cal
        self.balls = balls
        self.status_rates = status_rates
        self.pool = pool
        self.ocr = ocr
        self.config = config

        self.chat = ocr.chat_reader
        self.turns = services.turns
        self.hp = services.hp
        self.status = services.status
        self._chain = services.chain

        # Trackers
        self.cached: dict | None = None
        self._name_future: Future[dict | None] | None = None
        self.last_line = ""
        self._caught_printed = False
        self._catch_streak = 0
        self.dusk_active = False
        self._loc_read = False
        self._is_trainer = False
        self._trainer_decided = False
        self._ot_checked = False
        self._menu_raw = False
        self._menu_streak = 0
        self._menu_stable = False
        self._was_horde = False
        self._last_advance = 0.0
        self._last_chat_turn = 0
        self._last_chat_submit = 0.0
        self._battle_start = 0.0

    def reset(self, now: float) -> None:
        self.cached = None
        self._name_future = None
        self.last_line = ""
        self.turns.reset()
        self.hp.reset()
        self.status.reset()
        self.chat.reset()
        self._caught_printed = False
        self._catch_streak = 0
        self.dusk_active = False
        self._loc_read = False
        self._is_trainer = False
        self._trainer_decided = False
        self._ot_checked = False
        self._menu_raw = False
        self._menu_streak = 0
        self._menu_stable = False
        self._was_horde = False
        self._last_advance = 0.0
        self._last_chat_turn = 0
        self._last_chat_submit = 0.0
        self._battle_start = now



    def get_vision_hint(self) -> bool:
        """Returns the horde hint for the vision pipeline."""
        return self._was_horde

    def step(self, f: BattleFrame, timer_active: bool) -> BattleUpdate:
        frame = f.frame
        reading = f.battle_reading_raw
        bt = f.battle_text_raw
        now = f.now
        rect = f.rect

        if reading is None or bt is None:
            return BattleUpdate(caught_species_id=None, log_line=None, is_multi=False, panel_state=None)

        if reading.is_horde or f.enemy_count > 1:
            self._was_horde = True

        update = BattleUpdate(
            caught_species_id=None,
            log_line=None,
            is_multi=False,
            panel_state=None,
        )

        if not self._loc_read:
            self._loc_read = True
            if f.location_text:
                cave = is_cave_location(f.location_text)
                night = is_dusk_ball_night(current_game_minute())
                self.dusk_active = cave or night
                bits = [b for b, on in (("cave", cave), ("night", night)) if on]
                note = f" ({'+'.join(bits)} -> Dusk Ball boosted)" if bits else ""
                log.info(f"location: {f.location_text}{note}")

        asleep = reading.state is BattleState.SINGLE and reading.bars[0].status is Status.SLP

        chat_turn = self.chat.poll()
        if timer_active and now - self._last_chat_submit >= 1.5:
            self.chat.submit(frame)
            self._last_chat_submit = now

        if chat_turn is not None and chat_turn != self._last_chat_turn:
            self._last_chat_turn = chat_turn
            log.debug("chat: Turn %d  (counter Turn %d)", chat_turn, self.turns.turns_completed + 1)

        outcome = apply_chat_turn(
            self.turns,
            chat_turn,
            asleep=asleep,
            now=now,
            last_advance=self._last_advance,
            down_guard_s=self.config.turn_down_guard_s,
            battle_start=self._battle_start,
            start_grace_s=self.config.battle_start_grace_s,
        )
        if outcome in ("down", "up"):
            shown = self.turns.turns_completed + 1
            log.debug("chat corrected %s -> Turn %d", outcome.upper(), shown)

        self._menu_raw, self._menu_streak, self._menu_stable = debounce_menu(
            bt.menu_present,
            self._menu_raw,
            self._menu_streak,
            self._menu_stable,
            threshold=self.config.menu_stable_frames,
        )

        before = self.turns.turns_completed
        self.turns.observe_menu(self._menu_stable, bt.action)
        if self.turns.turns_completed > before:
            self._last_advance = now
            log.debug("menu -> Turn %d", self.turns.turns_completed + 1)

        stable = bt.menu_present and reading.state is BattleState.SINGLE
        if stable and not self._trainer_decided:
            bar = reading.bars[0]
            x_frac = bar.x / frame.shape[1]
            if is_horde_remnant(self._was_horde, x_frac, self.cal.hp_bar.remnant_x_frac):
                self._is_trainer = False
            else:
                self._is_trainer = is_trainer_battle(frame, bar, self.cal.trainer)
            self._trainer_decided = True

        self._catch_streak = self._catch_streak + 1 if bt.caught else 0
        if self._catch_streak >= 1 and not self._caught_printed and self.cached is not None:
            update.log_line = f"caught {self.cached['name']}!"
            self._caught_printed = True
            self._on_catch(self.cached)
            if self.cached.get("id"):
                update.caught_species_id = self.cached["id"]

        if reading.state is BattleState.SINGLE:
            if self._trainer_decided:
                self._update_single(f, update)
            else:
                update.panel_state = {
                    "dex_id": 0,
                    "name": "Reading battle...",
                    "catch_rate": None,
                    "turn": self.turns.turns_completed + 1,
                    "probs": {},
                    "level": None,
                    "status": None,
                    "hp_pct": reading.bars[0].hp_pct,
                    "alpha": False,
                }
        elif reading.state is BattleState.MULTI:
            update.is_multi = True
            if self.last_line != "multi":
                update.log_line = "multiple enemy bars (horde): waiting for one to remain"
                self.last_line = "multi"
            update.panel_state = {
                "dex_id": 0,
                "name": "Horde Battle",
                "catch_rate": None,
                "turn": self.turns.turns_completed + 1,
                "probs": {},
                "level": None,
                "status": None,
                "hp_pct": None,
                "alpha": False,
            }

        return update

    def _on_catch(self, enemy: dict) -> None:
        sid = enemy.get("id")
        if sid is None:
            return
        length = self._chain.record_catch(sid)
        log.debug("repeat chain: %s x%d", enemy.get("name"), length)

    def _update_single(self, f: BattleFrame, update: BattleUpdate) -> None:
        bar = f.battle_reading_raw.bars[0]
        hp_pct = self.hp.update(bar.hp_pct)
        status = self.status_override or self.status.update(bar.status.value)

        if self._is_trainer:
            update.panel_state = {
                "dex_id": 0,
                "name": "Trainer's Pokémon",
                "catch_rate": None,
                "turn": self.turns.turns_completed + 1,
                "probs": {},
                "level": None,
                "status": status if status != "none" else None,
                "hp_pct": hp_pct,
                "alpha": False,
                "is_trainer": True,
            }
            return

        if self.species_override is not None:
            self.cached = self.species_override
        elif self.cached is None:
            if self._name_future is None and self.ocr.name_reader is not None:
                self._name_future = self.pool.submit(self.ocr.name_reader.read, f.frame.copy(), bar)
            elif self._name_future is not None and self._name_future.done():
                sp = self._name_future.result()
                self._name_future = None
                if sp is not None:
                    self.cached = sp
                    rate_str = "??" if sp["catch_rate"] is None else sp["catch_rate"]
                    log.info(f"identified: {sp['name']} (catch rate {rate_str})")
        elif self.cached.get("level") is None and self.ocr.name_reader is not None:
            if self._name_future is None:
                self._name_future = self.pool.submit(self.ocr.name_reader.read, f.frame.copy(), bar)
            elif self._name_future is not None and self._name_future.done():
                sp = self._name_future.result()
                self._name_future = None
                if sp is not None and sp.get("level") is not None and sp["name"] == self.cached["name"]:
                    self.cached["level"] = sp["level"]

        if (
            not self._ot_checked
            and self.cached is not None
            and self.cached.get("id")
            and read_caught_icon(f.frame, bar, self.cal.caught_icon)
        ):
            self._ot_checked = True
            update.caught_species_id = self.cached["id"]

        turn_note = f"turn {self.turns.turns_completed + 1}"
        if self.turns.turns_asleep:
            turn_note += f", asleep {self.turns.turns_asleep}"

        if self.cached is None:
            line = f"{'?':12.12s} HP {hp_pct:5.1f}% [{status}]  ({turn_note})"
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
            }
        else:
            ctx = battle_context(
                self.cached,
                turns_completed=self.turns.turns_completed,
                turns_asleep=self.turns.turns_asleep,
                enemy_asleep=status == "slp",
                dusk_active=self.dusk_active,
                repeat_chain=chain_for(self._chain, self.cached),
            )
            probs_list = ball_probs(
                hp_pct, self.cached["catch_rate"], self.status_rates[status], self.balls, ctx
            )
            line = f"[{turn_note}] " + format_line(self.cached["name"], hp_pct, status, probs_list)
            
            overlay_probs = {name: p for name, p in probs_list if p is not None}
            update.panel_state = {
                "dex_id": self.cached.get("id", -1),
                "name": self.cached["name"],
                "catch_rate": self.cached["catch_rate"],
                "turn": self.turns.turns_completed + 1,
                "probs": overlay_probs,
                "level": self.cached.get("level"),
                "status": status,
                "hp_pct": hp_pct,
                "alpha": bool(self.cached.get("alpha")),
            }

        if line != self.last_line:
            if update.log_line:
                log.info(update.log_line) # print previous log line if there is one (like caught)
            update.log_line = line
            self.last_line = line
