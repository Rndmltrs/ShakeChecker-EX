from __future__ import annotations

import pytest

from sprite_loader import (
    SPRITES_DIR,
    SpriteLoader,
    ball_slug,
    ball_sprite_path,
    species_sprite_path,
)

# --- pure path resolution (no Qt) ---


def test_ball_slug_handles_accent_and_spaces():
    assert ball_slug("Poké Ball") == "poke-ball"
    assert ball_slug("Great Ball") == "great-ball"
    assert ball_slug("Dream Ball") == "dream-ball"


def test_species_path_prefers_gif_over_png(tmp_path):
    base = tmp_path
    (base / "pokemon").mkdir()
    (base / "pokemon" / "7.png").write_bytes(b"x")
    (base / "pokemon" / "7.gif").write_bytes(b"x")
    assert species_sprite_path(7, base).name == "7.gif"


def test_species_path_falls_back_to_png(tmp_path):
    base = tmp_path
    (base / "pokemon").mkdir()
    (base / "pokemon" / "1000.png").write_bytes(b"x")
    assert species_sprite_path(1000, base).name == "1000.png"


def test_species_path_none_when_missing(tmp_path):
    (tmp_path / "pokemon").mkdir()
    assert species_sprite_path(1052, tmp_path) is None


def test_vendored_sprites_resolve():
    # against the real committed sprites: an early id is animated, a Gen-6 id is
    # static, a PokeMMO event-custom id has nothing, all 12 balls exist.
    assert species_sprite_path(1).suffix == ".gif"  # Bulbasaur, animated
    assert species_sprite_path(1000).suffix == ".png"  # static fallback
    assert species_sprite_path(1052) is None  # DEBUG_ST1000, no sprite
    for ball in ("Poké Ball", "Quick Ball", "Dream Ball", "Net Ball"):
        assert ball_sprite_path(ball) is not None, ball


# --- Qt loading (needs a QGuiApplication) ---


@pytest.fixture(scope="module")
def qt_app():
    try:
        from PyQt6.QtGui import QGuiApplication
    except Exception:  # pragma: no cover
        pytest.skip("PyQt6 unavailable")
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


def test_ball_pixmap_loads_and_scales(qt_app):
    loader = SpriteLoader()
    pm = loader.ball_pixmap("Poké Ball", 24)
    assert not pm.isNull()
    assert pm.height() == 24


def test_species_movie_for_animated_id(qt_app):
    loader = SpriteLoader()
    mv = loader.species_movie(1, 64)  # Bulbasaur .gif
    assert mv is not None
    assert mv.scaledSize().height() == 64


def test_species_movie_none_for_static_id(qt_app):
    loader = SpriteLoader()
    assert loader.species_movie(1000, 64) is None  # only a .png exists


def test_species_pixmap_static_and_placeholder(qt_app):
    loader = SpriteLoader()
    static = loader.species_pixmap(1000, 64)
    assert not static.isNull()
    placeholder = loader.species_pixmap(1052, 64)  # no sprite -> "?" placeholder
    assert not placeholder.isNull()


def test_cache_returns_same_object(qt_app):
    loader = SpriteLoader()
    a = loader.ball_pixmap("Great Ball", 24)
    b = loader.ball_pixmap("Great Ball", 24)
    assert a is b


def test_sprites_dir_points_at_vendored_assets():
    assert (SPRITES_DIR / "items" / "poke-ball.png").exists()
