"""ShakeChecker console app: WAITING -> IDLE -> BATTLE state machine.

Watches the PokeMMO window and prints per-ball catch probabilities for the
current wild battle. HP%, HP colour and enemy status are read from the screen;
the species (base catch rate) is given on the command line:

    python src/app.py --species Onix       # status auto-detected from screen
    python src/app.py --species Onix --status slp   # override the detection
    python src/app.py --rate 45            # raw base catch rate instead
    python src/app.py --list-windows       # diagnose window detection
"""

from __future__ import annotations

import argparse
import enum
import io
import json
import sys
import time
from pathlib import Path

from battle_reader import BattleState, Calibration, load_calibration, read_battle
from catch_calc import catch_probability
from window_capture import (
    WINDOW_TITLE,
    WindowCapture,
    find_pokemmo_hwnd,
    fold_confusables,
    get_client_rect,
    is_window_alive,
    iter_visible_windows,
    set_dpi_awareness,
    title_matches,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "data"

WAITING_POLL_S = 2.0
IDLE_FRAME_S = 0.5  # ~2 fps
BATTLE_FRAME_S = 0.2  # ~5 fps
# Debounce: the enemy HP bar briefly vanishes during attack/status animations,
# so only treat the battle as over once the bar has been gone continuously for
# this long. Otherwise the state flickers battle->idle->battle mid-fight.
BATTLE_END_GRACE_S = 2.5


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


def ball_probs(
    hp_pct: float, base_rate: int, status_rate: float, balls: list[dict]
) -> list[tuple[str, float]]:
    return [
        (b["name"], catch_probability(hp_pct / 100.0, base_rate, b["rate"], status_rate))
        for b in balls
    ]


def analyze_image(
    image_path: str, base_rate: int, status_override: str | None, cal: Calibration
) -> None:
    """Offline mode: run the full pipeline on a single PNG and print the result.

    Lets you verify reader + probabilities + output format without the live
    game (same code path the live loop uses)."""
    import cv2

    frame = cv2.imread(image_path)
    if frame is None:
        raise SystemExit(f"cannot read image: {image_path!r}")
    status_rates = load_status_rates()
    balls = load_balls()
    reading = read_battle(frame, cal)
    print(f"{image_path}")
    print(f"  state: {reading.state.value}  (bars detected: {len(reading.bars)})")
    if reading.state is BattleState.MULTI:
        print("  -> horde/double battle: ignored in v1 (overlay would stay hidden)")
    for i, bar in enumerate(reading.bars):
        status = status_override or bar.status.value
        tag = f"bar {i}: " if len(reading.bars) > 1 else ""
        print(f"  {tag}HP {bar.hp_pct:.1f}% ({bar.color.value})  status: {bar.status.value}")
        if reading.state is BattleState.SINGLE:
            probs = ball_probs(bar.hp_pct, base_rate, status_rates[status], balls)
            print("  " + format_line(bar.hp_pct, status, probs))


def list_windows() -> None:
    """Diagnostic: print every visible top-level window and mark PokeMMO
    matches, so window-detection problems can be seen directly."""
    set_dpi_awareness()
    windows = iter_visible_windows()
    matches = 0
    print(
        f"{len(windows)} visible top-level windows (looking for titles starting with "
        f"{WINDOW_TITLE!r}):\n"
    )
    for hwnd, title in windows:
        is_match = title_matches(title)
        rect = get_client_rect(hwnd)
        size = (
            f"{rect.width}x{rect.height} @ ({rect.left},{rect.top})" if rect else "no client rect"
        )
        mark = " <-- MATCH" if is_match else ""
        if is_match:
            matches += 1
        print(f"  hwnd={hwnd:>10}  {size:28s}  {title!r}{mark}")
        folded = fold_confusables(title)
        if is_match and folded != title:
            cps = " ".join(f"U+{ord(c):04X}" for c in title)
            print(f"             title uses non-ASCII homoglyphs; folds to {folded!r}")
            print(f"             codepoints: [{cps}]")
    picked = find_pokemmo_hwnd()
    print(f"\n{matches} title match(es). find_pokemmo_hwnd() -> {picked}")
    if picked is not None:
        print(f"  selected client rect: {get_client_rect(picked)}")


def run(base_rate: int, status_override: str | None, cal: Calibration) -> None:
    balls = load_balls()
    status_rates = load_status_rates()
    capture = WindowCapture()
    state = AppState.WAITING
    hwnd: int | None = None
    last_seen_bar = 0.0
    last_line = ""

    src = f"manual override: {status_override}" if status_override else "auto-detected from screen"
    print(f"base catch rate {base_rate}, status {src}")
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
            status = status_override or bar.status.value
            probs = ball_probs(bar.hp_pct, base_rate, status_rates[status], balls)
            line = format_line(bar.hp_pct, status, probs)
            if line != last_line:
                print(line)
                last_line = line
        elif reading.state is BattleState.MULTI:
            last_seen_bar = now  # in battle, but not a catchable v1 scenario
            if last_line != "multi":
                print("multiple enemy bars (horde/double): ignored in v1")
                last_line = "multi"
        elif state is AppState.BATTLE and now - last_seen_bar > BATTLE_END_GRACE_S:
            state = AppState.IDLE
            last_line = ""
            print("battle ended")

        time.sleep(BATTLE_FRAME_S if state is AppState.BATTLE else IDLE_FRAME_S)


def main() -> None:
    # Ball names contain non-ASCII (Poké Ball); force UTF-8 on the Windows console.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="ShakeChecker milestone-1 console output")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--species", help="species name, e.g. Onix")
    group.add_argument("--rate", type=int, help="base catch rate override")
    parser.add_argument(
        "--status",
        default=None,
        choices=sorted(load_status_rates()),
        help="override the auto-detected enemy status (default: read from screen)",
    )
    parser.add_argument(
        "--image",
        help="offline mode: analyze a single PNG (e.g. a fixture) instead of the live window",
    )
    parser.add_argument(
        "--list-windows",
        action="store_true",
        help="diagnostic: list visible windows and PokeMMO matches, then exit",
    )
    args = parser.parse_args()

    if args.list_windows:
        list_windows()
        return

    if args.species is None and args.rate is None:
        parser.error("one of --species or --rate is required (or use --list-windows)")

    base_rate = args.rate if args.rate is not None else lookup_catch_rate(args.species)
    cal = load_calibration(ROOT / "calibration.toml")

    if args.image:
        analyze_image(args.image, base_rate, args.status, cal)
        return

    set_dpi_awareness()
    try:
        run(base_rate, args.status, cal)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
