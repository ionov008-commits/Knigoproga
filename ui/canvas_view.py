"""Интерактивный холст: зум, панорамирование и прокладка связей."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from assets.theme import COLOR_ACCENT, COLOR_CANVAS_BG, COLOR_GRID, COLOR_GRID_MAJOR
from ui.event_node import EventNode
from ui.link_item import LinkItem, RubberBandLink

SCENE_EXTENT = 1_000_000.0  # виртуально бесконечное поле для панорамирования
MIN_ZOOM = 0.05
MAX_ZOOM = 4.0
ZOOM_STEP = 1.15
LOD_NODE_WIDTH = 28.0  # уже этой ширины на экране нода рисуется точкой


class CanvasView(QGraphicsView):
    """QGraphicsView с бесконечной сеткой, зумом и режимом связывания."""

    linkCompleted = Signal(int, int)  # source_event_id, target_event_id
    addEventRequested = Signal(QPointF)  # клик по пустому месту
    eventOpenRequested = Signal(int)  # двойной клик по ноде
    linkOpenRequested = Signal(int)  # двойной клик по связи
    zoomChanged = Signal(float, QPointF)  # применённый коэффициент и точка привязки
    panned = Signal(float, float)  # смещение мыши по X и Y в пикселях

    def __init__(self, scene: QGraphicsScene, parent: Optional[QWidget] = None) -> None:
        super().__init__(scene, parent)
        self.scene = scene
        self.link_mode = False
        self.link_source: Optional[EventNode] = None
        self._rubber: Optional[RubberBandLink] = None

        self._panning = False
        self._space_held = False
        self._pan_origin = QPointF()

        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setBackgroundBrush(QColor(COLOR_CANVAS_BG))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setMouseTracking(True)
        self.viewport().setCursor(Qt.ArrowCursor)

    # ------------------------------------------------------------ scene ---
    def configure_scene(self) -> None:
        self.scene.setSceneRect(-SCENE_EXTENT, -SCENE_EXTENT, SCENE_EXTENT * 2, SCENE_EXTENT * 2)

    # --------------------------------------------------------- zoom/pan ---
    def current_zoom(self) -> float:
        return self.transform().m11()

    def zoom_by(self, factor: float, anchor_view_pos: Optional[QPointF] = None) -> None:
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.current_zoom() * factor))
        factor = new_zoom / self.current_zoom()
        if abs(factor - 1.0) < 1e-6:
            return

        previous_anchor = self.transformationAnchor()
        if anchor_view_pos is not None:
            self.setTransformationAnchor(QGraphicsView.NoAnchor)
            before = self.mapToScene(anchor_view_pos.toPoint())
            self.scale(factor, factor)
            after = self.mapToScene(anchor_view_pos.toPoint())
            delta = after - before
            self.translate(delta.x(), delta.y())
        else:
            self.scale(factor, factor)
        self.setTransformationAnchor(previous_anchor)

        self.update_lod()
        anchor = anchor_view_pos if anchor_view_pos is not None else QPointF(self.viewport().rect().center())
        self.zoomChanged.emit(factor, anchor)

    def update_lod(self) -> None:
        """При сильном отдалении карточки событий превращаются в точки."""
        zoom = self.current_zoom()
        for item in self.scene.items():
            if isinstance(item, EventNode):
                item.apply_zoom(zoom)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self.centerOn(QPointF(0, 0))
        self.update_lod()

    def pan_horizontal_by_pixels(self, delta_x: float) -> None:
        """Сдвигает содержимое по X так же, как перетаскивание мышью."""
        h = self.horizontalScrollBar()
        before = h.value()
        h.setValue(before - int(round(delta_x)))
        applied = float(before - h.value())
        if abs(applied) > 0.5:
            self.panned.emit(applied, 0.0)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        factor = ZOOM_STEP if delta > 0 else 1.0 / ZOOM_STEP
        self.zoom_by(factor, event.position())
        event.accept()

    def _start_pan(self, event: QMouseEvent) -> None:
        self._panning = True
        self._pan_origin = event.position()
        self.viewport().setCursor(Qt.ClosedHandCursor)
        if self._rubber is not None and self.link_source is not None:
            self._rubber.update_curve(self.link_source.center(), self.mapToScene(event.position().toPoint()))

    def _do_pan(self, event: QMouseEvent) -> None:
        delta = event.position() - self._pan_origin
        self._pan_origin = event.position()
        h = self.horizontalScrollBar()
        v = self.verticalScrollBar()
        before_h = h.value()
        before_v = v.value()
        h.setValue(h.value() - int(delta.x()))
        v.setValue(v.value() - int(delta.y()))
        # Сообщаем только реально применённый сдвиг — на краях поля таймлайн тоже стоит.
        self.panned.emit(float(before_h - h.value()), float(before_v - v.value()))
        if self._rubber is not None and self.link_source is not None:
            self._rubber.update_curve(self.link_source.center(), self.mapToScene(event.position().toPoint()))

    def _stop_pan(self) -> None:
        self._panning = False
        self._update_cursor()

    def _update_cursor(self) -> None:
        if self._panning:
            self.viewport().setCursor(Qt.ClosedHandCursor)
        elif self._space_held:
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif self.link_mode:
            self.viewport().setCursor(Qt.CrossCursor)
        else:
            self.viewport().setCursor(Qt.ArrowCursor)

    # ------------------------------------------------------ link mode ---
    def set_link_mode(self, enabled: bool) -> None:
        self.link_mode = bool(enabled)
        if not self.link_mode:
            self.cancel_link_operation()
        self._update_cursor()

    def cancel_link_operation(self) -> None:
        if self.link_source is not None:
            self.link_source.set_connect_source(False)
            self.link_source = None
        self._remove_rubber()

    def _remove_rubber(self) -> None:
        if self._rubber is not None:
            self.scene.removeItem(self._rubber)
            self._rubber = None

    @staticmethod
    def node_for_item(item) -> Optional[EventNode]:
        """Поднимается от дочерних элементов (текст) к самой карточке события."""
        while item is not None and not isinstance(item, EventNode):
            item = item.parentItem()
        return item if isinstance(item, EventNode) else None

    def event_at(self, view_pos: QPointF) -> Optional[EventNode]:
        for item in self.items(view_pos.toPoint()):
            node = self.node_for_item(item)
            if node is not None:
                return node
        return None

    def handle_link_click(self, node: EventNode) -> None:
        """Первый клик — источник, второй — приёмник."""
        if self.link_source is None:
            self.link_source = node
            node.set_connect_source(True)
            self._rubber = RubberBandLink()
            self.scene.addItem(self._rubber)
            self._rubber.update_curve(node.center(), node.center())
            return

        source = self.link_source
        source.set_connect_source(False)
        self._remove_rubber()
        self.link_source = None

        if node is source:
            return  # клик по той же ноде — отмена
        self.linkCompleted.emit(source.event_id, node.event_id)

    # ------------------------------------------------------- mouse events ---
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and self._space_held
        ):
            self._start_pan(event)
            event.accept()
            return

        if event.button() == Qt.LeftButton and self.link_mode:
            node = self.event_at(event.position())
            if node is not None:
                self.handle_link_click(node)
            else:
                self.cancel_link_operation()  # клик мимо ноды — отмена
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            self._do_pan(event)
            event.accept()
            return
        if self._rubber is not None and self.link_source is not None:
            self._rubber.update_curve(self.link_source.center(), self.mapToScene(event.position().toPoint()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._panning and (event.button() == Qt.MiddleButton or event.button() == Qt.LeftButton):
            self._stop_pan()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            super().mouseDoubleClickEvent(event)
            return

        item = self.itemAt(event.position().toPoint())
        node = self.node_for_item(item)
        if node is not None:
            self.eventOpenRequested.emit(node.event_id)
        elif isinstance(item, LinkItem):
            self.linkOpenRequested.emit(item.link_id)
        elif item is None:
            self.addEventRequested.emit(self.mapToScene(event.position().toPoint()))
        event.accept()

    # ----------------------------------------- колбэки из графических элементов ---
    def event_double_clicked(self, node: EventNode) -> None:
        self.eventOpenRequested.emit(node.event_id)

    def link_double_clicked(self, link: LinkItem) -> None:
        self.linkOpenRequested.emit(link.link_id)

    def mark_dirty(self) -> None:
        """Нода сдвинулась — координаты уже пишутся в БД, помечаем проект."""
        main = self.window()
        if hasattr(main, "mark_modified"):
            main.mark_modified()

    # ------------------------------------------------------------- keys ---
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self._update_cursor()
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self.link_mode:
            self.cancel_link_operation()
            main = self.window()
            if hasattr(main, "toggle_link_mode"):
                main.toggle_link_mode(False)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            self._update_cursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        self._space_held = False
        self._update_cursor()
        super().focusOutEvent(event)

    # -------------------------------------------------------- background ---
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor(COLOR_CANVAS_BG))

        zoom = self.current_zoom()
        minor_step = 25.0
        while minor_step * zoom < 12:  # слишком густая сетка при отдалении
            minor_step *= 2
        major_step = minor_step * 4

        left = rect.left() - (rect.left() % minor_step)
        top = rect.top() - (rect.top() % minor_step)

        minor_lines = []
        major_lines = []
        x = left
        while x < rect.right():
            (major_lines if abs(x % major_step) < 1e-6 else minor_lines).append((QPointF(x, rect.top()), QPointF(x, rect.bottom())))
            x += minor_step
        y = top
        while y < rect.bottom():
            (major_lines if abs(y % major_step) < 1e-6 else minor_lines).append((QPointF(rect.left(), y), QPointF(rect.right(), y)))
            y += minor_step

        painter.setPen(QPen(QColor(COLOR_GRID), 0.0))
        for a, b in minor_lines:
            painter.drawLine(a, b)
        painter.setPen(QPen(QColor(COLOR_GRID_MAJOR), 0.0))
        for a, b in major_lines:
            painter.drawLine(a, b)

        # Оси координат для ориентации на бесконечном холсте.
        painter.setPen(QPen(QColor("#3a2f66"), 0.0))
        if rect.left() <= 0 <= rect.right():
            painter.drawLine(QPointF(0, rect.top()), QPointF(0, rect.bottom()))
        if rect.top() <= 0 <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), 0), QPointF(rect.right(), 0))

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        # Источник связи уже подсвечен контуром ноды — дополнительная
        # графика здесь не нужна, оставляем хук для будущих подсказок.
        return