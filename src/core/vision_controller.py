from dataclasses import dataclass
from typing import Any, Callable
from concurrent.futures import Future, ThreadPoolExecutor
import numpy as np

from core.services import OcrServices, AppConfig

@dataclass
class VisionUpdate:
    hud_present: bool
    enemy_count: int
    battle_text_raw: Any | None
    battle_reading_raw: Any | None
    debounce_state: float

class VisionController:
    def __init__(
        self,
        *,
        ocr: OcrServices,
        battle_reader_func: Callable,
        pool: ThreadPoolExecutor,
        cal: Any,
        config: AppConfig,
    ):
        self.ocr = ocr
        self.read_battle = battle_reader_func
        self.pool = pool
        self.cal = cal
        self.config = config

        self._bt_future: Future[Any] | None = None
        self._battle_future: Future[Any] | None = None

        self._last_bt: Any | None = None
        self._last_reading: Any | None = None

        # Debounce state for noisy frames (generic visual debounce)
        self._debounce_state: float = 0.0

    def reset(self) -> None:
        self._last_bt = None
        self._last_reading = None
        self._debounce_state = 0.0
        # We don't cancel futures because they are running, but we will ignore them
        # or just let them resolve and overwrite. AppController resetting state is enough.

    def step(self, frame: np.ndarray, needs_reading: bool, hint: Any = None) -> VisionUpdate | None:
        # 1. Poll futures
        if self._bt_future is not None and self._bt_future.done():
            self._last_bt = self._bt_future.result()
            self._bt_future = None

        if self._battle_future is not None and self._battle_future.done():
            self._last_reading = self._battle_future.result()
            self._battle_future = None

        # 2. Submit new jobs
        if self._bt_future is None:
            self._bt_future = self.pool.submit(self.ocr.battle_text_reader.read, frame.copy())

        if needs_reading and getattr(self, "_battle_future", None) is None:
            # Blindly pass hint to the injected reader function
            self._battle_future = self.pool.submit(self.read_battle, frame.copy(), self.cal, horde=hint)

        if self._last_bt is None:
            return None

        # 3. Detect generic HUD presence
        from battle.battle_reader import is_battle_ui_present
        hud_present = is_battle_ui_present(frame, self.cal.battle_ui)
        
        # Determine enemy count based on raw reading
        enemy_count = 0
        if self._last_reading is not None:
            if hasattr(self._last_reading, 'bars'):
                enemy_count = len(self._last_reading.bars)
            elif getattr(self._last_reading, 'is_horde', False):
                enemy_count = self.config.horde_enemy_count

        # Update and return raw vision data
        return VisionUpdate(
            hud_present=hud_present,
            enemy_count=enemy_count,
            battle_text_raw=self._last_bt,
            battle_reading_raw=self._last_reading if needs_reading else None,
            debounce_state=self._debounce_state
        )
