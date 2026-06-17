"""Global, non-per-account UI preferences (userdata/settings.json).

Currently just which Poke Balls to hide from the catch-rate overlay. Stored as a
set of HIDDEN ball ids (not enabled ones), so a ball added to balls.json later
shows by default instead of being silently hidden. Empty file / no file means all
balls are shown.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path


class Settings:
    def __init__(self, path: Path, hidden_balls: set[str]) -> None:
        self.path = path
        self.hidden_balls = hidden_balls

    @classmethod
    def load(cls, userdata_dir: Path | str) -> Settings:
        path = Path(userdata_dir) / "settings.json"
        hidden: set[str] = set()
        if path.exists():
            try:
                raw = json.loads(path.read_text("utf-8"))
                hidden = {str(b) for b in raw.get("hidden_balls", [])}
            except (json.JSONDecodeError, OSError):
                pass  # corrupt/unreadable -> fall back to defaults (all shown)
        return cls(path, hidden)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"hidden_balls": sorted(self.hidden_balls)}
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
