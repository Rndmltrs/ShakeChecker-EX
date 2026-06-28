"""PyQt6 dex "missing here" panel: frameless, translucent, always-on-top, shown
while walking the overworld (hidden in battle, where the catch overlay takes
over). Docks below the game's HUD like the catch overlay.

Layout: a top icon bar (profile + info), a route header (name + region/time/
season + still-needed count), then a VERTICALLY SCROLLABLE list of sprite + name
+ way rows -- every uncaught species (dex order), then the already-caught
Lure/Rare/Very Rare ones (✓), via dex_tracker.display_order. The list height is
capped (BASE_MAX_LIST_H); longer lists scroll. Name colour = rarity (WoW-style).

Interaction is HOVER-TO-INTERACT: the window is click-through (input passes to
the game) until the cursor is over it, then it accepts clicks (icons, per-row
check-off) and the wheel scrolls. Click-through is toggled via the Win32
WS_EX_TRANSPARENT extended style; a short timer polls the cursor.

The app wires four callbacks: on_toggle_caught(dex_id), on_select_profile(name),
on_create_profile(name), get_profiles()->(active, [names]).

Preview without the game:  python src/dex_panel.py
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.game_time import season_name
from dex.dex_structures import LocationView
from dex.dex_tracker import display_order
from ui.sprite_loader import SpriteLoader
from ui.ui_components import DexSpeciesRow
from ui.ui_overlay import (
    BaseOverlay,
)

HOVER_POLL_MS = 40  # how often to check if the cursor is over the panel
ANIMATE_SPRITES = True  # Toggle animated GIFs for the Dex Panel (False saves CPU)


# Base (scale 1.0) sizes in logical px (mirrors overlay.py's approach). The way
# sits right after the name and overlong ways are elided, so this only needs to
# fit a typical name + short way; long names still show in full (the way elides).
BASE_PANEL_W = 236
BASE_SPRITE_H = 22
BASE_SPRITE_COL_W = 30  # fixed sprite-column width so names start flush
BASE_TITLE_PX = 15
BASE_SUB_PX = 11
BASE_ROW_PX = 13
BASE_ICON_PX = 15
BASE_MARGIN_X = 12
BASE_MARGIN_Y = 10
BASE_COL_SPACING = 3
BASE_ROW_SPACING = 6
DEX_MAX_VISIBLE_ROWS = 6  # show at most this many rows; the rest scroll


class DexPanel(BaseOverlay):
    def __init__(self, loader: SpriteLoader | None = None) -> None:
        super().__init__(
            mode_name="Dex Mode",
            mode_tooltip="Switch to Battle Mode\n(Note: auto-switch is enabled)",
            base_panel_w=BASE_PANEL_W,
            extra_css=(
                " QScrollArea { background: transparent; border: none; }"
                " QScrollBar:vertical { width: 6px; background: transparent; margin: 0; }"
                " QScrollBar::handle:vertical { background: rgba(255,255,255,70);"
                " border-radius: 3px; min-height: 20px; }"
                " QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
                " QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
                " background: transparent; }"
            ),
        )
        self._loader = loader or SpriteLoader()
        self._sprite_h = BASE_SPRITE_H
        self._legend: QWidget | None = None
        self._profiles: QWidget | None = None  # profile management popup
        self._rows: list[DexSpeciesRow] = []  # reused row-widget pool, grown as needed

        # Close the header popups when ShakeChecker stops being the active app,
        # i.e. the user clicked back into the game window.
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.applicationStateChanged.connect(self._on_app_state_changed)

        # callbacks the app wires in (no-ops until set)
        self.on_toggle_caught: Callable[[int], None] | None = None
        self.get_keep_caught: Callable[[], bool] | None = None
        self.get_click_to_catch: Callable[[], bool] | None = None
        self.on_force_refresh: Callable[[], None] | None = None

        self._init_dex()

    def _on_refresh_clicked(self) -> None:
        if self.on_force_refresh:
            self.on_force_refresh()

    def setup_middle_btn(self) -> None:
        self._info_btn = self._add_header_btn("Rarity colour legend", self._toggle_legend)

    def _init_dex(self) -> None:

        self._title_layout = QHBoxLayout()
        self._title_layout.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel(" ")
        self._title.setObjectName("PrimaryText")
        self._title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._title_layout.addWidget(self._title, 1)

        from ui.ui_components import SpinnerButton

        self._refresh_btn = SpinnerButton(BASE_ICON_PX)
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        self._title_layout.addWidget(self._refresh_btn)

        self._col.addLayout(self._title_layout)

        self._subtitle = QLabel(" ")
        self._subtitle.setObjectName("SecondaryText")
        self._subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._col.addWidget(self._subtitle)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("Divider")
        self._col.addWidget(line)

        # scrollable species list
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.viewport().setStyleSheet("background: transparent;")  # type: ignore[union-attr]
        self._list = QWidget()
        self._list.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(
            0, 0, 16, 0
        )  # gap so the scrollbar clears the way text
        self._list_layout.addStretch(1)  # keep rows top-aligned
        self._scroll.setWidget(self._list)
        self._col.addWidget(self._scroll, 1)

        self.apply_scale(1.0)

    # --- public API ---

    def _on_drag_resize(self, dy: int) -> None:
        super()._on_drag_resize(dy)
        self._fit_list_height()

    def apply_scale(self, scale: float) -> None:
        scale = max(0.1, min(2.0, scale))
        if abs(scale - self._scale) < 0.02:
            return
        self._scale = scale
        self._panel_w = self._px(BASE_PANEL_W)
        self.setFixedWidth(self._panel_w)
        self._sprite_h = self._px(BASE_SPRITE_H)
        self._name_fm = QFontMetrics(self._font(self._px(BASE_ROW_PX)))
        self._way_fm = QFontMetrics(self._font(self._px(BASE_SUB_PX)))

        title_font = self._font(self._px(BASE_TITLE_PX), bold=True)
        sub_font = self._font(self._px(BASE_SUB_PX))
        self._title.setFont(title_font)
        self._subtitle.setFont(sub_font)

        self._mode_label.setFont(self._font(self._px(13), bold=True))
        isz = self._px(BASE_ICON_PX)
        self._scale_icon_btn(self._mode_btn, "book", isz)
        self._scale_icon_btn(self._settings_btn, "gear", isz)
        self._scale_icon_btn(self._info_btn, "info", isz)
        self._refresh_btn.set_size(isz)
        self._col.setContentsMargins(
            self._px(BASE_MARGIN_X),
            self._px(BASE_MARGIN_Y),
            self._px(BASE_MARGIN_X),
            self._px(BASE_MARGIN_Y),
        )
        self._col.setSpacing(self._px(BASE_COL_SPACING))
        self._list_layout.setSpacing(self._px(BASE_ROW_SPACING))
        self._list_layout.setContentsMargins(0, 0, self._px(16), 0)
        col_w = self._px(BASE_SPRITE_COL_W)
        row_font = self._font(self._px(BASE_ROW_PX))
        sub_font = self._font(self._px(BASE_SUB_PX))
        for r in self._rows:
            r.apply_scale(self._px(BASE_ROW_SPACING), row_font, sub_font, col_w, self._sprite_h)
            r.clear_sprite()  # force reload at the new sprite size
        self._last_pos = None

    def show_here(self, view: LocationView) -> None:
        """Populate from a location view and show the panel."""
        keep_caught = self.get_keep_caught() if self.get_keep_caught is not None else True
        entries = display_order(view.entries, keep_caught=keep_caught)
        needed = sum(1 for e in view.entries if not e.caught)

        title_text = view.route if view.route == "ShakeChecker" else view.route.title()
        self._current_title_text = title_text
        self._title.setText(title_text)

        if view.route == "ShakeChecker":
            self._subtitle.setText(view.region.title())
        else:
            self._subtitle.setText(
                f"{view.region.title()} · {view.period.value.title()} · "
                f"{season_name(view.season)} · {needed} left"
            )
        self._ensure_rows(max(1, len(entries)))
        margin_x = self._px(BASE_MARGIN_X)
        col_w = self._px(BASE_SPRITE_COL_W)
        spacing = self._px(BASE_ROW_SPACING)
        base_16 = self._px(16)

        for i, entry in enumerate(entries):
            r = self._rows[i]
            r.fill(
                entry, self._name_fm, self._way_fm, self._panel_w, margin_x, col_w, spacing, base_16
            )
            r.set_sprite(self._loader, entry.id, self._sprite_h, col_w)
            r.setVisible(True)

        for i in range(len(entries), len(self._rows)):
            r = self._rows[i]
            if r.isVisible():  # only clear sprite on the visible->hidden transition
                r.suspend_sprite()
                r.setVisible(False)

        if not entries:  # nothing left here
            r0 = self._rows[0]
            r0.hide_sprite()
            r0.setVisible(True)
            if not view.entries:
                r0.name.setText('<span style="color:#9aa0aa;">no encounters here</span>')
            else:
                r0.name.setText('<span style="color:#9aa0aa;">all caught here!</span>')
            r0.way.setText("")

        self._fit_list_height()
        self._col.invalidate()
        self._col.activate()
        self._root.invalidate()
        self._root.activate()
        if self._manual_height is None:
            self.adjustSize()
        self.show()

    def set_loading(self, is_loading: bool) -> None:
        """Show a spinner on the refresh button while OCR is running."""
        self._is_loading = is_loading
        self._refresh_btn.set_loading(is_loading)

    def hide_panel(self) -> None:
        self._hide_popups()
        for r in self._rows:  # stop GIFs while hidden; they reload on re-show
            r.suspend_sprite()
        self.hide()

    def _hide_popups(self) -> None:
        try:
            if self._legend is not None and self._legend.isVisible():
                self._legend.close()
        except RuntimeError:
            pass
        self._legend = None

        try:
            if self._profiles is not None and self._profiles.isVisible():
                self._profiles.close()
        except RuntimeError:
            pass
        self._profiles = None

    def _on_app_state_changed(self, state: Qt.ApplicationState) -> None:
        # Close the header popups when focus leaves ShakeChecker for the game.
        # Our own modal dialogs (new/delete profile) keep the app Active, so this
        # never fires while one is open.
        if state == Qt.ApplicationState.ApplicationInactive:
            self._hide_popups()

        if state == Qt.ApplicationState.ApplicationInactive:
            self._hide_popups()

    def _row_clicked(self, index: int) -> None:
        if self.get_click_to_catch is not None and not self.get_click_to_catch():
            return
        dex = self._rows[index].dex if index < len(self._rows) else None
        if dex is not None and self.on_toggle_caught is not None:
            self.on_toggle_caught(dex)

    def _toggle_legend(self, _=False) -> None:
        if self._legend is not None and self._legend.isVisible():
            self._legend.close()
            self._legend = None
            return
        self._open_legend(self)

    def _open_legend(self, parent_widget: QWidget | None = None) -> None:
        if self._legend is not None:
            self._legend.close()
        from ui.ui_components import build_legend

        self._legend = build_legend(self, parent_widget)
        self._legend.move(self._info_btn.mapToGlobal(self._info_btn.rect().bottomRight()))
        self._legend.show()

        self._legend.move(self._info_btn.mapToGlobal(self._info_btn.rect().bottomRight()))
        self._legend.show()

    # --- internals ---

    def _ensure_rows(self, n: int) -> None:
        while len(self._rows) < n:
            self._make_row()

    def _make_row(self) -> None:
        index = len(self._rows)
        row = DexSpeciesRow(index, self._row_clicked)

        row_font = self._font(self._px(BASE_ROW_PX))
        sub_font = self._font(self._px(BASE_SUB_PX))
        col_w = self._px(BASE_SPRITE_COL_W)
        row.apply_scale(self._px(BASE_ROW_SPACING), row_font, sub_font, col_w, self._sprite_h)

        # insert above the trailing stretch so rows stay top-aligned
        self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        self._rows.append(row)

    def _fit_list_height(self) -> None:
        """Size the scroll viewport to the content, capped at DEX_MAX_VISIBLE_ROWS
        rows (the rest scroll)."""
        if self._manual_height is not None:
            # If manually resized, let the scroll area expand to fill the available layout space
            self._scroll.setMinimumHeight(100)
            self._scroll.setMaximumHeight(16777215)
            return

        # Compute height directly from visible row count so we never race against
        # Qt's layout pass (sizeHint/adjustSize can be stale for a frame).
        row_h = self._sprite_h
        spacing = self._px(BASE_ROW_SPACING)
        visible = max(1, sum(1 for r in self._rows if r.isVisible()))
        # _list_layout has a trailing addStretch(1), so Qt places N spacings for N rows
        # + 1 spacer = N*(row_h+spacing) total. Using N-1 was 1 spacing short, causing
        # the content to overflow the viewport by ~6px, triggering scrollbar oscillation.
        content = visible * (row_h + spacing)
        cap = DEX_MAX_VISIBLE_ROWS * row_h + (DEX_MAX_VISIBLE_ROWS - 1) * spacing
        self._scroll.setFixedHeight(min(content, cap))

        self._scroll.setFixedHeight(min(content, cap))
