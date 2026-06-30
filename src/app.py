"""ShakeChecker: WAITING -> IDLE -> BATTLE state machine driving the overlay.

Watches the PokeMMO window and, during a wild battle, shows per-ball catch
probabilities in a click-through overlay docked to the game window (and mirrors
them to the console as a debug log). Species, HP%, status and turn are read from
the screen; everything can be overridden from the command line:

    python src/app.py                      # auto: identify species via OCR
    python src/app.py --species Onix        # override the detected species
    python src/app.py --species Onix --status slp   # override the detection too
    python src/app.py --rate 45             # raw base catch rate instead
    python src/app.py --image fixtures/x.png  # offline: analyse one PNG (no overlay)
    python src/app.py --list-windows        # diagnose window detection
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import win32api
import win32con
import win32event
import winerror
from PyQt6.QtCore import qInstallMessageHandler
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from battle.battle_log import AsyncChatReader, read_turn_number
from battle.battle_manager import BattleManager
from battle.battle_reader import (
    BattleState,
    BattleTextReader,
    Calibration,
    load_calibration,
    read_battle,
)
from battle.catch_calc import (
    ball_probs,
    battle_context,
    format_line,
    load_balls,
    load_status_rates,
    resolve_enemy,
)
from battle.catch_chain import CatchChain
from battle.hp_settler import HpSettler
from battle.name_reader import NameReader, lookup_species
from battle.status_settler import StatusSettler
from battle.turn_tracker import TurnTracker
from core import paths
from core.app_controller import AppController
from core.config import (
    BATTLE_ANIM_GRACE_S,
    BATTLE_END_GRACE_S,
    BATTLE_FRAME_S,
    BATTLE_START_GRACE_S,
    DEX_LOC_INTERVAL_S,
    IDLE_FRAME_S,
    LOC_MASK_STABLE_S,
    MENU_STABLE_FRAMES,
    TRAINER_END_GRACE_S,
    TURN_DOWN_GUARD_S,
    WAITING_POLL_S,
)
from core.paths import (
    SPECIES_INDEX_PATH,
    TEMPLATES_DIR,
    USERDATA,
)
from core.services import AppConfig, BattleServices, OcrServices
from core.settings_controller import SettingsController
from core.settings_store import Settings
from core.utils import parse_coord
from core.vision_controller import VisionController
from core.window_capture import (
    WINDOW_TITLE,
    WindowCapture,
    find_pokemmo_hwnd,
    fold_confusables,
    get_client_rect,
    iter_visible_windows,
    set_dpi_awareness,
    title_matches,
)
from dex.dex_controller import DexController
from dex.dex_factory import build_dex_session
from dex.location_reader import is_cave_location, read_location
from ui.battle_panel import BattlePanel
from ui.dex_panel import DexPanel
from ui.tray_menu import build_tray

log = logging.getLogger("shakechecker")


class _LevelFormatter(logging.Formatter):
    """Plain message for INFO, '[dbg]'-prefixed for DEBUG."""

    def format(self, record: logging.LogRecord) -> str:
        msg = ("[dbg] " if record.levelno <= logging.DEBUG else "") + record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return msg


def setup_logging(debug: bool) -> None:
    log.handlers.clear()
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    log.propagate = False
    handler: logging.Handler
    if sys.stdout is not None:
        handler = logging.StreamHandler(sys.stdout)
    else:
        try:
            logfile = paths.userdata_dir() / "shakechecker.log"
            logfile.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(logfile, mode="w", encoding="utf-8")
        except OSError:
            handler = logging.NullHandler()
    handler.setFormatter(_LevelFormatter())
    log.addHandler(handler)


def analyze_image(
    image_path: str, species_override: dict | None, status_override: str | None, cal: Calibration
) -> None:
    """Offline mode: run the full pipeline on a single PNG and print the result."""
    import cv2

    frame = cv2.imread(image_path)
    if frame is None:
        raise SystemExit(f"cannot read image: {image_path!r}")
    status_rates = load_status_rates()
    balls = load_balls()
    name_reader = None if species_override else NameReader(cal.name, SPECIES_INDEX_PATH)
    reading = read_battle(frame, cal)
    print(f"{image_path}\n  state: {reading.state.value}  (bars detected: {len(reading.bars)})")
    if reading.state is BattleState.MULTI:
        print("  -> horde/double battle: ignored in v1 (overlay would stay hidden)")
    for i, bar in enumerate(reading.bars):
        status = status_override or bar.status.value
        enemy = resolve_enemy(species_override, name_reader, frame, bar)
        label = enemy["name"] if enemy else "?"
        tag = f"bar {i}: " if len(reading.bars) > 1 else ""
        print(
            f"  {tag}{label}  HP {bar.hp_pct:.1f}% ({bar.color.value})  status: {bar.status.value}"
        )
        if reading.state is BattleState.SINGLE and enemy is not None:
            turn = read_turn_number(frame, cal.chat)
            turns_completed = turn - 1 if turn else 0
            h, w = frame.shape[:2]
            ly0 = parse_coord(cal.location.top, h)
            ly1 = parse_coord(cal.location.bottom, h)
            lx0 = parse_coord(cal.location.left, w)
            lx1 = parse_coord(cal.location.right, w)
            dusk = is_cave_location(read_location(frame[ly0:ly1, lx0:lx1]))
            ctx = battle_context(enemy, turns_completed=turns_completed, dusk_active=dusk)
            probs = ball_probs(bar.hp_pct, enemy["catch_rate"], status_rates[status], balls, ctx)
            turn_note = f"[turn {turn}] " if turn else "[turn ?] "
            print("  " + turn_note + format_line(label, bar.hp_pct, status, probs))


def list_windows() -> None:
    """Diagnostic: print every visible top-level window and mark PokeMMO matches."""
    set_dpi_awareness()
    windows = iter_visible_windows()
    matches = 0
    print(f"{len(windows)} visible top-level windows (looking for {WINDOW_TITLE!r}):\n")
    for hwnd, title in windows:
        is_match = title_matches(title)
        rect = get_client_rect(hwnd)
        size = f"{rect.width}x{rect.height} @ ({rect.left},{rect.top})" if rect else "no rect"
        mark = " <-- MATCH" if is_match else ""
        if is_match:
            matches += 1
        print(f"  hwnd={hwnd:>10}  {size:28s}  {title!r}{mark}")
        folded = fold_confusables(title)
        if is_match and folded != title:
            cps = " ".join(f"U+{ord(c):04X}" for c in title)
            print(f"             homoglyphs; folds to {folded!r}\n             codepoints: [{cps}]")
    picked = find_pokemmo_hwnd()
    print(f"\n{matches} title match(es). find_pokemmo_hwnd() -> {picked}")
    if picked is not None:
        print(f"  selected client rect: {get_client_rect(picked)}")


SINGLE_INSTANCE_NAME = "ShakeChecker_SingleInstance_Mutex"


def acquire_single_instance(name: str = SINGLE_INSTANCE_NAME) -> int | None:
    handle = win32event.CreateMutex(None, False, name)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        win32api.CloseHandle(handle)
        return None
    return handle


def run(
    species_override: dict | None,
    status_override: str | None,
    cal: Calibration,
    account: str | None = None,
    debug: bool = False,
) -> None:
    setup_logging(debug)
    lock = acquire_single_instance()
    if lock is None:
        log.info("ShakeChecker is already running; this instance will exit")
        win32api.MessageBox(
            0,
            "ShakeChecker is already running.",
            "ShakeChecker",
            win32con.MB_OK | win32con.MB_ICONINFORMATION,
        )
        return

    def qt_message_handler(mode, context, message):
        if (
            "SetProcessDpiAwarenessContext" in message
            or "DPI_AWARENESS_CONTEXT" in message
            or "WindowDoesNotAcceptFocus" in message
        ):
            return
        print(message, file=sys.stderr)

    qInstallMessageHandler(qt_message_handler)

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    icon = QIcon(str(paths.DATA_DIR / "shakechecker.ico"))
    app.setWindowIcon(icon)

    dex = build_dex_session(account)

    cores = os.cpu_count() or 4
    workers = max(1, min(4, cores - 2))
    pool = ThreadPoolExecutor(max_workers=workers)
    loc_pool = ThreadPoolExecutor(max_workers=1)

    config = AppConfig(
        turn_down_guard_s=TURN_DOWN_GUARD_S,
        battle_start_grace_s=BATTLE_START_GRACE_S,
        menu_stable_frames=MENU_STABLE_FRAMES,
        horde_enemy_count=5,
        battle_anim_grace_s=BATTLE_ANIM_GRACE_S,
        trainer_end_grace_s=TRAINER_END_GRACE_S,
        battle_end_grace_s=BATTLE_END_GRACE_S,
        dex_loc_interval_s=DEX_LOC_INTERVAL_S,
        loc_mask_stable_s=LOC_MASK_STABLE_S,
        idle_frame_s=IDLE_FRAME_S,
        battle_frame_s=BATTLE_FRAME_S,
        waiting_poll_s=WAITING_POLL_S,
        userdata_path=USERDATA,
    )

    ocr = OcrServices(
        name_reader=None if species_override else NameReader(cal.name, SPECIES_INDEX_PATH),
        battle_text_reader=BattleTextReader(cal.battle_text, TEMPLATES_DIR),
        chat_reader=AsyncChatReader(cal.chat),
    )

    services = BattleServices(
        turns=TurnTracker(),
        hp=HpSettler(),
        status=StatusSettler(),
        chain=CatchChain(),
    )

    balls = load_balls()
    status_rates = load_status_rates()
    settings = Settings.load(USERDATA)
    settings_controller = SettingsController(
        settings=settings,
        balls=balls,
        config=config,
        get_region=lambda: dex.region if dex else None,
        on_update=lambda x: None,
    )

    battle_manager = BattleManager(
        species_override=species_override,
        status_override=status_override,
        cal=cal,
        balls=balls,
        status_rates=status_rates,
        pool=pool,
        ocr=ocr,
        services=services,
        config=config,
    )

    dex_controller = DexController(
        dex_session=dex,
        loc_pool=loc_pool,
        config=config,
    )

    vision_controller = VisionController(
        ocr=ocr,
        battle_reader_func=read_battle,
        pool=pool,
        cal=cal,
        config=config,
    )

    capture = WindowCapture(0)

    battle_panel = BattlePanel([b["name"] for b in balls])
    dex_panel = DexPanel() if dex else None

    loop = AppController(
        pool=pool,
        loc_pool=loc_pool,
        ocr=ocr,
        capture=capture,
        battle_panel=battle_panel,
        settings_controller=settings_controller,
        battle_manager=battle_manager,
        dex_controller=dex_controller,
        vision_controller=vision_controller,
        config=config,
        species_override=species_override,
        status_override=status_override,
        cal=cal,
        dex=dex,
        dex_panel=dex_panel,
    )

    settings_controller.on_update = loop._handle_settings_update

    _tray = build_tray(icon, app.quit, paths.APP_VERSION)
    loop.start()
    try:
        code = app.exec()
    finally:
        loop.ocr.chat_reader.shutdown()
        _tray.hide()
    sys.exit(code)


def restrict_onnx_threads() -> None:
    try:
        import onnxruntime
    except ImportError:
        return
    original_init = onnxruntime.SessionOptions.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.intra_op_num_threads = 1
        self.inter_op_num_threads = 1

    onnxruntime.SessionOptions.__init__ = patched_init


def main() -> None:
    restrict_onnx_threads()
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="ShakeChecker console output")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--species", help="override the auto-detected species")
    group.add_argument("--rate", type=int, help="override with a raw base catch rate")
    parser.add_argument(
        "--status",
        default=None,
        choices=sorted(load_status_rates()),
        help="override auto-detected status",
    )
    parser.add_argument("--image", help="offline mode: analyze a single PNG")
    parser.add_argument(
        "--list-windows", action="store_true", help="diagnostic: list visible windows"
    )
    parser.add_argument("--account", help="PokeMMO account/character for dex")
    parser.add_argument("--debug", action="store_true", help="verbose diagnostics")
    args = parser.parse_args()

    if args.list_windows:
        list_windows()
        return

    species_override = None
    if args.species is not None:
        species_override = lookup_species(args.species)
    elif args.rate is not None:
        species_override = {"name": f"rate {args.rate}", "catch_rate": args.rate, "types": []}

    cal = load_calibration(paths.CALIBRATION_PATH)
    if args.image:
        analyze_image(args.image, species_override, args.status, cal)
        return

    set_dpi_awareness()
    try:
        run(species_override, args.status, cal, account=args.account, debug=args.debug)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
