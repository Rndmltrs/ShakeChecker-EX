# ruff: noqa: E402
import sys
from pathlib import Path

# Add src to python path so we can run this directly
root = Path(__file__).resolve().parent.parent
sys.path.append(str(root / "src"))

from PyQt6.QtWidgets import QApplication

from ui.battle_panel import BattlePanel
from ui.sprite_loader import SpriteLoader


def main():
    app = QApplication(sys.argv)

    loader = SpriteLoader()
    # Dummy balls
    balls = ["poke-ball", "great-ball", "ultra-ball"]
    panel = BattlePanel(ball_names=balls, loader=loader)

    # We apply scale first to initialize sizing
    panel.apply_scale(1.0)

    # Force mock data: Charizard (FIRE/FLYING)
    # Charizard dex_id = 6
    panel.show_battle(
        dex_id=6,
        name="Testizard",
        level=69,
        catch_rate=None,
        turn=1,
        probs={},
        status=None,
        hp_pct=100.0,
        alpha=False,
        is_trainer=True,
        enemy_types=("STEEL", "ELECTRIC"),
        is_empty=False,
        ev_yield={"special-attack": 3, "special-defense": 3},
    )

    panel.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
