"""Global, non-per-account UI preferences (userdata/settings.json).

Holds which Poke Balls to hide from the catch-rate overlay (stored as a set of
HIDDEN ball ids, not enabled ones, so a ball added to balls.json later shows by
default instead of being silently hidden) and the dex-panel mode. Empty file /
no file means all balls shown and the default dex mode.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

# Default for the dex "missing here" panel: keep caught species in the list
# (shown checked, at the bottom) rather than removing them. This is what users
# expected (see issue #16); False restores the old "hide caught" behaviour.
DEFAULT_KEEP_CAUGHT = True


class Settings:
    def __init__(self, path: Path, hidden_balls: set[str], keep_caught: bool) -> None:
        self.path = path
        self.hidden_balls = hidden_balls
        self.keep_caught = keep_caught

    @classmethod
    def load(cls, userdata_dir: Path | str) -> Settings:
        path = Path(userdata_dir) / "settings.json"
        hidden: set[str] = set()
        keep_caught = DEFAULT_KEEP_CAUGHT
        if path.exists():
            try:
                raw = json.loads(path.read_text("utf-8"))
                hidden = {str(b) for b in raw.get("hidden_balls", [])}
                keep_caught = bool(raw.get("keep_caught", DEFAULT_KEEP_CAUGHT))
            except (json.JSONDecodeError, OSError):
                pass  # corrupt/unreadable -> fall back to defaults
        return cls(path, hidden, keep_caught)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"hidden_balls": sorted(self.hidden_balls), "keep_caught": self.keep_caught}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")

    def is_ball_visible(self, ball_id: str) -> bool:
        return ball_id not in self.hidden_balls

    def toggle_ball(self, ball_id: str) -> bool:
        """Flip a ball's visibility, persist, and return True if it is now visible."""
        if ball_id in self.hidden_balls:
            self.hidden_balls.discard(ball_id)
        else:
            self.hidden_balls.add(ball_id)
        self.save()
        return ball_id not in self.hidden_balls

    def set_all_balls(self, ball_ids: Iterable[str], visible: bool) -> None:
        ids = set(ball_ids)
        if visible:
            self.hidden_balls -= ids
        else:
            self.hidden_balls |= ids
        self.save()

    def toggle_keep_caught(self) -> bool:
        """Flip the dex 'keep caught species' mode, persist, and return the new value."""
        self.keep_caught = not self.keep_caught
        self.save()
        return self.keep_caught
