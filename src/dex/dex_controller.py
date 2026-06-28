from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np

from core.services import AppConfig
from dex import location_reader
from dex.dex_session import DexSession
from dex.dex_structures import LocationView


@dataclass
class DexFrame:
    hud_crop: np.ndarray
    now: float
    in_battle: bool


@dataclass
class DexUpdate:
    location_text: str
    location_view: LocationView | None
    log_line: str | None
    is_loading: bool


class DexController:
    def __init__(
        self, *, dex_session: DexSession | None, loc_pool: ThreadPoolExecutor, config: AppConfig
    ):
        self.dex = dex_session
        self.loc_pool = loc_pool
        self.config = config

        self._loc_ocr_raw = ""
        self._last_hud = ""
        self._last_loc_check = 0.0
        self._last_loc_trigger = 0.0

        self._last_seen_mask: np.ndarray | None = None
        self._mask_stable_since = 0.0
        self._last_loc_mask: np.ndarray | None = None
        self._mask_changed_since: float | None = None

        self._loc_future: Future[str] | None = None
        self._pending_loc_mask: np.ndarray | None = None

        self._queued_loc_frame: np.ndarray | None = None
        self._queued_loc_mask: np.ndarray | None = None

    def record_caught(self, species_id: int) -> bool:
        """Proxy to record a catch in the dex session."""
        if self.dex is not None:
            return self.dex.record_caught(species_id)
        return False

    def reset_loc_check(self) -> None:
        """Force the next overworld frame to re-evaluate location."""
        self._last_loc_check = 0.0

    def override_region(self, region: str | None) -> None:
        if self.dex is not None:
            self.dex.seed_region(region)

    def load_profile(self, account: str) -> None:
        if self.dex is not None:
            from dex.dex_structures import CaughtStore

            self.dex.set_caught(CaughtStore.for_account(self.config.userdata_path, account))

    def step(self, frame: DexFrame) -> DexUpdate:
        if self.dex is None:
            return self._step_build_update()

        mask = location_reader.extract_location_mask(frame.hud_crop)
        if mask is not None:
            self._step_mask_stabilization(mask, frame.now)
            self._step_queue_ocr(mask, frame.hud_crop, frame.now)
            self._step_process_ocr_result(mask, frame.now)

        return self._step_build_update()

    def _mask_changed(self, m1, m2) -> bool:
        if m1 is None or m2 is None:
            return True
        diff = cv2.absdiff(m1, m2)
        changed_pixels = np.count_nonzero(diff)
        return bool(changed_pixels > 50)

    def _step_mask_stabilization(self, mask: np.ndarray, now: float) -> None:
        if self._mask_changed(mask, self._last_seen_mask):
            self._last_seen_mask = mask
            self._mask_stable_since = now

        changed = self._mask_changed(mask, self._last_loc_mask)

        if not changed:
            self._mask_changed_since = None
            self._queued_loc_frame = None
            self._queued_loc_mask = None
        elif self._mask_changed_since is None:
            self._mask_changed_since = now

    def _step_queue_ocr(self, mask: np.ndarray, hud_crop: np.ndarray, now: float) -> None:
        dex_due = now - self._last_loc_check >= self.config.dex_loc_interval_s
        is_stable = now - self._mask_stable_since >= self.config.loc_mask_stable_s
        changed = self._mask_changed(mask, self._last_loc_mask)
        ready = is_stable and changed

        if ready and dex_due:
            if np.count_nonzero(mask) < (mask.size * 0.005):
                self._last_loc_mask = mask
                self._mask_changed_since = None
                self._queued_loc_frame = None
                self._queued_loc_mask = None
            elif self._loc_future is None:
                trigger_latency = now - self._last_loc_trigger
                from core.ocr_engine import _log_performance

                _log_performance("location_trigger_latency", trigger_latency, (0, 0))

                self._last_loc_trigger = now
                self._loc_future = self.loc_pool.submit(
                    location_reader.read_location, hud_crop.copy()
                )
                self._pending_loc_mask = mask.copy()
            else:
                if self._queued_loc_frame is None:
                    self._queued_loc_frame = hud_crop.copy()
                    self._queued_loc_mask = mask.copy()
                self._last_loc_mask = mask

    def _step_process_ocr_result(self, mask: np.ndarray, now: float) -> None:
        if self._loc_future is not None and self._loc_future.done():
            ocr_result = self._loc_future.result() if self._loc_future else ""
            self._loc_future = None

            if not self._mask_changed(mask, self._pending_loc_mask):
                self._last_loc_mask = mask
                self._last_loc_check = now
                self._loc_ocr_raw = ocr_result
            else:
                if self._queued_loc_frame is None:
                    self._loc_ocr_raw = ocr_result
                self._last_loc_check = 0.0

            if (
                self._queued_loc_frame is not None
                and self._queued_loc_mask is not None
                and now - self._last_loc_check >= self.config.dex_loc_interval_s
            ):
                self._loc_future = self.loc_pool.submit(
                    location_reader.read_location, self._queued_loc_frame
                )
                self._pending_loc_mask = self._queued_loc_mask
                self._queued_loc_frame = None
                self._queued_loc_mask = None

    def _step_build_update(self) -> DexUpdate:
        is_loading = self._loc_future is not None

        # Resolve the location to a view if it changed or if we need a dummy view
        location_view = None
        log_line = None

        if self.dex is not None:
            if not self._last_hud and self._loc_future is not None:
                # Placeholder UI while first location reads
                from core.game_time import Period

                location_view = LocationView(
                    route="Reading location...",
                    region="Please wait",
                    period=Period.DAY,
                    season=0,
                    entries=[],
                )
            else:
                hud_name = self._loc_ocr_raw
                # Debounce OCR jitter
                if self._last_hud and hud_name:
                    import re

                    from rapidfuzz import fuzz

                    def extract_digits(s: str) -> tuple[str, ...]:
                        return tuple(re.findall(r"\d+", s))

                    if (
                        extract_digits(hud_name) == extract_digits(self._last_hud)
                        and fuzz.ratio(hud_name.lower(), self._last_hud.lower()) >= 75.0
                        and not self.dex.is_exact_location(hud_name)
                    ):
                        hud_name = self._last_hud
                        self._loc_ocr_raw = hud_name

                # Normal update
                view = self.dex.on_location(hud_name)
                if view is not None:
                    location_view = view
                    if view.route != self._last_hud:
                        self._last_hud = view.route
                        entries_count = len(view.entries)
                        log_line = f"dex: {view.route} ({entries_count} missing)"

        return DexUpdate(
            location_text=self._loc_ocr_raw,
            location_view=location_view,
            log_line=log_line,
            is_loading=is_loading,
        )
