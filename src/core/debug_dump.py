"""Diagnostic module for generating visual debug dumps of the current game frame.

This module is responsible for capturing the current screen state, annotating it with
the active calibration regions (HP bars, OCR bounds, UI elements), and saving the
results to disk. This is heavily utilized when the user manually requests a debug
dump via the settings panel to troubleshoot visual detection issues.
"""

from __future__ import annotations

import logging
from typing import Any

from battle.battle_reader import Calibration
from core.utils import parse_coord

log = logging.getLogger("shakechecker")


def trigger_debug_dump(
    frame: Any,
    reading: Any,
    cal: Calibration,
) -> None:
    """Save an annotated full frame and cropped sub-regions to the logs/debug/ directory.

    This function isolates heavy image processing dependencies (cv2, numpy) by loading them
    lazily upon invocation. This ensures that the application does not incur a cold-start
    penalty for these libraries when running the standard game loop.

    Args:
        frame: The raw captured screen frame (np.ndarray).
        reading: The current BattleReading object containing detected HP bars and state.
        cal: The active Calibration configuration defining expected screen regions.
    """
    from datetime import datetime
    from pathlib import Path

    import cv2
    import numpy as np

    if frame is None:
        return

    debug_dir = Path("logs") / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    annotated = frame.copy()  # draw all boxes/legend on this copy only
    h, w = frame.shape[:2]

    # ---------------------------------------------------------
    # 1. HP BAR + CAUGHT ICON + NAME + TRAINER STRIP
    # ---------------------------------------------------------
    if reading and reading.bars:
        bar = reading.bars[0]

        # HP bar fill start
        cv2.circle(annotated, (bar.x, bar.y), 4, (0, 255, 0), -1)

        # HP bar rectangle (green)
        BAR_HEIGHT = 10
        BAR_WIDTH = 218
        cv2.rectangle(
            annotated,
            (bar.x, bar.y - BAR_HEIGHT // 2),
            (bar.x + BAR_WIDTH, bar.y + BAR_HEIGHT // 2),
            (0, 255, 0),
            2,
        )

        # Caught icon (red)
        c_ci = cal.caught_icon
        cv2.rectangle(
            annotated,
            (bar.x + c_ci.dx0, bar.y + c_ci.dy0),
            (bar.x + c_ci.dx1, bar.y + c_ci.dy1),
            (0, 0, 255),
            2,
        )

        # Name OCR region (yellow)
        c_name = cal.name
        ny0, ny1 = bar.y + c_name.dy0, bar.y + c_name.dy1
        nx0, nx1 = bar.x + c_name.dx0, bar.x + c_name.dx1
        if 0 <= ny0 < ny1 <= h and 0 <= nx0 < nx1 <= w:
            cv2.rectangle(annotated, (nx0, ny0), (nx1, ny1), (0, 255, 255), 2)

        # Trainer strip region (white)
        c_tr = cal.trainer
        ty0 = bar.y + c_tr.dy0
        ty1 = bar.y + c_tr.dy1
        tx0 = bar.x
        tx1 = bar.x + c_tr.width_px
        if 0 <= ty0 < ty1 <= h and 0 <= tx0 < tx1 <= w:
            cv2.rectangle(annotated, (tx0, ty0), (tx1, ty1), (255, 255, 255), 2)

        # Status badge region (chartreuse)
        c_st = cal.status
        st_y0 = bar.y + c_st.dy0
        st_y1 = bar.y + c_st.dy1
        st_x0 = bar.x + c_st.dx0
        st_x1 = bar.x + c_st.dx1
        if 0 <= st_y0 < st_y1 <= h and 0 <= st_x0 < st_x1 <= w:
            cv2.rectangle(annotated, (st_x0, st_y0), (st_x1, st_y1), (0, 255, 128), 2)

    # ---------------------------------------------------------
    # 2. HP BAR SEARCH REGION (blue)
    # ---------------------------------------------------------
    c_hp = cal.hp_bar
    sy0 = parse_coord(c_hp.search_top, h)
    sy1 = parse_coord(c_hp.search_bottom, h)
    sx0 = parse_coord(c_hp.search_left, w)
    sx1 = parse_coord(c_hp.search_right, w)
    cv2.rectangle(annotated, (sx0, sy0), (sx1, sy1), (255, 0, 0), 2)

    # ---------------------------------------------------------
    # 3. CHAT OCR REGION (cyan)
    # ---------------------------------------------------------
    c_chat = cal.chat
    cx0, cx1 = c_chat.crop_x(w)
    cy0 = parse_coord(c_chat.top, h)
    cy1 = parse_coord(c_chat.bottom, h)
    if 0 <= cy0 < cy1 <= h and 0 <= cx0 < cx1 <= w:
        cv2.rectangle(annotated, (cx0, cy0), (cx1, cy1), (255, 255, 0), 2)

    # ---------------------------------------------------------
    # 4. LOCATION REGION (purple)
    # ---------------------------------------------------------
    c_loc = cal.location
    ly0 = parse_coord(c_loc.top, h)
    ly1 = parse_coord(c_loc.bottom, h)
    lx0 = parse_coord(c_loc.left, w)
    lx1 = parse_coord(c_loc.right, w)
    cv2.rectangle(annotated, (lx0, ly0), (lx1, ly1), (255, 0, 255), 2)

    # ---------------------------------------------------------
    # 5. BATTLE UI REGION (orange)
    # ---------------------------------------------------------
    c_ui = cal.battle_ui
    uy0 = parse_coord(c_ui.top, h)
    uy1 = parse_coord(c_ui.bottom, h)
    ux0 = parse_coord(c_ui.left, w)
    ux1 = parse_coord(c_ui.right, w)
    cv2.rectangle(annotated, (ux0, uy0), (ux1, uy1), (0, 165, 255), 2)

    # ---------------------------------------------------------
    # 6. BATTLE TEXT REGION (pink)
    # ---------------------------------------------------------
    c_bt = cal.battle_text
    by0 = parse_coord(c_bt.top, h)
    by1 = parse_coord(c_bt.bottom, h)
    bx0 = parse_coord(c_bt.left, w)
    bx1 = parse_coord(c_bt.right, w)
    cv2.rectangle(annotated, (bx0, by0), (bx1, by1), (255, 105, 180), 2)

    # ---------------------------------------------------------
    # 7. LEGEND (bottom-right)
    # ---------------------------------------------------------
    legend = [
        ("HP Bar (detected)", (0, 255, 0)),
        ("Caught Icon Region", (0, 0, 255)),
        ("HP Bar Search", (255, 0, 0)),
        ("Name OCR Region", (0, 255, 255)),
        ("Chat OCR Region", (255, 255, 0)),
        ("Location Region", (255, 0, 255)),
        ("Battle UI Region", (0, 165, 255)),
        ("Battle Text Region", (255, 105, 180)),
        ("Trainer Strip Region", (255, 255, 255)),
        ("Status Badge Region", (0, 255, 128)),
    ]

    font = cv2.FONT_HERSHEY_DUPLEX
    scale = 0.4
    thickness = 1
    line_height = 16

    y = 20  # top padding

    for text, color in legend:
        text_width = cv2.getTextSize(text, font, scale, thickness)[0][0]
        x = w - text_width - 20

        # Outline (stroke)
        cv2.putText(
            annotated, text, (x - 1, y - 1), font, scale, (0, 0, 0), thickness + 1, cv2.LINE_AA
        )
        cv2.putText(
            annotated, text, (x + 1, y - 1), font, scale, (0, 0, 0), thickness + 1, cv2.LINE_AA
        )
        cv2.putText(
            annotated, text, (x - 1, y + 1), font, scale, (0, 0, 0), thickness + 1, cv2.LINE_AA
        )
        cv2.putText(
            annotated, text, (x + 1, y + 1), font, scale, (0, 0, 0), thickness + 1, cv2.LINE_AA
        )

        # Main text
        cv2.putText(annotated, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)

        y += line_height

    # ---------------------------------------------------------
    # 8. SAVE FULL FRAME (annotated copy)
    # ---------------------------------------------------------
    cv2.imwrite(str(debug_dir / f"full_frame_{timestamp}.png"), annotated)
    cv2.imwrite(str(debug_dir / f"full_raw_{timestamp}.png"), frame)

    # ---------------------------------------------------------
    # 9. DUMP CROPS
    # ---------------------------------------------------------

    # Location
    try:
        from dex import location_reader

        loc_raw = frame[ly0:ly1, lx0:lx1]
        if loc_raw.size > 0:
            cv2.imwrite(str(debug_dir / f"location_raw_{timestamp}.png"), loc_raw)

            loc_crop = loc_raw.copy()
            mask = location_reader.extract_location_mask(loc_raw)
            if mask is not None:
                ys, xs = np.where(mask > 0)
                if len(xs) > 0:
                    x1m, x2m = xs.min(), xs.max()
                    loc_crop = loc_crop[:, x1m : x2m + 1]

            scale_loc = 48.0 / max(1, loc_crop.shape[0])
            up_loc = cv2.resize(
                loc_crop, None, fx=scale_loc, fy=scale_loc, interpolation=cv2.INTER_CUBIC
            )
            cv2.imwrite(str(debug_dir / f"location_mod_{timestamp}.png"), up_loc)
    except Exception as e:
        log.warning("Failed to dump location: %s", e)

    # Chat
    try:
        chat_crop = frame[cy0:cy1, cx0:cx1]
        if chat_crop.size > 0:
            up_chat = cv2.resize(
                chat_crop,
                None,
                fx=c_chat.upscale,
                fy=c_chat.upscale,
                interpolation=cv2.INTER_CUBIC,
            )
            cv2.imwrite(str(debug_dir / f"chat_{timestamp}.png"), up_chat)
    except Exception as e:
        log.warning("Failed to dump chat: %s", e)

    # Name
    try:
        if reading and reading.bars:
            bar = reading.bars[0]
            c_name = cal.name
            y0n, y1n = bar.y + c_name.dy0, bar.y + c_name.dy1
            x0n, x1n = bar.x + c_name.dx0, bar.x + c_name.dx1
            if 0 <= y0n < y1n <= h and 0 <= x0n < x1n <= w:
                name_crop = frame[y0n:y1n, x0n:x1n]
                if name_crop.size > 0:
                    up_name = cv2.resize(
                        name_crop,
                        None,
                        fx=c_name.upscale,
                        fy=c_name.upscale,
                        interpolation=cv2.INTER_CUBIC,
                    )
                    cv2.imwrite(str(debug_dir / f"name_{timestamp}.png"), up_name)
    except Exception as e:
        log.warning("Failed to dump name: %s", e)

    # HP bar search crop
    try:
        crop_hp = frame[sy0:sy1, sx0:sx1]
        if crop_hp.size > 0:
            cv2.imwrite(str(debug_dir / f"hp_bar_search_{timestamp}.png"), crop_hp)
    except Exception as e:
        log.warning("Failed to dump hp_bar_search: %s", e)

    # Battle UI
    try:
        crop_ui = frame[uy0:uy1, ux0:ux1]
        if crop_ui.size > 0:
            cv2.imwrite(str(debug_dir / f"battle_ui_{timestamp}.png"), crop_ui)
    except Exception as e:
        log.warning("Failed to dump battle_ui: %s", e)

    # Caught icon
    try:
        if reading and reading.bars:
            bar = reading.bars[0]
            c_ci = cal.caught_icon
            y0c = bar.y + c_ci.dy0
            y1c = bar.y + c_ci.dy1
            x0c = bar.x + c_ci.dx0
            x1c = bar.x + c_ci.dx1
            if 0 <= y0c < y1c <= h and 0 <= x0c < x1c <= w:
                crop_ci = frame[y0c:y1c, x0c:x1c]
                if crop_ci.size > 0:
                    cv2.imwrite(str(debug_dir / f"caught_icon_{timestamp}.png"), crop_ci)
    except Exception as e:
        log.warning("Failed to dump caught_icon: %s", e)

    # Battle text
    try:
        crop_bt = frame[by0:by1, bx0:bx1]
        if crop_bt.size > 0:
            cv2.imwrite(str(debug_dir / f"battle_text_{timestamp}.png"), crop_bt)
    except Exception as e:
        log.warning("Failed to dump battle_text: %s", e)

    # Trainer strip
    try:
        if reading and reading.bars:
            bar = reading.bars[0]
            c_tr = cal.trainer
            ty0 = bar.y + c_tr.dy0
            ty1 = bar.y + c_tr.dy1
            tx0 = bar.x
            tx1 = bar.x + c_tr.width_px
            if 0 <= ty0 < ty1 <= h and 0 <= tx0 < tx1 <= w:
                crop_tr = frame[ty0:ty1, tx0:tx1]
                if crop_tr.size > 0:
                    cv2.imwrite(str(debug_dir / f"trainer_strip_{timestamp}.png"), crop_tr)
    except Exception as e:
        log.warning("Failed to dump trainer_strip: %s", e)

    if reading and reading.bars:
        log.info("Debug dump saved to '/logs/debug/' folder.")
    else:
        log.info(
            "Debug dump saved to '/logs/debug/' folder "
            "(partial – no battle data, bar-relative slices skipped)."
        )
