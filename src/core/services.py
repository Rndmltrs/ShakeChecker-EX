from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from battle.name_reader import NameReader
from battle.battle_reader import BattleTextReader
from battle.battle_log import AsyncChatReader
from battle.turn_tracker import TurnTracker
from battle.hp_settler import HpSettler
from battle.status_settler import StatusSettler
from battle.catch_chain import CatchChain

@dataclass(frozen=True)
class OcrServices:
    name_reader: NameReader | None
    battle_text_reader: BattleTextReader
    chat_reader: AsyncChatReader

@dataclass(frozen=True)
class BattleServices:
    turns: TurnTracker
    hp: HpSettler
    status: StatusSettler
    chain: CatchChain

@dataclass(frozen=True)
class AppConfig:
    turn_down_guard_s: float
    battle_start_grace_s: float
    menu_stable_frames: int
    horde_enemy_count: int
    battle_anim_grace_s: float
    trainer_end_grace_s: float
    battle_end_grace_s: float
    dex_loc_interval_s: float
    loc_mask_stable_s: float
    idle_frame_s: float
    battle_frame_s: float
    waiting_poll_s: float
    dex_shown_max: int
    userdata_path: Path
