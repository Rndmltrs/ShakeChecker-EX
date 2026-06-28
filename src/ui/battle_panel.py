"""PyQt6 catch-rate overlay: frameless, translucent, click-through, always-on-top.

Layout (top to bottom): Pokemon sprite + name (+ level / status badge); base
catch rate + turn; HP; one row per Poke Ball = sprite + name + catch %, the %
coloured by likelihood (<35% red, 35-66% yellow, >=66% green). Hidden outside
battles. Docks to the top corner inside the game window's client area.

Sizes are expressed at scale 1.0 (the maximum) and shrunk by apply_scale() when
the game window is small, so the overlay never overflows a small battle view and
never grows larger than its design size.

Read-only: the overlay only displays. Click-through means input passes straight
to the game underneath; the overlay never receives or sends any input.

Run standalone to preview the look without the game:
    python src/battle_panel.py
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QMovie
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.sprite_loader import SpriteLoader
from ui.ui_components import BattleBallRow
from ui.ui_overlay import (
    MIN_SCALE,
    BaseOverlay,
)

# Base (scale 1.0) sizes in logical px. apply_scale() multiplies these; 1.0 is the
# cap, so the overlay is never larger than this.
BASE_PANEL_W = 236  # fits the widest obtainable name + " Lv.100" at 16px bold
BASE_SPRITE_H = 24
BASE_BALL_H = 20
BASE_NAME_PX = 15
BASE_SUB_PX = 11
BASE_ROW_PX = 13
BASE_STATUS_PX = 10
BASE_LEVEL_PX = 11
BASE_MARGIN_X = 12
BASE_MARGIN_Y = 10
BASE_COL_SPACING = 3
BASE_HEADER_SPACING = 8
BASE_GLOW_BLUR = 14
BASE_ROW_SPACING = 6
BASE_PCT_MINW = 48


# probability colour thresholds (fraction 0-1) -> hex
_RED, _YELLOW, _GREEN = "#ff5555", "#ffcc44", "#55dd66"


def subheader_text(catch_rate: int | None, turn: int) -> str:
    # catch_rate is None for species with no known rate (e.g. roaming Latias/
    # Latios/Mesprit/Cresselia): show it as a mystery "??".
    rate = "??" if catch_rate is None else str(catch_rate)
    return f"Rate: {rate}  ·  Turn {turn}"


# Status code -> (label, badge background) following the in-game colour scheme.
_STATUS_BADGE = {
    "slp": ("SLP", "#7a7a7a"),
    "par": ("PAR", "#b59a00"),
    "psn": ("PSN", "#9b4dca"),
    "brn": ("BRN", "#d4602f"),
    "frz": ("FRZ", "#3f9fd4"),
}


def status_badge(status: str | None) -> tuple[str, str] | None:
    """(label, background colour) for a status, or None for no status (-> hidden)."""
    return _STATUS_BADGE.get(status.lower()) if status else None


def visible_ball_order(
    ball_names: list[str], probs: dict[str, float], hidden: set[str]
) -> list[str]:
    """Balls to show in the overlay, best catch rate first. Drops hidden balls and
    any without a probability; ties keep the original ball order (stable sort)."""
    shown = [n for n in ball_names if n not in hidden and probs.get(n) is not None]
    return sorted(shown, key=lambda n: probs[n], reverse=True)


def unknown_ball_order(ball_names: list[str], hidden: set[str]) -> list[str]:
    """Balls to show when the catch rate is unknown (no probabilities to sort by):
    every non-hidden ball, in the original order."""
    return [n for n in ball_names if n not in hidden]


class BattlePanel(BaseOverlay):
    def __init__(self, ball_names: list[str], loader: SpriteLoader | None = None) -> None:
        super().__init__(
            mode_name="Battle Mode", mode_tooltip="Switch to Dex Mode", base_panel_w=BASE_PANEL_W
        )
        self._loader = loader or SpriteLoader()
        self._movie: QMovie | None = None
        self._current_dex: int | None = None  # avoid restarting the GIF every frame
        self._ball_names = list(ball_names)
        self._ball_rows: dict[str, BattleBallRow] = {}  # one reorderable row widget per ball
        self._hidden_names: set[str] = set()  # balls the user chose to hide
        self._last_order: list[str] | None = None  # skip reordering when unchanged

        self.get_ball_state: Callable[[], tuple[list[tuple[str, str]], set[str]]] | None = None
        self.on_toggle_ball: Callable[[str], None] | None = None
        self.on_set_all_balls: Callable[[bool], None] | None = None
        self.on_force_refresh: Callable[[], None] | None = None
        self._balls: QWidget | None = None

        self._sprite_h = BASE_SPRITE_H
        self._level_px = BASE_LEVEL_PX
        self._init_header()

    def _on_refresh_clicked(self) -> None:
        if self.on_force_refresh:
            self.on_force_refresh()

    def setup_middle_btn(self) -> None:
        self._balls_btn = self._add_header_btn("Select Pokeballs to show", self._on_balls_click)

    def _init_header(self) -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QHBoxLayout, QLabel

        self._header = QHBoxLayout()
        self._sprite = QLabel()
        self._sprite.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        # Red glow/aura behind the sprite to mark an Alpha Pokémon
        self._alpha_glow = QGraphicsDropShadowEffect(self)
        self._alpha_glow.setOffset(0, 0)
        self._alpha_glow.setColor(QColor(235, 45, 45))
        self._sprite.setGraphicsEffect(self._alpha_glow)
        self._alpha_glow.setEnabled(False)
        self._name = QLabel(" ")
        self._name.setTextFormat(Qt.TextFormat.RichText)  # bold name + small "Lv.N"
        # Ignored width: a long name clips instead of widening the panel.
        self._name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._name.setObjectName("PrimaryText")
        self._status = QLabel()
        self._status.setVisible(False)

        from ui.ui_components import SpinnerButton

        self._refresh_btn = SpinnerButton(15)
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)

        self._header.addWidget(self._sprite)
        self._header.addWidget(self._name, 1)
        self._header.addWidget(self._refresh_btn)
        self._header.addWidget(self._status)
        self._header.setContentsMargins(0, 0, 0, 0)
        self._col.addLayout(self._header)

        self._sub = QLabel("")
        self._sub.setTextFormat(Qt.TextFormat.RichText)
        self._sub.setObjectName("SecondaryTextDark")
        self._sub.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._col.addWidget(self._sub)

        self._hp = QLabel("")
        self._hp.setObjectName("PrimaryText")
        self._hp.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._col.addWidget(self._hp)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("Divider")
        self._col.addWidget(line)

        self._balls_container = QWidget()
        self._balls_layout = QVBoxLayout(self._balls_container)
        self._balls_layout.setContentsMargins(0, 0, 0, 0)
        self._col.addWidget(self._balls_container, 1)

        # "no battles detected" placeholder - built as a plain ball-style row so
        # it gets identical height and spacing to the real ball rows.
        self._empty_row = QWidget()
        _row_e = QHBoxLayout(self._empty_row)
        _row_e.setContentsMargins(0, 0, 0, 0)
        self._empty_label = QLabel()
        self._empty_label.setTextFormat(Qt.TextFormat.RichText)
        self._empty_label.setText("no battles detected")
        self._empty_label.setObjectName("SecondaryText")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        _row_e.addWidget(self._empty_label)
        self._balls_layout.addWidget(self._empty_row)  # always first child

        # one row per ball: icon + name (left) + percent (right). Each row is its own
        # widget so show_battle() can reorder (best % on top) and hide filtered balls.
        for name in self._ball_names:
            row = BattleBallRow(name)
            self._balls_layout.addWidget(row)
            self._ball_rows[name] = row

        self._balls_layout.addStretch(1)

        self.apply_scale(1.0)  # set fonts, sprites, widths at full size

    # --- public API ---

    def apply_scale(self, scale: float) -> None:
        """Resize the whole overlay by `scale` (<=3.0). Cheap no-op if unchanged."""
        scale = max(MIN_SCALE, min(3.0, scale))
        if abs(scale - self._scale) < 0.02:
            return
        self._scale = scale

        px = self._px
        self._panel_w = px(BASE_PANEL_W)
        self.setFixedWidth(self._panel_w)
        self._sprite_h = px(BASE_SPRITE_H)
        self._level_px = px(BASE_LEVEL_PX)

        name_font = self._font(px(BASE_NAME_PX), bold=True)
        row_font = self._font(px(BASE_ROW_PX))
        sub_font = self._font(px(BASE_SUB_PX))
        status_font = self._font(px(BASE_STATUS_PX), bold=True)

        self._name.setFont(name_font)
        self._sub.setFont(sub_font)
        self._hp.setFont(sub_font)
        self._status.setFont(status_font)
        self._empty_label.setFont(row_font)

        self._mode_label.setFont(self._font(px(13), bold=True))

        self._sprite.setFixedHeight(self._sprite_h)
        self._alpha_glow.setBlurRadius(px(BASE_GLOW_BLUR))
        ball_h = px(BASE_BALL_H)
        pct_minw = px(BASE_PCT_MINW)
        row_spacing = px(BASE_ROW_SPACING)

        self._empty_row.setFixedHeight(ball_h)
        for name, row in self._ball_rows.items():
            pixmap = self._loader.ball_pixmap(name, ball_h)
            row.apply_scale(row_font, pixmap, ball_h, pct_minw, row_spacing)

        isz = px(15)  # BASE_ICON_PX from dex_panel
        self._scale_icon_btn(self._mode_btn, "swords", isz)
        self._scale_icon_btn(self._balls_btn, "ball", isz)
        self._scale_icon_btn(self._settings_btn, "gear", isz)
        self._refresh_btn.set_size(isz)

        self._col.setContentsMargins(
            px(BASE_MARGIN_X), px(BASE_MARGIN_Y), px(BASE_MARGIN_X), px(BASE_MARGIN_Y)
        )
        self._col.setSpacing(px(BASE_COL_SPACING))
        self._header.setSpacing(px(BASE_HEADER_SPACING))
        self._balls_layout.setSpacing(row_spacing)

        # reload the current sprite at the new size and force a re-dock
        if self._current_dex is not None:
            dex = self._current_dex
            self._current_dex = None
            self._set_sprite(dex)
        self.adjustSize()
        self._last_pos = None
        self._last_order = None  # row heights changed -> recompute the fixed height

    def set_loading(self, is_loading: bool) -> None:
        """Show a spinner on the refresh button while OCR is running."""
        self._refresh_btn.set_loading(is_loading)

    def show_battle(
        self,
        dex_id: int,
        name: str,
        catch_rate: int | None,
        turn: int,
        probs: dict[str, float],
        level: int | None = None,
        status: str | None = None,
        hp_pct: float | None = None,
        alpha: bool = False,
        is_trainer: bool = False,
        is_empty: bool = False,
    ) -> None:
        """Update the overlay for the current enemy and show it.

        `catch_rate` is None for species with no known rate (roaming Latias/Latios/
        Mesprit/Cresselia): the rate and every ball percentage then show "??".
        `alpha` draws a red tile behind the sprite to mark an Alpha Pokémon."""
        unknown = catch_rate is None
        self._set_sprite(dex_id)
        self._alpha_glow.setEnabled(alpha)  # red aura marks an Alpha Pokémon
        lvl = (
            f' <span style="font-size:{self._level_px}px; color:#9aa0aa;">Lv.{level}</span>'
            if level
            else ""
        )
        if is_empty:
            self._sprite.setVisible(False)
            self._hp.setVisible(False)
            self._name.setText("")
            self._sub.setText("")
            self._set_status(None)
            self._empty_row.setVisible(True)
        else:
            self._name.setText(f"{name}{lvl}")
            self._sprite.setVisible(True)
            self._hp.setVisible(True)
            self._empty_row.setVisible(False)
            if is_trainer:
                self._sub.setText("Trainer Battle")
            else:
                self._sub.setText(subheader_text(catch_rate, turn))
            self._hp.setText(f"HP: {hp_pct:.0f}%" if hp_pct is not None else "")
            self._set_status(status)
        if is_trainer or is_empty or not probs:
            order = []
        else:
            for name, row in self._ball_rows.items():
                prob = probs.get(name)
                row.set_prob(prob, unknown)
            order = (
                unknown_ball_order(self._ball_names, self._hidden_names)
                if unknown
                else visible_ball_order(self._ball_names, probs, self._hidden_names)
            )
        self._reorder(order, is_empty=is_empty)
        self.show()

    def set_hidden_names(self, names: set[str]) -> None:
        """Choose which balls the overlay shows (by ball NAME). Hidden balls drop
        out; the rest are sorted by catch rate on the next update."""
        self._hidden_names = set(names)
        self._last_order = None  # force a re-layout on the next show_battle

    def _reorder(self, order: list[str], is_empty: bool = False) -> None:
        """Lay the ball rows out in `order` (best % first), hiding the rest. Skips
        the layout work when the order hasn't changed."""
        if order == self._last_order and is_empty == (self._last_order == []):
            return
        self._last_order = order
        # Show the placeholder only in the empty state; hide it when real balls show.
        self._empty_row.setVisible(is_empty)
        for roww in self._ball_rows.values():
            self._balls_layout.removeWidget(roww)
            roww.setVisible(False)
        for i, name in enumerate(order):
            roww = self._ball_rows[name]
            # Insert after the (always-first) empty_row placeholder.
            self._balls_layout.insertWidget(i + 1, roww)
            roww.setVisible(True)

        # Mirror dex_panel's _fit_list_height(): force a synchronous relayout of
        # _balls_layout, compute the tight sizeHint (excludes unconstrained stretch
        # expansion), and pin _balls_container to exactly that height so the window
        # sizes down cleanly without the trailing stretch eating extra space.
        self._balls_layout.invalidate()
        self._balls_layout.activate()
        self._balls_container.adjustSize()
        content_h = self._balls_container.sizeHint().height()

        if self._manual_height is not None:
            self._balls_container.setMinimumHeight(content_h)
            self._balls_container.setMaximumHeight(16777215)
        else:
            self._balls_container.setFixedHeight(content_h)

        self._col.invalidate()
        self._col.activate()
        self._root.invalidate()
        self._root.activate()

        if self._manual_height is None:
            self.setFixedHeight(self.sizeHint().height())

    def hide_battle(self) -> None:
        if self._movie is not None:
            self._movie.stop()
        self._current_dex = None  # so re-entering a battle restarts the sprite
        if self.isVisible():
            self.hide()

    def _on_balls_click(self) -> None:
        pos = self._balls_btn.mapToGlobal(self._balls_btn.rect().bottomLeft())
        self._toggle_balls(pos, self)

    # --- internals ---

    def _set_status(self, status: str | None) -> None:
        badge = status_badge(status)
        if badge is None:
            self._status.setVisible(False)
            return
        label, bg = badge
        self._status.setText(label)
        self._status.setStyleSheet(
            f"color: #ffffff; background: {bg}; border-radius: 3px; padding: 1px 3px;"
        )
        self._status.setVisible(True)

    def _set_sprite(self, dex_id: int) -> None:
        # Only (re)load on a species change; otherwise an animated GIF would be
        # restarted to frame 0 every tick and look frozen.
        if dex_id == self._current_dex:
            return
        self._current_dex = dex_id
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
        movie = self._loader.species_movie(dex_id, self._sprite_h)
        if movie is not None:
            self._movie = movie
            self._sprite.setMovie(movie)
            movie.start()
        else:
            self._sprite.setPixmap(self._loader.species_pixmap(dex_id, self._sprite_h))

    # --- ball picker popup ---

    def _toggle_balls(
        self, anchor_pos: QPoint | bool | None = None, parent_widget: QWidget | None = None
    ) -> None:
        if isinstance(anchor_pos, bool):
            anchor_pos = None
        if self._balls is not None and self._balls.isVisible():
            self._balls.close()
            self._balls = None
            return
        self._open_balls(anchor_pos, parent_widget)

    def _open_balls(
        self, anchor_pos: QPoint | bool | None = None, parent_widget: QWidget | None = None
    ) -> None:
        if isinstance(anchor_pos, bool):
            anchor_pos = None
        if self._balls is not None:
            self._balls.close()
        self._balls = self._build_balls(parent_widget)
        if anchor_pos is not None:
            self._balls.move(anchor_pos)
        else:
            self._balls.move(self._balls_btn.mapToGlobal(self._balls_btn.rect().bottomLeft()))
        self._balls.show()

    def _build_balls(self, parent_widget: QWidget | None = None) -> QWidget:
        balls, hidden = self.get_ball_state() if self.get_ball_state else ([], set())
        from ui.ui_components import create_popup_window

        w, box = create_popup_window("balls", parent_widget)
        head = QLabel("Show balls")
        head.setFont(self._font(12, bold=True))
        head.setStyleSheet("color: #ffffff;")
        box.addWidget(head)
        icon_h = self._px(BASE_SPRITE_H)
        for ball_id, ball_name in balls:
            shown = ball_id not in hidden
            sw = QPushButton(("✓  " if shown else "    ") + ball_name)
            sw.setFont(self._font(12))
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setIcon(QIcon(self._loader.ball_pixmap(ball_name, icon_h)))
            sw.setIconSize(QSize(icon_h, icon_h))
            shade = "#eeeeee" if shown else "#777777"
            sw.setStyleSheet(f"QPushButton {{ text-align: left; color: {shade}; }}")
            sw.clicked.connect(lambda _=False, i=ball_id: self._toggle_ball(i))
            box.addWidget(sw)
        row = QHBoxLayout()
        for text, vis in (("All", True), ("None", False)):
            b = QPushButton(text)
            b.setFont(self._font(11))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("QPushButton { color: #9aa0aa; }")
            b.clicked.connect(lambda _=False, v=vis: self._set_all_balls(v))
            row.addWidget(b)
        row.addStretch(1)
        cont = QWidget()
        cont.setLayout(row)
        box.addWidget(cont)
        return w

    def _toggle_ball(self, ball_id: str) -> None:
        if self.on_toggle_ball is not None:
            self.on_toggle_ball(ball_id)
        self._open_balls()

    def _set_all_balls(self, visible: bool) -> None:
        if self.on_set_all_balls is not None:
            self.on_set_all_balls(visible)
        self._open_balls()
