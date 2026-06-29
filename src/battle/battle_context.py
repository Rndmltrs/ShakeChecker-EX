"""Per-battle context and historical timeline for the BattleManager.

These dataclasses replace the ~16 scattered boolean/numeric flags that lived on
BattleController. They are plain, mutable dataclasses — no logic, no I/O. The
Manager owns and mutates them; the UI consumes the final BattleUpdate output.

Kept in a separate module so they can be imported by tests without pulling in
the full Manager (and its heavy dependencies).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BattleContext:
    """All mutable state that spans a single battle's lifetime.

    Reset at ``BattleStarted``; updated each frame by the Manager.
    """

    # ── Species cache ─────────────────────────────────────────────────────
    # The resolved species dict from the name-reader OCR (or species_override).
    # None while unidentified; populated in _on_ocr_result().
    species: dict | None = None

    # ── Battle-lifetime timing ─────────────────────────────────────────────
    battle_start: float = 0.0  # monotonic time at BattleStarted
    last_advance: float = 0.0  # last time TurnTracker.turns_completed incremented
    last_chat_turn: int = 0  # last unique turn number seen from chat OCR
    last_chat_submit: float = 0.0  # last time a chat-OCR frame was submitted

    # ── Classification flags ──────────────────────────────────────────────
    # is_trainer: locked by the Manager once trainer detection resolves.
    # Starts False; set True on confirmed trainer strip; set False after
    # menu_streak > trainer_decide_frames with no confirmed strip.
    is_trainer: bool = False
    # trainer_decided: True once is_trainer is locked (either direction).
    # While False, the Manager stays in SCANNING and shows "Reading battle…".
    trainer_decided: bool = False

    # ── Dusk Ball state ───────────────────────────────────────────────────
    # Set once per battle from the location OCR on the first stable frame.
    dusk_active: bool = False
    location_set: bool = False  # True once location OCR has been applied

    # ── OT / catch flags ──────────────────────────────────────────────────
    # caught_icon_seen: True once the OT Poké Ball icon has been detected.
    # Triggers a dex.record_caught() call; only fires once per battle.
    caught_icon_seen: bool = False
    # caught_logged: True once a "caught X!" log line has been emitted.
    # Prevents the same log line from firing again if the catch banner flickers.
    caught_logged: bool = False

    # ── Config refs ───────────────────────────────────────────────────────
    # Stored here so transition methods can access them without referencing
    # the global config object.
    down_guard_s: float = 0.0  # turn_down_guard_s from AppConfig
    start_grace_s: float = 0.0  # battle_start_grace_s from AppConfig


@dataclass
class BattleTimeline:
    """Snapshot of the most recently committed values for change detection.

    The Manager compares the current frame's readings against this to decide
    whether to push a new log line or UI update, suppressing redundant output.
    Separate from BattleContext because it tracks *output* state, not *input*
    state — it is updated AFTER the Manager has committed a new value.
    """

    last_species_name: str | None = None  # name of the last confirmed species
    last_hp: float = 0.0  # last settled HP percentage
    last_status: str = "none"  # last committed status string
    last_menu: bool = False  # last debounced menu_stable value
    last_trainer_flag: bool = False  # last emitted is_trainer value
    last_log_line: str = ""  # last line printed to the console log
