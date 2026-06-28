# ShakeChecker — Fork Notice
**This repository is a personal fork of the original [ghostpixxel/ShakeChecker](https://github.com/ghostpixxel/ShakeChecker) project.**

> All credit for the concept, design, implementation, and research behind ShakeChecker belongs entirely to ghostpixxel. This fork exists only for personal development, experimentation, and launcher improvements.

### Key Fork Improvements
- **Persistent UI:** Dex and battle panels for a smoother, always‑visible overlay experience.
- **Dynamic Locations:** Intelligent location detection that correctly handles empty/no‑encounter areas.
- **Asynchronous Architecture:** Thread‑pooled backend with heavily optimized OCR calls for better performance.
- **Z‑Order Safety:** Safe overlay behavior ensuring panels never appear above unrelated application windows.
- **Enhanced Region Detection:** Powered by the underlying dynamic‑location system.
- **Expanded Settings:** Includes panel auto‑switching, caught‑status toggles, and region overrides.
- **Debug Tools:** One‑click debug capture that dumps the full game window with color‑coded regions and OCR slices.

---

### Advanced Developer Launcher
This fork includes a custom, standalone PowerShell bootstrap launcher (`launcher.ps1`) designed from the ground up to provide a frictionless experience for both users and developers. By executing the application purely from source, the launcher bypasses compiled executables, ensuring zero false-positives while maintaining a completely transparent environment.

Beyond just starting the app, the launcher acts as a fully integrated environment manager and developer toolkit. Features include:

- **Zero-Friction Setup:** Automatically validates your Python 3.11+ environment, provisions an isolated `.venv` workspace, and can even generate a desktop shortcut for quick access.
- **Faster Dependency Resolution:** Instead of relying on traditional pip installations, the launcher bootstraps `uv` (a Rust-based package installer) to download and install heavy, compiled dependencies (like OpenCV and PyQt6) concurrently with a sleek visual terminal UI.
- **Embedded REPL Terminal:** Drops you right into the active virtual environment with a custom terminal interface that supports command history mapping and safe execution of multi-line pasted text without dropping the UI.
- **Integrated Developer Tools:** A full CLI menu grants 1-click access to run automated linting and formatting via Ruff, static type checking with mypy, and unit testing with pytest.
- **Clean-Slate Environment Resets:** Includes built-in utilities to instantly wipe and rebuild your environment from scratch, ensuring you never waste time tracking down rogue dependencies.

*This makes testing, modifying, and using ShakeChecker faster and more developer-friendly.*

---

## 🔗 Original Project

**Author:** ghostpixxel  
**Repository:** https://github.com/ghostpixxel/ShakeChecker  
**Website & FAQ:** https://ghostpixxel.github.io/ShakeChecker/  
**Latest Release:** https://github.com/ghostpixxel/ShakeChecker/releases/latest

ShakeChecker is a passive, **read‑only** screen‑reading overlay for PokeMMO on
Windows.

It never sends input, reads memory, injects code, or interacts with the game
client in any way. It is strictly a visual overlay.

If you are looking for the official version of ShakeChecker,  
**please use the original repository linked above.**

---

## 📜 License & Attribution

ShakeChecker is licensed under the terms provided by the original author.  
All original copyrights, trademarks, and credits remain with **ghostpixxel**.
