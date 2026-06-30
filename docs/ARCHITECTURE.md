# ShakeChecker Architecture & Execution Flow

This document outlines the core architecture, modular boundaries, and runtime execution flow of ShakeChecker following the v3 Battle Pipeline Refactor.

## Modular Boundaries

ShakeChecker is divided into four distinct domains, each strictly isolated:

- **`core/`**: Application state, path resolution, window capture, debugging, and the main `AppController` loop.
- **`battle/`**: Everything related to the active battle sequence — pixel reading, species identification, turn tracking, and catch probability math.
- **`dex/`**: Everything related to the overworld (location tracking, encounter tables, caught tracking, and profile management).
- **`ui/`**: Pure PyQt6 presentation layers (overlays, settings panels, tray icon).

### Directory Tree

```text
data/                           ← Static game databases (encounters, species, etc.)
scripts/                        ← Developer tooling for fetching and parsing game data
src/
├── app.py                      ← The pure entry point and bootstrapper
├── battle/                     ← High-frequency encounter math and OCR
│   ├── battle_context.py       ← BattleContext + BattleTimeline (per-battle state)
│   ├── battle_log.py           ← Async chat OCR reader
│   ├── battle_logic.py         ← Pure, stateless logic functions (testable without Qt)
│   ├── battle_manager.py       ← Unified lifecycle manager + internal FSM
│   ├── battle_reader.py        ← Low-level CV bar/status reading functions
│   ├── battle_vision.py        ← Pixel→semantics layer (produces BattleScene)
│   ├── catch_calc.py           ← Catch probability math (Gen 5 formula)
│   ├── catch_chain.py          ← Repeat-catch chain tracking
│   ├── hp_settler.py           ← HP bar debounce filter
│   ├── name_reader.py          ← Name-banner OCR + species resolver
│   ├── status_settler.py       ← Status badge debounce filter
│   ├── turn_tracker.py         ← Turn count (menu + chat sources)
│   └── type_chart.py           ← Gen 5 type effectiveness matrix
├── core/                       ← App state, timers, and the global controller
│   ├── app_controller.py
│   ├── config.py
│   ├── debug_dump.py
│   ├── game_time.py
│   ├── ocr_engine.py
│   ├── paths.py
│   ├── services.py
│   ├── settings_controller.py
│   ├── settings_store.py
│   ├── utils.py
│   ├── vision_controller.py
│   └── window_capture.py
├── dex/                        ← Low-frequency overworld and collection logic
│   ├── dex_controller.py
│   ├── dex_factory.py
│   ├── dex_formatters.py
│   ├── dex_session.py
│   ├── dex_structures.py
│   ├── dex_tracker.py
│   └── location_reader.py
└── ui/                         ← Presentation layer (PyQt6)
    ├── battle_panel.py
    ├── dex_panel.py
    ├── settings_panel.py
    ├── sprite_loader.py
    ├── tray_menu.py
    ├── ui_components.py
    ├── ui_icons.py
    ├── ui_manager.py
    ├── ui_overlay.py
    └── ui_theme.py
```

> [!IMPORTANT]
> **The Pure-Impure Boundary:** No code above the Vision layer ever imports `cv2` or `numpy` for battle purposes. Pixel operations are fully sealed inside `battle_vision.py`. UI components and state machines never perform complex calculations; they delegate to pure, testable functions (e.g., `catch_calc.py`, `battle_logic.py`, `dex_formatters.py`).

## Execution Flow

The application boots in a strict sequence, transitioning from environment setup to a Qt-driven event loop.

### 1. The Entry Point (`src/app.py → main()`)
Execution begins in `main()`. This function acts purely as an environment and configuration router.
- **Environment Prep:** Restricts the ONNX OCR engine to 1 thread to prevent CPU thrashing.
- **Argument Parsing:** Parses CLI arguments (`--debug`, `--account`, `--image`, etc.).
- **Diagnostic Routing:** If a diagnostic flag like `--list-windows` is passed, it executes the diagnostic task and exits immediately.
- **Handoff:** Loads base screen coordinates (`load_calibration`) and routes the user into the live application by calling `run()`.

### 2. The Bootstrapper (`src/app.py → run()`)
This function physically wires the application's components together.
- **Instance Lock:** Acquires a process-wide Windows Mutex so only one instance of ShakeChecker can run.
- **Logging setup:** Configures the logger to output to the console or file.
- **Qt Engine:** Instantiates the `QApplication` (the core Qt framework) and suppresses harmless DPI warnings.
- **Service Construction:** Builds the `BattlePanel` and `DexPanel`, and uses a factory for the `DexSession`.
- **Controller Wiring:** Injects the panels, OCR engines, and trackers into `AppController`, which constructs the `UIManager` to manage window docking and visibility.
- **System Tray:** Builds the tray menu and wires the "Quit" action.
- **Liftoff:** Calls `loop.start()` to kickstart the controller's internal timer, then yields the main thread to Qt via `app.exec()`.

### 3. The Ticker (`src/core/app_controller.py`)
Once `loop.start()` is called, `AppController` schedules a continuous timer loop using Qt's `QTimer`.
- **`step()`:** Triggered repeatedly by the timer. Provides an exception guard and delegates to `_tick()`.
- **`_tick()`:** The State Machine router. Evaluates the current `AppState` and decides what work to do this frame.

## The State Machine (`_tick()`)

### WAITING State
The app has not yet detected the PokeMMO window.
- Polls Windows using `find_pokemmo_hwnd()` until it successfully locks onto the game client.
- Once found, transitions to `IDLE`.

### IDLE State
The game is found; the player is in the overworld.
- Checks every frame for a battle via visual cues. If detected, transitions to `BATTLE`.
- Periodically submits background tasks to identify the current location and update the Dex overlay.

### BATTLE State
A battle is active. The application shifts to a highly reactive mode.

1. **Frame Capture:** Captures the game window at ~20ms intervals.
2. **Vision (BattleScene):** The raw frame is passed to `BattleVision.step()`, which reads all HP bars, checks for trainer strips, diffs the name banner for Pokémon swaps, and emits a `BattleScene` — a single semantic snapshot of the frame with no numpy arrays.
3. **BattleManager.step():** Consumes the `BattleScene` and drives the full battle lifecycle.
4. **BattleUpdate → UI:** The Manager returns a `BattleUpdate` every frame, which `AppController` passes to `UIManager` to dock and render the `BattlePanel` overlay.
5. **Exit Condition:** The Manager tracks grace periods and a brightness-spike detector; once the battle signals are gone for long enough, it emits an IDLE detector state and `AppController` tears down the battle context.

## The Battle Pipeline (Detail)

### Data Flow

```text
[ PokeMMO Window ]
        │
        ▼ (WindowCapture)
[ Raw BGR Frame ]
        │
        ▼ (BattleVision.step)
[ BattleScene ]          ← Pure semantics: booleans + scalars only, no pixel arrays
        │
        ▼ (BattleManager.step)
┌──────────────────────────────────────────────┐
│  battle_logic.py  ─── is_in_battle()         │
│                   ─── debounce_battle()       │
│                   ─── debounce_menu()         │
│                   ─── battle_end_grace()      │
│                   ─── apply_chat_turn()       │
│                                              │
│  TurnTracker  ──── observe_menu()            │
│               ──── observe() / set_turn()    │
│                                              │
│  _BattleState FSM ── SCANNING                │
│                   ── IDENTIFYING             │
│                   ── TRACKING                │
│                   ── SWAPPING                │
└──────────────────────────────────────────────┘
        │
        ▼
[ BattleUpdate ]
        │
        ▼ (UIManager → BattlePanel)
[ Overlay ]
```

### BattleVision Layer (`battle_vision.py`)

`BattleVision` is the **only** code that touches raw frames after capture. It seals every pixel operation:

| Operation | Source function |
|---|---|
| HP bar reading | `battle_reader.read_enemy_bars()` |
| Horde-remnant check | `battle_logic.is_horde_remnant()` |
| Trainer strip detection | `battle_reader.is_trainer_battle()` |
| Name-banner pixel diff | `cv2.absdiff` on half-res crop |
| OT caught-icon check | `battle_reader.read_caught_icon()` |

Output is a `BattleScene` dataclass containing only booleans, scalars, and the typed `BarReading` tuples from `battle_reader`. Nothing above this layer imports `cv2` or `numpy`.

### BattleManager Internal FSM (`battle_manager.py`)

The Manager contains a private `_BattleState` enum and named transition methods. Each transition is documented with the exact game logic it represents:

```
SCANNING     → waiting for trainer/wild classification + stable menu
IDENTIFYING  → OCR submitted to thread pool; species not yet locked
TRACKING     → species locked; normal HP/status/turn loop
SWAPPING     → pixel diff detected; OCR verifying; OLD species held on UI
```

**Transition methods:**
- `_on_trainer_decided(is_trainer)` — locks the wild/trainer classification after the stability guard passes.
- `_on_menu_stable()` — first stable menu appearance; transitions `SCANNING → IDENTIFYING`.
- `_on_name_changed(scene)` — pixel diff triggered; transitions `TRACKING → SWAPPING`.
- `_on_ocr_result(sp)` — OCR thread completed; locks species (`IDENTIFYING → TRACKING`) or confirms/denies a swap (`SWAPPING → TRACKING`).

**Pure logic delegation:**

| Task | Delegated to |
|---|---|
| Battle membership gate | `battle_logic.is_in_battle()` + `debounce_battle()` |
| Menu debounce | `battle_logic.debounce_menu()` |
| Turn advancement | `TurnTracker.observe_menu()` |
| Chat OCR correction | `battle_logic.apply_chat_turn()` |
| End-of-battle grace | `battle_logic.battle_end_grace()` |
| Catch probability | `catch_calc.ball_probs()` |

The Manager does **not** re-implement any of this math; it wires inputs to these pure functions and consumes their outputs.

## The Dex Pipeline

The Dex operates as an independent, asynchronous subsystem running alongside the main State Machine primarily during the `IDLE` state.

1. **Trigger:** Fired periodically by `AppController` during `IDLE`.
2. **Vision (Location OCR):** Crops the top-left HUD and submits it to `location_reader.py`.
3. **Routing (`DexSession`):** Raw OCR text is fuzzy-matched against `area_index.json` to resolve a canonical location ID.
4. **Data Aggregation:** `DexSession` cross-references the location with `encounter_index.json` and the user's `CaughtStore`, building a `LocationView` of missing encounters.
5. **Presentation:** `dex_formatters.py` formats for the console; `UIManager` docks and renders the `DexPanel` overlay.
6. **Interactivity:** Clicking a Pokémon in the panel fires a callback to `DexSession` to mutate the `CaughtStore` and immediately re-render.

## System State Diagram

```text
[ WAITING ] --(PokeMMO window found)--> [ IDLE ]
    ^                                     |   ^
    |                                     |   |
 (Window closed)         (Battle UI detected) (Battle UI lost)
    |                                     |   |
    +---------------------------------- [ BATTLE ]
```

- **WAITING:** Polling `win32gui` at low frequency (~1 second). No active OCR.
- **IDLE:** Fast polling. Checking for battle entry. Periodic background OCR for location.
- **BATTLE:** Maximum frequency (~20ms). Continuous frame capture, `BattleVision` + `BattleManager` pipeline, live `BattlePanel` overlay.

## Dependency Injection & Testability

ShakeChecker uses strict Dependency Injection with explicit keyword-only constructors.

- **The Rule:** Controllers never instantiate services, thread pools, or configuration variables internally. They never import global state constants.
- **The Practice:** In `app.py`'s `run()` (the Composition Root), the full dependency graph is constructed. Constants are loaded into an `AppConfig` struct; OCR readers into `OcrServices`; battle trackers (`TurnTracker`, `HpSettler`, etc.) into `BattleServices`. These are injected cleanly down the hierarchy.
- **The Benefit:** Absolute determinism and trivial testability. A `BattleManager` can be instantiated in isolation with a dummy `AppConfig` and a mock `OcrServices`, allowing full pipeline simulations without launching Qt or a game window.

### Example: Mocking for Tests

```python
from unittest.mock import MagicMock
from core.services import AppConfig, OcrServices, BattleServices
from battle.battle_manager import BattleManager

# 1. Create a dummy configuration
test_config = AppConfig(
    turn_down_guard_s=0.0,
    battle_start_grace_s=0.0,
    menu_stable_frames=1,
    horde_enemy_count=5,
    # ... fill other required floats/ints
)

# 2. Mock the heavy OCR readers
mock_ocr = OcrServices(
    name_reader=MagicMock(),
    battle_text_reader=MagicMock(),
    chat_reader=MagicMock()
)

# 3. Use real (but isolated) trackers
test_services = BattleServices(
    turns=TurnTracker(),
    hp=HpSettler(),
    status=StatusSettler(),
    chain=CatchChain(),
)

# 4. Instantiate the Manager purely
manager = BattleManager(
    species_override=None,
    status_override=None,
    cal=mock_calibration,
    balls=mock_balls_list,
    status_rates=mock_rates,
    pool=MagicMock(),
    ocr=mock_ocr,
    services=test_services,
    config=test_config
)

# Now pass in synthetic BattleScene objects and assert the BattleUpdate outputs!
```

## Configuration & Disk State

ShakeChecker reads from static data and writes to dynamic local storage.

- **Static Data (Read-Only):**
  - `data/species_index.json`: Base catch rates, typing, and names.
  - `data/encounter_index.json`: Global map data linking locations to wild encounters.
  - `data/area_index.json`: Fuzzy-matching dictionary used to resolve raw OCR HUD text to canonical locations.
  - `calibration.toml`: X/Y coordinate ratios mapping exactly where UI elements sit on the screen.

- **Dynamic State (Read/Write):**
  - `%APPDATA%/ShakeChecker/settings.json`: User preferences (UI scaling, theme choices). Loaded on boot by `Settings`.
  - `%APPDATA%/ShakeChecker/profiles/<account_name>_caught.json`: Tracks exactly which Pokémon a specific user has caught. Mutated by `DexSession`.
  - `%APPDATA%/ShakeChecker/shakechecker.log`: Rolling diagnostic log.
