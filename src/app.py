"""Milestone 1 console app: WAITING -> IDLE -> BATTLE state machine.

Watches the PokeMMO window and prints per-ball catch probabilities for the
current wild battle. Species (and status, until milestone 2 reads it from
screen) are given on the command line:

    python src/app.py --species Onix
    python src/app.py --species Onix --status slp
    python src/app.py --rate 45            # raw base catch rate instead
"""

from __future__ import annotations

import argparse
import enum
import json
import sys
import time
from pathlib import Path

from battle_reader import BattleState, Calibration, load_calibration, read_battle
from catch_calc import catch_probability
from window_capture import (
    WindowCapture,
    find_pokemmo_hwnd,
    get_client_rect,
    is_window_alive,
    set_dpi_awareness,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "data"

WAITING_POLL_S = 2.0
IDLE_FRAME_S = 0.5  # ~2 fps
BATTLE_FRAME_S = 0.2  # ~5 fps
BAR_GONE_TIMEOUT_S = 1.0


class AppState(enum.Enum):
    WAITING = "waiting"
    IDLE = "idle"
    BATTLE = "battle"


def load_balls() -> list[dict]:
    return json.loads((DATA / "balls.json").read_text("utf-8"))["balls"]


def load_status_rates() -> dict[str, float]:
    return json.loads((DATA / "status_rates.json").read_text("utf-8"))["rates"]


def lookup_catch_rate(species: str) -> int:
    entries = json.loads((DATA / "species_core.json").read_text("utf-8"))
    for e in entries:
        if e["name"].lower() == species.lower():
            return e["catch_rate"]
    raise SystemExit(f"unknown species: {species!r}")


def format_line(hp_pct: float, status: str, probs: list[tuple[str, float]]) -> str:
    balls = "  ".join(f"{name} {100 * p:5.1f}%" for name, p in probs)
    return f"HP {hp_pct:5.1f}% [{status}]  {balls}"


def run(base_rate: int, status: str, cal: Calibration) -> None:
    balls = load_balls()
    status_rate = load_status_rates()[status]
    capture = WindowCapture()
    state = AppState.WAITING
    hwnd: int | None = None
    last_seen_bar = 0.0
    last_line = ""

    print(f"base catch rate {base_rate}, status {status} (x{status_rate})")
    print("waiting for PokeMMO window...")

    while True:
        if state is AppState.WAITING:
            hwnd = find_pokemmo_hwnd()
            if hwnd is None:
                time.sleep(WAITING_POLL_S)
                continue
            print("PokeMMO window found")
            state = AppState.IDLE

        assert hwnd is not None
        rect = get_client_rect(hwnd)
        if rect is None:
            if not is_window_alive(hwnd):
                print("window lost, waiting...")
                state = AppState.WAITING
                hwnd = None
            time.sleep(WAITING_POLL_S)
            continue

        frame = capture.grab(rect)
        reading = read_battle(frame, cal)
        now = time.monotonic()

        if reading.state is BattleState.SINGLE:
            last_seen_bar = now
            if state is not AppState.BATTLE:
                state = AppState.BATTLE
                print("battle detected")
            bar = reading.bars[0]
            probs = [
                (
                    b["name"],
                    catch_probability(bar.hp_pct / 100.0, base_rate, b["rate"], status_rate),
                )
                for b in balls
            ]
            line = format_line(bar.hp_pct, status, probs)
            if line != last_line:
                print(line)
                last_line = line
        elif reading.state is BattleState.MULTI:
            last_seen_bar = now  # in battle, but not a catchable v1 scenario
            if last_line != "multi":
                print("multiple enemy bars (horde/double): ignored in v1")
                last_line = "multi"
        elif state is AppState.BATTLE and now - last_seen_bar > BAR_GONE_TIMEOUT_S:
            state = AppState.IDLE
            last_line = ""
            print("battle ended")

        time.sleep(BATTLE_FRAME_S if state is AppState.BATTLE else IDLE_FRAME_S)


def main() -> None:
    parser = argparse.ArgumentParser(description="ShakeChecker milestone-1 console output")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--species", help="species name, e.g. Onix")
    group.add_argument("--rate", type=int, help="base catch rate override")
    parser.add_argument(
        "--status",
        default="none",
        choices=sorted(load_status_rates()),
        help="enemy status (read manually until milestone 2)",
    )
    args = parser.parse_args()

    set_dpi_awareness()
    base_rate = args.rate if args.rate is not None else lookup_catch_rate(args.species)
    cal = load_calibration(ROOT / "calibration.toml")
    try:
        run(base_rate, args.status, cal)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
