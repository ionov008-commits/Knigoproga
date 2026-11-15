"""Карточка события на холсте (QGraphicsRectItem)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsSceneMouseEvent,
    QGraphicsTextItem,
)

from assets.theme import (
    COLOR_ACCENT,
    COLOR_BORDER,
    COLOR_PANEL,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    NODE_HEIGHT,
    NODE_RADIUS,
    NODE_WIDTH,
)

if TYPE_CHECKING:  # pragma: no cover
    from ui.canvas_view import CanvasView
    from ui.link_item import LinkItem


LOD_SCREEN_WIDTH = 60.0


def _elide(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class EventNode(QGraphicsRectItem):
    """Нода события: 180x90, заголовок и 2-3 строки описания.

    • перетаскивается левой кнопкой мыши;
    • при перемещении сообщает связанным линиям о перерисовке;
    • двойной клик открывает редактор события;
    • в режиме связывания клик выбирает ноду как источник/приёмник.
    """

    NODE_TYPE = "event"

    def __init__(self, event_id: int, title: str, description: str = "", x: float = 0.0, y: float = 0.0) -> None:
        super().__init__(0.0, 0.0, NODE_WIDTH, NODE_HEIGHT)
        self.event_id = int(event_id)
        self.title_text = title or "Без названия"
        self.description_text = description or ""
        self.links: list["LinkItem"] = []
        self._is_connect_source = False
        self._dragging = False
        self._lod = False  # режим точки при сильном отдалении

        self.setPos(float(x), float(y))
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIsFocusable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(0)
        self.setToolTip(self._tooltip_text())

        self._build_text_items()
        self.refresh_pen()

    # --------------------------------------------------------------- shapes ---
    def _build_text_items(self) -> None:
        padding = 10.0

        self.title_item = QGraphicsTextItem(self)
        title_font = QFont("Segoe UI", 9)
        title_font.setBold(True)
        self.title_item.setFont(title_font)
        self.title_item.setDefaultTextColor(QColor(COLOR_TEXT))
        self.title_item.setTextWidth(NODE_WIDTH - padding * 2)
        self.title_item.setPos(padding, padding - 3)

        self.desc_item = QGraphicsTextItem(self)
        desc_font = QFont("Segoe UI", 7)
        self.desc_item.setFont(desc_font)
        self.desc_item.setDefaultTextColor(QColor(COLOR_TEXT_MUTED))
        self.desc_item.setTextWidth(NODE_WIDTH - padding * 2)
        self.desc_item.setPos(padding, 34.0)

        self.class_item = QGraphicsTextItem(self)
        class_font = QFont("Segoe UI", 6)
        self.class_item.setFont(class_font)
        self.class_item.setDefaultTextColor(QColor("#6d6d72"))
        self.class_item.setPlainText(f"#{self.event_id}")
        self.class_item.setPos(NODE_WIDTH - 42.0, NODE_HEIGHT - 16.0)

        # Текстовые элементы не должны перехватывать мышь: иначе двойной клик
        # по центру карточки уходил в текст, и событие не открывалось.
        for text_item in (self.title_item, self.desc_item, self.class_item):
            text_item.setAcceptedMouseButtons(Qt.NoButton)
            text_item.setAcceptHoverEvents(False)

        self._refresh_text()

    def _refresh_text(self) -> None:
        self.title_item.setPlainText(_elide(self.title_text, 40))
        self.desc_item.setPlainText(_elide(self.description_text, 64) or "—")

    def _tooltip_text(self) -> str:
        body = self.description_text.strip() or "Описание не заполнено."
        return f"#{self.event_id} · {self.title_text}\n\n{body}"

    def update_content(self, title: str, description: str) -> None:
        self.title_text = title or "Без названия"
        self.description_text = description or ""
        self._refresh_text()
        self.setToolTip(self._tooltip_text())
        self.update()

    def _view_zoom(self) -> float:
        view = self._scene_view()
        try:
            return float(view.current_zoom()) if view is not None else 1.0
        except Exception:  # noqa: BLE001
            return 1.0

    def apply_zoom(self, zoom: float) -> None:
        """Включает/выключает режим точки в зависимости от масштаба."""
        lod = zoom * NODE_WIDTH < LOD_SCREEN_WIDTH
        if lod == self._lod:
            return
        self._lod = lod
        for text_item in (self.title_item, self.desc_item, self.class_item):
            text_item.setVisible(not lod)
        self.update()

    def shape(self) -> QPainterPath:
        """Точная хит-область: карточка или компактная точка."""
        path = QPainterPath()
        if self._lod:
            zoom = max(self._view_zoom(), 1e-3)
            radius = min(10.0 / zoom, 80.0)
            path.addEllipse(QPointF(NODE_WIDTH / 2.0, NODE_HEIGHT / 2.0), radius, radius)
            return path
        path.addRoundedRect(QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT), NODE_RADIUS, NODE_RADIUS)
        return path

    def boundingRect(self) -> QRectF:
        return QRectF(-4, -4, NODE_WIDTH + 8, NODE_HEIGHT + 8)

    # ---------------------------------------------------------------- links ---
    def center(self) -> QPointF:
        return self.mapToScene(QPointF(NODE_WIDTH / 2.0, NODE_HEIGHT / 2.0))

    def add_link(self, link: "LinkItem") -> None:
        if link not in self.links:
            self.links.append(link)

    def remove_link(self, link: "LinkItem") -> None:
        if link in self.links:
            self.links.remove(link)

    def update_links(self) -> None:
        for link in list(self.links):
            link.update_position()

    # -------------------------------------------------------------- отрисовка ---
    def set_connect_source(self, flag: bool) -> None:
        self._is_connect_source = bool(flag)
        self.refresh_pen()

    def refresh_pen(self) -> None:
        if self._is_connect_source:
            pen = QPen(QColor(COLOR_ACCENT), 3)
        elif self.isSelected():
            pen = QPen(QColor(COLOR_ACCENT), 2)
        else:
            pen = QPen(QColor(COLOR_BORDER), 1.4)
        pen.setJoinStyle(Qt.RoundJoin)
        self.setPen(pen)
        self.update()

    def _paint_dot(self, painter: QPainter) -> None:
        """Компактная точка вместо карточки при сильном отдалении."""
        zoom = max(self._view_zoom(), 1e-3)
        radius = min(4.5 / zoom, 42.0)
        center = QPointF(NODE_WIDTH / 2.0, NODE_HEIGHT / 2.0)
        active = self._is_connect_source or self.isSelected()
        color = QColor(COLOR_ACCENT) if active else QColor("#dcddde")
        painter.setPen(QPen(color, 0))
        painter.setBrush(color)
        painter.drawEllipse(center, radius, radius)
        if active:
            painter.setPen(QPen(QColor(COLOR_ACCENT), 0))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, radius + min(3.5 / zoom, 30.0), radius + min(3.5 / zoom, 30.0))

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._lod:
            self._paint_dot(painter)
            return
        rect = QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT)

        background = QColor(COLOR_PANEL)
        if self._is_connect_source:
            background = QColor("#322a52")
        painter.setBrush(QBrush(background))
        painter.setPen(self.pen())
        painter.drawRoundedRect(rect, NODE_RADIUS, NODE_RADIUS)

        # Акцентная полоска слева как маркер события.
        stripe = QPainterPath()
        stripe.addRoundedRect(QRectF(1.0, 9.0, 3.0, NODE_HEIGHT - 18.0), 1.5, 1.5)
        painter.fillPath(stripe, QColor(COLOR_ACCENT if (self._is_connect_source or self.isSelected()) else "#4b4b52"))

        # Разделитель между заголовком и описанием.
        painter.setPen(QPen(QColor("#333336"), 1))
        painter.drawLine(QPointF(10, 31), QPointF(NODE_WIDTH - 10, 31))

        if self._is_connect_source:
            painter.setPen(QPen(QColor(COLOR_ACCENT), 1.5))
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), NODE_RADIUS, NODE_RADIUS)

    # -------------------------------------------------------------- события ---
    def hoverEnterEvent(self, event) -> None:
        if not self._is_connect_source:
            self.setCursor(Qt.PointingHandCursor if self._is_link_mode() else Qt.OpenHandCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.setCursor(Qt.ArrowCursor if self._is_link_mode() else Qt.OpenHandCursor)
        super().hoverLeaveEvent(event)

    def _scene_view(self) -> Optional["CanvasView"]:
        scene = self.scene()
        view = scene.views()[0] if scene and scene.views() else None
        return view  # type: ignore[return-value]

    def _is_link_mode(self) -> bool:
        view = self._scene_view()
        return bool(getattr(view, "link_mode", False))

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        view = self._scene_view()
        if event.button() == Qt.LeftButton and getattr(view, "link_mode", False):
            # В режиме связывания ноды не переставляем: клик выбирает их.
            if view is not None:
                view.handle_link_click(self)
            event.accept()
            return
        self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if not self._dragging and event.buttons() & Qt.LeftButton:
            self._dragging = True
            view = self._scene_view()
            if view is not None:
                view.mark_dirty()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        self._dragging = False
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.PointingHandCursor if self._is_link_mode() else Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        view = self._scene_view()
        if event.button() == Qt.LeftButton and view is not None:
            if getattr(view, "link_mode", False):
                view.cancel_link_operation()
            view.event_double_clicked(self)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.update_links()
            db = getattr(self.scene(), "db", None) if self.scene() else None
            if db is not None:
                from database import queries

                queries.update_event_position(db, self.event_id, self.pos().x(), self.pos().y())
        elif change == QGraphicsItem.ItemSelectedHasChanged:
            self.refresh_pen()
        return super().itemChange(change, value)

    def refresh_links(self, links: Iterable["LinkItem"] = ()) -> None:
        self.links = [link for link in (links if links else self.links) if link is not None]