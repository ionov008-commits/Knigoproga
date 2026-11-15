"""Кривая линия связи между двумя нодами (QGraphicsPathItem)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsSceneMouseEvent

from assets.theme import COLOR_ACCENT, COLOR_SEQUENCE_LINE

if TYPE_CHECKING:  # pragma: no cover
    from ui.canvas_view import CanvasView
    from ui.event_node import EventNode

# link_type -> стиль линии
LINK_STYLES: dict[str, dict] = {
    "sequence": {"color": COLOR_SEQUENCE_LINE, "style": Qt.SolidLine, "dash": None},
    "influence": {"color": COLOR_ACCENT, "style": Qt.CustomDashLine, "dash": [6.0, 3.0, 1.5, 3.0]},
}

HIT_WIDTH = 14.0  # ширина зоны попадания мышью
ARROW_SIZE = 9.0


def build_curve_path(start: QPointF, end: QPointF, link_type: str = "sequence") -> QPainterPath:
    """Кубическая кривая от центра источника к центру приёмника."""
    path = QPainterPath(start)
    dx = end.x() - start.x()
    dy = end.y() - start.y()
    if abs(dx) < 1.0 and abs(dy) < 1.0:
        return path

    if link_type == "influence":
        # S-образная кривая с выраженным боковым смещением.
        offset = max(60.0, abs(dy) * 0.8)
        side = 1.0 if dx >= 0 else -1.0
        ctrl1 = QPointF(start.x() + side * offset, start.y())
        ctrl2 = QPointF(end.x() - side * offset, end.y())
    else:
        # Классическая "горизонтальная" кубическая кривая.
        if abs(dx) < 2.0:
            dx = 120.0 if dy >= 0 else -120.0
        ctrl1 = QPointF(start.x() + dx * 0.5, start.y())
        ctrl2 = QPointF(start.x() + dx * 0.5, end.y())

    path.cubicTo(ctrl1, ctrl2, end)
    return path


def _arrow_polygon(center: QPointF, end: QPointF, size: float = ARROW_SIZE) -> QPolygonF:
    """Треугольник-стрелка, остроконечная вершина которого — точка ``end``."""
    angle = math.atan2(end.y() - center.y(), end.x() - center.x())
    back_x = end.x() - math.cos(angle) * size
    back_y = end.y() - math.sin(angle) * size
    px, py = -math.sin(angle) * size * 0.5, math.cos(angle) * size * 0.5
    return QPolygonF(
        [
            QPointF(end),
            QPointF(back_x + px, back_y + py),
            QPointF(back_x - px, back_y - py),
        ]
    )


class LinkItem(QGraphicsPathItem):
    """Постоянная связь между двумя событиями.

    Двойной клик по линии открывает ``LinkEditDialog``.
    """

    NODE_TYPE = "link"

    def __init__(
        self,
        link_id: int,
        source_node: "EventNode",
        target_node: "EventNode",
        link_type: str = "sequence",
        description: str = "",
    ) -> None:
        super().__init__()
        self.link_id = int(link_id)
        self.source_node = source_node
        self.target_node = target_node
        self.link_type = link_type if link_type in LINK_STYLES else "sequence"
        self.description = description or ""
        self._hovered = False
        self._arrow: Optional[QPolygonF] = None

        self.setZValue(-1)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)

        if self.source_node is not None:
            self.source_node.add_link(self)
        if self.target_node is not None:
            self.target_node.add_link(self)

        self.setToolTip(self._tooltip_text())
        self.update_position()

    # ------------------------------------------------------------- geometry ---
    def update_position(self) -> None:
        if self.source_node is None or self.target_node is None:
            return
        start = self.source_node.center()
        end = self.target_node.center()
        self.prepareGeometryChange()
        self.setPath(build_curve_path(start, end, self.link_type))

        path = self.path()
        if path.isEmpty():
            self._arrow = None
        else:
            tip = path.pointAtPercent(1.0)
            tail = path.pointAtPercent(0.85)
            self._arrow = _arrow_polygon(tail, tip)
        self._apply_pen()

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(HIT_WIDTH)
        hit = stroker.createStroke(self.path())
        hit.addPath(self.path())
        return hit

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(-ARROW_SIZE, -ARROW_SIZE, ARROW_SIZE, ARROW_SIZE)

    # ------------------------------------------------------------- state ---
    def set_link_type(self, link_type: str) -> None:
        self.link_type = link_type if link_type in LINK_STYLES else "sequence"
        self.setToolTip(self._tooltip_text())
        self.update_position()

    def set_description(self, description: str) -> None:
        self.description = description or ""
        self.setToolTip(self._tooltip_text())

    def detach(self) -> None:
        """Отвязывает линию от нод перед удалением из сцены."""
        if self.source_node is not None:
            self.source_node.remove_link(self)
        if self.target_node is not None:
            self.target_node.remove_link(self)

    def _tooltip_text(self) -> str:
        kind = "Влияние" if self.link_type == "influence" else "Последовательность"
        src = getattr(self.source_node, "title_text", "?")
        dst = getattr(self.target_node, "title_text", "?")
        text = f"{kind}: {src} → {dst}"
        if self.description.strip():
            text += f"\n\n{self.description.strip()}"
        return text

    # -------------------------------------------------------------- drawing ---
    def _apply_pen(self) -> None:
        style = LINK_STYLES[self.link_type]
        color = QColor(style["color"])
        width = 2.0
        if self.isSelected():
            color = QColor(COLOR_ACCENT)
            width = 3.0
        elif self._hovered:
            color = QColor("#9a83ff") if self.link_type == "influence" else QColor(COLOR_ACCENT)
            width = 2.8

        pen = QPen(color, width)
        if style["dash"]:
            pen.setStyle(Qt.CustomDashLine)
            pen.setDashPattern(style["dash"])
        else:
            pen.setStyle(Qt.SolidLine)
        pen.setCapStyle(Qt.RoundCap)
        pen.setCosmetic(True)  # линия остаётся видимой при любом масштабе
        self.setPen(pen)
        self._arrow_color = color
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        if self._arrow is not None:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._arrow_color)
            painter.drawPolygon(self._arrow)

    # -------------------------------------------------------------- events ---
    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        self._apply_pen()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self._apply_pen()
        super().hoverLeaveEvent(event)

    def _view(self) -> Optional["CanvasView"]:
        scene = self.scene()
        return scene.views()[0] if scene and scene.views() else None

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        view = self._view()
        if event.button() == Qt.LeftButton and view is not None:
            view.link_double_clicked(self)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._apply_pen()
        return super().itemChange(change, value)


class RubberBandLink(QGraphicsPathItem):
    """Временная пунктирная линия, которая тянется от источника к курсору."""

    def __init__(self) -> None:
        super().__init__()
        pen = QPen(QColor(COLOR_ACCENT), 2)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([5.0, 4.0])
        pen.setCapStyle(Qt.RoundCap)
        self.setPen(pen)
        self.setZValue(1000)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)

    def update_curve(self, start: QPointF, end: QPointF) -> None:
        self.prepareGeometryChange()
        self.setPath(build_curve_path(start, end, "influence"))

    def shape(self) -> QPainterPath:
        # Временная линия не должна перехватывать события мыши.
        return QPainterPath()