"""Process Explorer's history graphs in the family look: the family gradient as the line, a faint fill under it, a
second line in pearl (kernel time, or writes), the label and value in the corner."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import theme


class Graph(QWidget):
    def __init__(self, label: str = "", small: bool = False, parent=None):
        super().__init__(parent)
        self.label = label
        self.small = small
        self.values: list[float] = []
        self.second: list[float] | None = None
        self.value = ""
        self.top: float | None = 100.0          # None: scale to the largest value shown (I/O)
        self.samples = 120 if small else 300
        self.setMinimumSize(QSize(110 if small else 200, 30 if small else 110))

    def set_data(self, values, value: str = "", second=None, top: float | None = 100.0):
        self.values = list(values)[-self.samples:]
        self.second = list(second)[-self.samples:] if second is not None else None
        self.value = value
        self.top = top
        self.update()

    def _scale(self) -> float:
        if self.top is not None:
            return self.top
        peak = max(self.values + (self.second or []) + [1.0])
        return peak * 1.15

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        p.setPen(QPen(QColor(theme.PANEL_EDGE), 1))
        p.setBrush(QColor(theme.WIDGET))
        p.drawRoundedRect(r, 3, 3)
        if not self.small:
            p.setPen(QPen(QColor(theme.PANEL_EDGE), 1, Qt.PenStyle.DotLine))
            for k in range(1, 4):
                y = r.top() + r.height() * k / 4
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        inner = r.adjusted(2, 15, -2, -2) if self.small else r.adjusted(2, 3, -2, -2)
        top = self._scale()
        n = self.samples

        def path(vals):
            pa = QPainterPath()
            start = n - len(vals)                      # the newest sample at the right edge, as Process Explorer
            for i, v in enumerate(vals):
                x = inner.left() + inner.width() * (start + i) / max(1, n - 1)
                y = inner.bottom() - inner.height() * min(1.0, max(0.0, v / top))
                pa.moveTo(x, y) if i == 0 else pa.lineTo(x, y)
            return pa
        if len(self.values) >= 2:
            line = path(self.values)
            fill = QPainterPath(line)
            fill.lineTo(line.currentPosition().x(), inner.bottom())
            fill.lineTo(line.elementAt(0).x, inner.bottom())
            fill.closeSubpath()
            g = QLinearGradient(inner.topLeft(), inner.bottomLeft())
            c1 = QColor(theme.ACCENT); c1.setAlphaF(.35)
            c2 = QColor(theme.ACCENT); c2.setAlphaF(.02)
            g.setColorAt(0, c1); g.setColorAt(1, c2)
            p.fillPath(fill, QBrush(g))
            p.setBrush(Qt.BrushStyle.NoBrush)          # drawPath would otherwise fill the line's chord with the old brush
            p.setPen(QPen(QBrush(theme.family_gradient(inner.left(), 0, inner.right(), 0)), 1.6 if self.small else 2))
            p.drawPath(line)
            if self.second and len(self.second) >= 2:
                p.setPen(QPen(QColor(theme.TEXT_DIM), 1.2))
                p.drawPath(path(self.second))
        if self.label or self.value:
            f = QFont("Inter")
            f.setPixelSize(10 if self.small else 11)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(r.adjusted(6, 3, -6, -3), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.label)
            p.setPen(QColor(theme.TEXT))
            p.drawText(r.adjusted(6, 3, -6, -3), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, self.value)
