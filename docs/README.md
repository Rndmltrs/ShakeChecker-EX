# ShakeChecker — Project Fork

**This repository is a hard fork of the original [ghostpixxel/ShakeChecker](https://github.com/ghostpixxel/ShakeChecker) project.**

> All credit for the original concept, design, and research behind ShakeChecker belongs to GhostPixxel. This fork has been independently re-architected to address performance limitations and improve maintainability.

---

## Key Fork Improvements

* **Real-time Computer Vision:** Optimized use of OpenCV and RapidFuzz to perform high-speed, fuzzy-matched OCR and state detection on a live game feed—all without hooking into the game client.
* **Asynchronous Architecture:** Replaced synchronous loops with a non-blocking, thread-pooled backend. Heavy OCR processing is offloaded to background threads, ensuring the UI remains fluid and responsive even during intensive tasks.
* **Architectural Decoupling:** Fully refactored into a modular package structure (`battle/`, `dex/`, `ui/`, `core/`) to improve feature isolation and long-term maintainability.
* **Enhanced Battle Panel:** Displays pokemon element types, EV gains, and also type advantages during trainer battles.
* **Improved Location Logic:** Dynamically parses locations without encounters with enhanced region detection and name resolution.
* **Overlay & Z-Order Safety:** Implemented strict overlay handling to ensure UI panels remain correctly populated with relevant information without interfering with unrelated application windows.
* **Developer-Centric Debugging:** Integrated one-click debug tools that export game window captures with color-coded region slices and OCR output for rapid, visual troubleshooting.
* **Granular User Control:** Added modular settings, including panel auto-switching, caught-status toggles, and region overrides—decoupled from the UI logic for a cleaner experience.

# ShakeChecker Installation & Setup Guide

This guide covers how to set up the ShakeChecker application on your system. The process is automated to ensure it runs safely without affecting your core system files or registry.

## 1. Initial Setup
* Ensure you have **Python 3.11 or higher** installed on your computer.
* Download the project folder and locate the `run_launcher.cmd` file.
* Double-click `run_launcher.cmd` to begin the automated setup.

## 2. Environment Configuration
* **Automated Validation**: The system will automatically verify your Python installation.
* **Safe Sandboxing**: It will create a local `.venv` folder, which keeps all application files and dependencies sandboxed to the project directory, preventing any system-wide clutter.

## 3. Application Workflow
* **Running the App**: The launcher provides a menu where you can start the application directly.
* **Building a Standalone Executable**: If you prefer to run the app without the Python environment, use **Option 3** in the menu. This compiles the project into a portable standalone `.exe` file, which will be created in the `dist\ShakeChecker\` folder.
* **Desktop Shortcut**: After a successful first installation, the launcher will ask if you would like to create a shortcut on your desktop for quick access.
  
---

## Advanced Developer Launcher
This fork features a custom PowerShell bootstrap launcher (`launcher.ps1`) designed to provide a professional, transparent environment for both users and developers.

* **Zero-Friction Setup:** Automatically validates Python 3.11+ requirements, provisions an isolated `.venv` workspace, and manages desktop shortcuts.
* **High-Speed Dependency Management:** Utilizes `uv` (a Rust-based installer) to resolve and install complex dependencies (OpenCV, PyQt6) with massive concurrency gains compared to standard `pip`.
* **Integrated Dev Toolkit:** A full CLI menu provides 1-click access to production-grade tooling:
    * **Automated Linting/Formatting:** `ruff`.
    * **Static Type Checking:** `mypy`.
    * **Unit Testing:** `pytest`.
* **Environment Resilience:** Includes utilities for "clean-slate" environment resets, ensuring dependency conflicts are resolved instantly.
* **Location & Species Updater:** Quickly update relevant data for locations and species from PokeMMO Hub.
* <https://github.com/PokeMMO-Tools/pokemmo-hub>

---

## 🔗 Original Project

**Author:** GhostPixxel  
**Repository:** [ghostpixxel/ShakeChecker](https://github.com/ghostpixxel/ShakeChecker)  
**Website & FAQ:** [ShakeChecker Website](https://ghostpixxel.github.io/ShakeChecker/)  

ShakeChecker is a passive, **read-only** screen-reading overlay for PokeMMO on Windows. It does not send input, read memory, or inject code. If you are looking for the original, official version of ShakeChecker, **please use the repository linked above.**

---

## Disclaimer

ShakeChecker is a fan-made tool and is not affiliated with, endorsed, or sponsored by PokeMMO. Pokémon and all related names, sprites and trademarks belong to Nintendo, Game Freak and The Pokémon Company. This is an unofficial project; all rights to their respective owners.
