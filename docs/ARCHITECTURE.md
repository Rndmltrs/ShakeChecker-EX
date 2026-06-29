# ShakeChecker Architecture & Execution Flow

This document outlines the core architecture, modular boundaries, and runtime execution flow of ShakeChecker following the v2 Sharding Refactor.

## Modular Boundaries

ShakeChecker is divided into four distinct domains, each strictly isolated:

- **`core/`**: Application state, path resolution, window capture, debugging, and the main `AppController` loop.
- **`battle/`**: Everything related to the active battle sequence (OCR readers, HP settling, turn tracking, and catch probability math).
- **`dex/`**: Everything related to the overworld (location tracking, encounter tables, caught tracking, and profile management).
- **`ui/`**: Pure PyQt6 presentation layers (overlays, settings panels, tray icon).

### Directory Tree

```text
data/                           ← Static game databases (encounters, species, etc.)
scripts/                        ← Developer tooling for fetching and parsing game data
src/
├── app.py                      ← The pure entry point and bootstrapper
├── battle/                     ← High-frequency encounter math and OCR
│   ├── battle_controller.py
│   ├── battle_detector.py
│   ├── battle_log.py
│   ├── battle_logic.py
│   ├── battle_reader.py
│   ├── catch_calc.py
│   ├── catch_chain.py
│   ├── hp_settler.py
│   ├── name_reader.py
│   ├── status_settler.py
│   └── turn_tracker.py
├── core/                       ← App state, timers, and the global controller
│   ├── account_store.py
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
> **The Pure-Impure Boundary:** UI components and state machines never perform complex calculations themselves. They delegate to pure, testable functions (e.g., `catch_calc.py`, `dex_formatters.py`) which return calculated state to be rendered.

## Execution Flow

The application boots in a strict sequence, transitioning from environment setup to a Qt-driven event loop.

### 1. The Entry Point (`src/app.py -> main()`)
Execution begins in `main()`. This function acts purely as an environment and configuration router.
- **Environment Prep:** Restricts the ONNX OCR engine to 1 thread to prevent CPU thrashing.
- **Argument Parsing:** Parses CLI arguments (`--debug`, `--account`, `--image`, etc.).
- **Diagnostic Routing:** If a diagnostic flag like `--list-windows` is passed, it executes the diagnostic task and exits immediately.
- **Handoff:** Loads base screen coordinates (`load_calibration`) and routes the user into the live application by calling `run()`.

### 2. The Bootstrapper (`src/app.py -> run()`)
This function physically wires the application's components together.
- **Instance Lock:** Acquires a process-wide Windows Mutex so only one instance of ShakeChecker can run.
- **Logging setup:** Configures the logger (`_LevelFormatter`) to output to the console or file.
- **Qt Engine:** Instantiates the `QApplication` (the core Qt framework) and suppresses harmless DPI warnings.
- **Service Construction:** Builds the `BattlePanel` and `DexPanel`, and uses a factory for the `DexSession`.
- **Controller Wiring:** Injects the panels, OCR engines, and trackers into the core `AppController`, which then constructs the `UIManager` to manage window docking and visibility.
- **System Tray:** Builds the tray menu and wires up the "Quit" action.
- **Liftoff:** Calls `loop.start()` to kickstart the controller's internal timer, and explicitly yields the main thread to Qt via `app.exec()`. Qt is now fully in charge of the process lifecycle.

### 3. The Ticker (`src/core/app_controller.py`)
Once `loop.start()` is called, the `AppController` schedules a continuous timer loop using Qt's `QTimer`.
- **`step()`:** Triggered repeatedly by the timer. Its only job is to provide an exception guard and delegate work to `_tick()`.
- **`_tick()`:** Serves as the State Machine router. It evaluates the current `AppState` and dynamically decides what work needs to be done on this exact frame.

## The State Machine (`_tick()`)
Depending on what state the app is in, `_tick()` splits into three distinct execution pipelines:

### WAITING State
The app has not yet detected the PokeMMO window.
- The tick loop fires very slowly (`WAITING_POLL_S`).
- Polls Windows using `find_pokemmo_hwnd()` until it successfully locks onto the game client.
- Once found, transitions to `IDLE`.

### IDLE State
The game is found, and the player is running around the overworld.
- The tick loop fires moderately (`IDLE_FRAME_S`).
- Checks every frame to see if a battle has initiated via visual cues. If so, transitions to `BATTLE`.
- Periodically submits background tasks to a thread pool to read the HUD, identify the current location, and update the Location/Encounter Dex overlay.

### BATTLE State
A wild encounter has started. The application shifts to a highly reactive mode to overlay live catch probabilities.

1. **High-Frequency Ticker:** The state machine accelerates the tick rate (`BATTLE_FRAME_S`, typically ~20ms) to track rapid UI changes during animations.
2. **Vision (Battle OCR):** Every frame, `_battle_step()` captures the window and submits it to the thread pool.
   - `read_battle()` (in `src/battle/battle_reader.py`) uses carefully calibrated coordinates to locate the wild Pokémon's health bar.
   - It reads the raw pixels to calculate the current HP percentage and scans for status condition icons (e.g., SLP, PAR).
3. **Signal Settling:** Because the game UI animates (health bars slide down, bars flash when hit), raw OCR data can flicker. 
   - `HpSettler` and `StatusSettler` filter out the noise, ensuring the math only runs when the health bar has stabilized.
4. **Enemy Resolution:** `src/battle/catch_calc.py -> resolve_enemy()` identifies what you are fighting. 
   - It uses `NameReader` to run OCR on the enemy's nameplate, fuzzy-matches it against the `species.json` database, and extracts the base catch rate and typing. (This can be overridden via CLI flags).
5. **Context & Math:** With the stable HP, status, and species known:
   - **Context Pipeline:** The app reads the battle chat log (`AsyncChatReader`) to parse the current turn number, and checks the local overworld state to see if it's currently night or if the player is in a cave (which triggers the 3x Dusk Ball multiplier).
   - **Probability Matrix:** `catch_calc.py -> ball_probs()` takes all this data and runs the exact Gen 5 catch formula for every single Pokéball type in the database.
6. **Overlay Rendering:** The final probability matrix is passed to the `UIManager`, which handles dynamic window docking and commands the `BattlePanel` to render the click-through overlay on top of the PokeMMO window in real-time.
7. **Exit Condition:** The tick loop continuously looks for the battle UI to disappear. Once gone for a set grace period, the state machine gracefully tears down the battle context, resets the thread pool, and drops back to `IDLE`.

## The Dex Pipeline

The Dex operates as an independent, asynchronous subsystem that runs alongside the main State Machine primarily during the `IDLE` state. Its goal is to passively track the player's location and display missing regional encounters.

1. **Trigger (`_update_dex`):** Fired periodically by `AppController` during the `IDLE` state.
2. **Vision (Location OCR):** The controller captures the screen and crops the top-left HUD (where map names appear). It submits this crop to the thread pool for parsing via `src/dex/location_reader.py`.
3. **Routing (`DexSession`):** The raw OCR text is returned and passed into `DexSession`. 
   - It fuzzy-matches the raw text against a massive mapping table (`area_index.json`) to resolve a canonical location ID.
4. **Data Aggregation:** `DexSession` cross-references the canonical location with `encounters.json` and the active user's `CaughtStore` (their local save data tracking what they've caught). 
   - It builds a `LocationView` model containing all potential wild encounters for that specific map, flagging which ones the user is missing.
5. **Presentation:** The `LocationView` is passed to `src/dex/dex_formatters.py` which formats it for the console, while the raw model is passed to the `UIManager`, which docks and renders the `DexPanel` overlay.
6. **Interactivity:** If the user clicks a Pokémon in the `DexPanel` to manually mark it as caught, the panel fires a callback back to the `SettingsController` and `AppController`, which instructs `DexSession` to mutate the `CaughtStore` (saving it to disk) and instantly re-triggers the presentation layer.

## System State Machine

The core `AppController` evaluates state every single tick. Transitions are strict and sequential:

```text
[ WAITING ] --(PokeMMO window found)--> [ IDLE ]
    ^                                     |   ^
    |                                     |   |
 (Window closed)         (Battle UI detected) (Battle UI lost)
    |                                     |   |
    +---------------------------------- [ BATTLE ]
```

- **WAITING:** Polling `win32gui` at a low frequency (~1 second). No active OCR.
- **IDLE:** Fast polling. Checking for battle entry conditions. Periodic background thread OCR for location tracking.
- **BATTLE:** Maximum frequency (~20ms). Continuous frame capture, OCR tracking for HP/Status, and active rendering of the `BattlePanel` overlay.

## Data Flow Pipeline

Data flows strictly in one direction from the game window to the UI layer.

```text
[ PokeMMO Window ]
        │
        ▼  (win32ui / OpenCV capture)
[ Frame Buffer ]
        │
        ├─▶ (If IDLE) ──▶ [ Location OCR ] ──▶ [ DexSession (Match & Filter) ] ──▶ [ DexPanel UI ]
        │
        └─▶ (If BATTLE) ─▶ [ Battle OCR ] ──▶ [ Hp/Status Settler (Noise Filter) ]
                                                       │
                                                       ▼
                            [ catch_calc.py (Probabilities & Context) ]
                                                       │
                                                       ▼
                                              [ BattlePanel UI ]
```

## Dependency Injection & Testability

ShakeChecker utilizes a strict Dependency Injection (DI) pattern with explicit keyword-only constructors to fully decouple the runtime loop and controllers from their services.

- **The Rule:** Controllers (like `AppController`, `BattleController`, `DexController`, and `VisionController`) must NEVER instantiate services, trackers, thread pools, or configuration variables internally. Furthermore, controllers are strictly prohibited from importing global state constants.
- **The Practice:** In `app.py`'s `run()` function (the Composition Root), the entire dependency graph is constructed. 
  - Constants are loaded into an `AppConfig` struct.
  - OCR readers are initialized and grouped into an `OcrServices` struct.
  - Battle trackers (`TurnTracker`, `HpSettler`, etc.) are grouped into a `BattleServices` struct.
  - These structs and explicit dependencies are then injected cleanly down the hierarchy via keyword-only arguments.
- **The Benefit:** This guarantees absolute determinism and makes testing trivial. Test suites can instantiate a completely pure `BattleController` in less than a millisecond by passing it a dummy `AppConfig` and a `MockOcrServices` that returns synthetic text, allowing full pipeline simulations without ever launching Qt or a PokeMMO window.

### Example: Mocking for Tests

Because dependencies are explicit, you can instantiate a controller using mocks (like `unittest.mock.MagicMock` or simple dummy objects) to test its logic in isolation.

```python
from unittest.mock import MagicMock
from core.services import AppConfig, OcrServices, BattleServices
from battle.battle_controller import BattleController

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

# 4. Instantiate the Controller purely
controller = BattleController(
    species_override=None,
    status_override=None,
    cal=mock_calibration,
    balls=mock_balls_list,
    status_rates=mock_rates,
    pool=MagicMock(), # Mock the thread pool
    ocr=mock_ocr,
    services=test_services,
    config=test_config
)

# Now you can pass in synthetic frames and assert the outputs!
```
## Configuration & Disk State

ShakeChecker reads from static data and writes to dynamic local storage.

- **Static Data (Read-Only):**
  - `data/species_core.json`: Base catch rates, typing, and names.
  - `data/encounters.json`: Global map data linking locations to wild encounters.
  - `data/area_index.json`: Fuzzy-matching dictionary used to resolve raw OCR HUD text to canonical locations.
  - `calibration.toml`: Hardcoded X/Y coordinate ratios mapping exactly where UI elements sit on the screen.

- **Dynamic State (Read/Write):**
  - `%APPDATA%/ShakeChecker/settings.json`: User preferences (UI scaling, theme choices). Loaded on boot by `Settings`.
  - `%APPDATA%/ShakeChecker/profiles/<account_name>_caught.json`: Tracks exactly which Pokémon a specific user has caught. Mutated by `DexSession`.
  - `%APPDATA%/ShakeChecker/shakechecker.log`: Rolling diagnostic log.
