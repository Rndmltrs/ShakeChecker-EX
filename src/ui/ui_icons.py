import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap


def icon_pixmap(kind: str, size: int, color: str, angle: float = 0) -> QPixmap:
    """A small monochrome header icon drawn in the overlay's own colour (so it
    matches the panel instead of an OS emoji): 'gear', 'ball', 'swords', 'book',
    'refresh', or 'info'."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    cx = cy = size / 2
    if kind == "gear":
        ring = QPen(c, size * 0.15)
        p.setPen(ring)
        p.drawEllipse(QPointF(cx, cy), size * 0.25, size * 0.25)
        teeth = QPen(c, size * 0.14)
        teeth.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(teeth)
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(
                QPointF(cx + math.cos(a) * size * 0.33, cy + math.sin(a) * size * 0.33),
                QPointF(cx + math.cos(a) * size * 0.46, cy + math.sin(a) * size * 0.46),
            )
    elif kind == "ball":
        p.setPen(QPen(c, size * 0.10))
        p.drawEllipse(QPointF(cx, cy), size * 0.40, size * 0.40)  # ball outline
        p.drawLine(QPointF(cx - size * 0.40, cy), QPointF(cx + size * 0.40, cy))  # band
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(cx, cy), size * 0.14, size * 0.14)  # centre button
    elif kind == "swords":
        p.setPen(QPen(c, size * 0.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(
            QPointF(cx - size * 0.3, cy + size * 0.3), QPointF(cx + size * 0.3, cy - size * 0.3)
        )
        p.drawLine(
            QPointF(cx - size * 0.25, cy + size * 0.1), QPointF(cx - size * 0.1, cy + size * 0.25)
        )
        p.drawLine(
            QPointF(cx + size * 0.3, cy + size * 0.3), QPointF(cx - size * 0.3, cy - size * 0.3)
        )
        p.drawLine(
            QPointF(cx + size * 0.25, cy + size * 0.1), QPointF(cx + size * 0.1, cy + size * 0.25)
        )
    elif kind == "book":
        p.setPen(QPen(c, size * 0.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx - size * 0.35, cy - size * 0.2), QPointF(cx, cy - size * 0.1))
        p.drawLine(QPointF(cx - size * 0.35, cy + size * 0.2), QPointF(cx, cy + size * 0.3))
        p.drawLine(
            QPointF(cx - size * 0.35, cy - size * 0.2), QPointF(cx - size * 0.35, cy + size * 0.2)
        )
        p.drawLine(QPointF(cx + size * 0.35, cy - size * 0.2), QPointF(cx, cy - size * 0.1))
        p.drawLine(QPointF(cx + size * 0.35, cy + size * 0.2), QPointF(cx, cy + size * 0.3))
        p.drawLine(
            QPointF(cx + size * 0.35, cy - size * 0.2), QPointF(cx + size * 0.35, cy + size * 0.2)
        )
        p.drawLine(QPointF(cx, cy - size * 0.1), QPointF(cx, cy + size * 0.3))
    elif kind == "refresh":
        p.translate(cx, cy)
        p.rotate(angle)
        p.translate(-cx, -cy)
        
        ring = QPen(c, size * 0.12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(ring)
        r = size * 0.32
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        p.drawArc(rect, 15 * 16, 120 * 16)
        p.drawArc(rect, 195 * 16, 120 * 16)

        # Arrow heads
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        from PyQt6.QtGui import QPolygonF

        # Arrow 1 at 135 deg (end of arc 1). Tangent points down-left (225 deg).
        a1_x, a1_y = cx + math.cos(math.radians(135)) * r, cy - math.sin(math.radians(135)) * r
        poly1 = QPolygonF(
            [
                QPointF(a1_x, a1_y),
                QPointF(a1_x + size * 0.15, a1_y - size * 0.05),
                QPointF(a1_x + size * 0.05, a1_y + size * 0.15),
            ]
        )
        p.drawPolygon(poly1)
        # Arrow 2 at 315 deg (end of arc 2). Tangent points up-right (45 deg).
        a2_x, a2_y = cx + math.cos(math.radians(315)) * r, cy - math.sin(math.radians(315)) * r
        poly2 = QPolygonF(
            [
                QPointF(a2_x, a2_y),
                QPointF(a2_x - size * 0.15, a2_y + size * 0.05),
                QPointF(a2_x - size * 0.05, a2_y - size * 0.15),
            ]
        )
        p.drawPolygon(poly2)
    else:  # info
        p.setPen(QPen(c, size * 0.10))
        p.drawEllipse(QPointF(cx, cy), size * 0.42, size * 0.42)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(cx, cy - size * 0.19), size * 0.065, size * 0.065)  # dot
        stem = QPen(c, size * 0.13)
        stem.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(stem)
        p.drawLine(QPointF(cx, cy - size * 0.02), QPointF(cx, cy + size * 0.22))
    p.end()
    return pm
