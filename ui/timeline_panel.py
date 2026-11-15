"""Таймлайн — верхняя полоса рабочей области.

Полоса встроена над холстом: сверху цветные зоны макропериодов,
линейка времени, ниже — дорожки событий и курсор вставки. При сильном
отдалении события рисуются точками, при приближении — прямоугольниками.
"""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from assets.theme import (
    COLOR_ACCENT,
    COLOR_BORDER,
    COLOR_CANVAS_BG,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
)
from database import queries
from ui import time_utils
from ui.dialog_period import TimelineSettingsDialog

DEFAULT_FALLBACK_WIDTH = 900.0
PLAYHEAD_COLOR = "#ff7675"


class TimelineWidget(QWidget):
    """Полотно встроенного таймлайна."""

    eventOpenRequested = Signal(int)
    addEventRequested = Signal(float)
    periodEditRequested = Signal(int)
    addPeriodRequested = Signal(float, float)
    timesChanged = Signal()
    viewChanged = Signal()
    contentHeightChanged = Signal()
    zoomRequested = Signal(float, float)  # коэффициент, X-привязка
    panRequested = Signal(float)  # горизонтальный сдвиг в пикселях

    PERIOD_BAND_H = 16.0
    HEADER_H = 24.0
    ROW_H = 22.0
    BAR_H = 16.0
    BOTTOM_PAD = 6.0
    DOT_THRESHOLD = 16.0
    EDGE = 6.0

    def __init__(self, db, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self._epoch = time_utils.DEFAULT_EPOCH
        self._events: list[dict] = []
        self._periods: list[dict] = []
        self._lanes: dict[int, int] = {}
        self._lane_count = 0

        self._seconds_per_pixel: Optional[float] = None
        self._view_start = 0.0
        self._needs_autofit = True
        self._playhead: Optional[float] = None

        self._drag: Optional[dict] = None
        self._panning_from: Optional[float] = None
        self._dragging_playhead = False
        self._hover: Optional[tuple] = None
        self._selected_event: Optional[int] = None
        self._selected_period: Optional[int] = None

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(320)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)

    # ------------------------------------------------------------ геометрия ---
    def _width(self) -> float:
        width = self.width()
        return float(width) if width > 50 else DEFAULT_FALLBACK_WIDTH

    @property
    def seconds_per_pixel(self) -> float:
        if self._seconds_per_pixel is None:
            self._seconds_per_pixel = (30.0 * time_utils.DAY) / self._width()
        return self._seconds_per_pixel

    def visible_span(self) -> float:
        return self.seconds_per_pixel * self._width()

    def time_to_x(self, seconds: float) -> float:
        return (float(seconds) - self._view_start) / self.seconds_per_pixel

    def x_to_time(self, x: float) -> float:
        return self._view_start + float(x) * self.seconds_per_pixel

    def _ruler_top(self) -> float:
        return self.PERIOD_BAND_H

    def _lanes_top(self) -> float:
        return self.PERIOD_BAND_H + self.HEADER_H

    def _content_height(self) -> float:
        return self._lanes_top() + max(1, self._lane_count) * self.ROW_H + self.BOTTOM_PAD

    def _update_geometry(self) -> None:
        height = int(round(self._content_height()))
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
            self.setMaximumHeight(height)
            self.contentHeightChanged.emit()
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        return QSize(int(self._width()), int(self._content_height()))

    # -------------------------------------------------------------- курсор ---
    def playhead(self) -> Optional[float]:
        return self._playhead

    def set_playhead(self, seconds: float) -> None:
        low, high = time_utils.seconds_range(self._epoch)
        self._playhead = min(max(float(seconds), low), high)
        self.update()

    def advance_playhead(self, seconds: float) -> None:
        self.set_playhead(seconds)

    def next_event_range(self) -> tuple[float, float]:
        """Куда поставить новое событие: от курсора вставки."""
        duration = self.default_duration()
        low, high = time_utils.seconds_range(self._epoch)
        if self._playhead is None:
            self._playhead = self.x_to_time(self._width() / 2.0)
        start = min(max(self._playhead, low), max(low, high - duration))
        end = min(start + duration, high)
        return start, end

    # -------------------------------------------------------------- данные ---
    def reload(self, autofit: bool = False) -> None:
        """Перечитывает данные. Масштаб пользователя сохраняется."""
        if self.db is None or not getattr(self.db, "is_open", False):
            self._events = []
            self._periods = []
            self._lanes = {}
            self._lane_count = 0
            self._epoch = time_utils.DEFAULT_EPOCH
            self._selected_event = None
            self._selected_period = None
            self._playhead = None
            self._update_geometry()
            self.update()
            return

        had_events = bool(self._events)
        self._epoch = time_utils.parse_epoch(queries.get_timeline_epoch(self.db))
        self._events = queries.get_timed_events(self.db)
        self._periods = queries.get_periods(self.db)
        self._compute_lanes()
        self._update_geometry()

        if self._playhead is None:
            if self._events:
                self._playhead = max(float(event["time_end"]) for event in self._events)
            else:
                self._playhead = 0.0

        # Вписываем всё только при первом заполнении или по явному запросу.
        should_fit = autofit or self._seconds_per_pixel is None or (not had_events and self._events)
        if should_fit:
            self._needs_autofit = True
            self._maybe_autofit()
        else:
            self._clamp_zoom()
            self._clamp_view()
        self.update()
        self.viewChanged.emit()

    def _compute_lanes(self) -> None:
        """Минимальное число дорожек, чтобы отрезки не перекрывались."""
        self._lanes = {}
        lane_ends: list[float] = []
        for event in sorted(self._events, key=lambda item: float(item["time_start"])):
            start = float(event["time_start"])
            end = float(event["time_end"])
            placed = False
            for index, lane_end in enumerate(lane_ends):
                if lane_end <= start + 1e-6:
                    lane_ends[index] = end
                    self._lanes[int(event["id"])] = index
                    placed = True
                    break
            if not placed:
                lane_ends.append(end)
                self._lanes[int(event["id"])] = len(lane_ends) - 1
        self._lane_count = len(lane_ends)

    # ------------------------------------------------------------ масштаб ---
    def _min_spp(self) -> float:
        return time_utils.MIN_SPAN / self._width()

    def _max_spp(self) -> float:
        return time_utils.MAX_SPAN / self._width()

    def _clamp_zoom(self) -> None:
        low = self._min_spp()
        high = self._max_spp()
        spp = self.seconds_per_pixel
        clamped = min(max(spp, low), high)
        if not math.isclose(clamped, spp, rel_tol=1e-12):
            self._seconds_per_pixel = clamped

    def _clamp_view(self) -> None:
        """Не даёт уехать за пределы дат, которые можно отобразить."""
        low, high = time_utils.seconds_range(self._epoch)
        span = self.visible_span()
        if high - low <= span:
            self._view_start = low
            return
        self._view_start = min(max(self._view_start, low), high - span)

    def _maybe_autofit(self) -> None:
        if self._needs_autofit and self.width() > 50:
            self._needs_autofit = False
            self.fit_all()

    def fit_all(self) -> None:
        moments: list[float] = []
        for event in self._events:
            moments.extend([float(event["time_start"]), float(event["time_end"])])
        for period in self._periods:
            moments.extend([float(period["start_time"]), float(period["end_time"])])

        width = self._width()
        if not moments:
            span = min(max(30.0 * time_utils.DAY, time_utils.MIN_SPAN), time_utils.MAX_SPAN)
            self._seconds_per_pixel = span / width
            self._view_start = -span / 2.0
        else:
            low, high = min(moments), max(moments)
            if high - low < time_utils.MINUTE:
                high = low + time_utils.MINUTE
            pad = max((high - low) * 0.08, time_utils.MINUTE)
            span = min(max((high - low) + 2 * pad, time_utils.MIN_SPAN), time_utils.MAX_SPAN)
            self._seconds_per_pixel = span / width
            self._view_start = low - pad
        self._clamp_zoom()
        self._clamp_view()
        self.update()
        self.viewChanged.emit()

    def zoom_by(self, factor: float, anchor_x: Optional[float] = None) -> None:
        if anchor_x is None:
            anchor_x = self._width() / 2.0
        old = self.seconds_per_pixel
        new = min(max(old * factor, self._min_spp()), self._max_spp())
        if math.isclose(new, old, rel_tol=1e-12):
            return
        anchor_time = self.x_to_time(anchor_x)
        self._seconds_per_pixel = new
        self._view_start = anchor_time - anchor_x * new
        self._clamp_view()
        self.update()
        self.viewChanged.emit()

    def pan_by_pixels(self, delta_x: float) -> None:
        self._view_start -= delta_x * self.seconds_per_pixel
        self._clamp_view()
        self.update()
        self.viewChanged.emit()

    def center_on(self, seconds: float) -> None:
        span = self.visible_span()
        self._view_start = seconds - span / 2.0
        self._clamp_view()
        self.update()
        self.viewChanged.emit()

    def ensure_visible(self, seconds: float) -> None:
        """Прокручивает полосу, если момент оказался вне видимой области."""
        span = self.visible_span()
        if not (self._view_start <= seconds <= self._view_start + span):
            self.center_on(seconds)

    def set_span(self, span: float, center: Optional[float] = None) -> None:
        """Задаёт ширину видимого окна в секундах (с ограничением масштаба)."""
        span = min(max(float(span), self._min_spp() * self._width()), self._max_spp() * self._width())
        width = self._width()
        if center is None:
            center = self._view_start + self.visible_span() / 2.0
        self._seconds_per_pixel = span / width
        self._view_start = center - span / 2.0
        self._clamp_view()
        self.update()
        self.viewChanged.emit()

    def default_duration(self) -> float:
        return min(max(self.visible_span() / 12.0, time_utils.MINUTE), 7 * time_utils.DAY)

    def default_period_duration(self) -> float:
        return max(self.visible_span() / 8.0, time_utils.HOUR)

    # ------------------------------------------------- действия по кнопкам ---
    def add_event_at_center(self) -> None:
        self._maybe_autofit()
        self.addEventRequested.emit(self.x_to_time(self._width() / 2.0))

    def add_period_at_center(self) -> None:
        self._maybe_autofit()
        center = self.x_to_time(self._width() / 2.0)
        half = self.default_period_duration() / 2.0
        self.addPeriodRequested.emit(center - half, center + half)

    # ------------------------------------------------------- прямоугольники ---
    def _event_rect(self, event: dict) -> QRectF:
        lane = self._lanes.get(int(event["id"]), 0)
        x1 = self.time_to_x(float(event["time_start"]))
        x2 = self.time_to_x(float(event["time_end"]))
        top = self._lanes_top() + lane * self.ROW_H + (self.ROW_H - self.BAR_H) / 2.0
        width = x2 - x1
        if width < self.DOT_THRESHOLD:
            # Точка: хит-зона — квадрат вокруг середины события.
            center = (x1 + x2) / 2.0
            return QRectF(center - 6.0, top, 12.0, self.BAR_H)
        return QRectF(x1, top, width, self.BAR_H)

    def _period_chip_rect(self, period: dict) -> QRectF:
        x1 = self.time_to_x(float(period["start_time"]))
        x2 = self.time_to_x(float(period["end_time"]))
        return QRectF(x1 + 1.0, 2.0, max(5.0, x2 - x1 - 2.0), self.PERIOD_BAND_H - 4.0)

    def _period_zone_rect(self, period: dict) -> QRectF:
        x1 = self.time_to_x(float(period["start_time"]))
        x2 = self.time_to_x(float(period["end_time"]))
        return QRectF(x1, 0.0, max(2.0, x2 - x1), float(self.height()))

    def _zone_for(self, rect: QRectF, pos: QPointF) -> str:
        distance_left = abs(pos.x() - rect.left())
        distance_right = abs(pos.x() - rect.right())
        nearest = min(distance_left, distance_right)
        if nearest <= self.EDGE:
            return "left" if distance_left <= distance_right else "right"
        return "body"

    def _hit_test(self, pos: QPointF) -> tuple:
        for event in self._events:
            rect = self._event_rect(event).adjusted(-1, -3, 1, 3)
            if rect.contains(pos):
                if rect.width() <= self.DOT_THRESHOLD:
                    zone = "body"  # точку можно только перетаскивать
                else:
                    zone = self._zone_for(rect, pos)
                return ("event", int(event["id"]), zone, event)
        if pos.y() <= self.PERIOD_BAND_H:
            for period in self._periods:
                chip = self._period_chip_rect(period)
                if chip.contains(pos):
                    return ("period", int(period["id"]), self._zone_for(chip, pos), period)
        return (None, None, None, None)

    # ------------------------------------------------------------ отрисовка ---
    def paintEvent(self, event) -> None:
        self._maybe_autofit()
        self._clamp_zoom()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        width = self.width()
        height = self.height()
        painter.fillRect(self.rect(), QColor(COLOR_CANVAS_BG))

        self._paint_period_zones(painter, width, height)
        self._paint_ruler(painter, width)
        self._paint_lanes(painter, width)
        self._paint_events(painter)
        self._paint_period_chips(painter, width)
        self._paint_playhead(painter, height)

        painter.setPen(QPen(QColor("#2b2b2e"), 1))
        painter.drawLine(QPointF(0, height - 1), QPointF(width, height - 1))

    def _paint_period_zones(self, painter: QPainter, width: float, height: float) -> None:
        """Макропериоды — цветные зоны на всю высоту полосы."""
        for period in self._periods:
            x1 = max(self.time_to_x(float(period["start_time"])), -4000.0)
            x2 = min(self.time_to_x(float(period["end_time"])), width + 4000.0)
            if x2 < -10 or x1 > width + 10:
                continue
            color = QColor(str(period.get("color") or COLOR_ACCENT))
            fill = QColor(color)
            fill.setAlpha(24 if not self._is_period_hovered(int(period["id"])) else 40)
            painter.fillRect(QRectF(x1, 0.0, max(2.0, x2 - x1), height), fill)

            line = QColor(color)
            line.setAlpha(110)
            painter.setPen(QPen(line, 1))
            if -2 <= x1 <= width + 2:
                painter.drawLine(QPointF(x1, 0), QPointF(x1, height))
            if -2 <= x2 <= width + 2:
                painter.drawLine(QPointF(x2, 0), QPointF(x2, height))

    def _paint_ruler(self, painter: QPainter, width: float) -> None:
        top = self._ruler_top()
        background = QColor("#1b1b1c")
        background.setAlpha(226)
        painter.fillRect(QRectF(0, top, width, self.HEADER_H), background)

        spp = self.seconds_per_pixel
        step = time_utils.choose_tick_step(spp, 90.0)
        view_end = self.x_to_time(width)

        painter.setFont(QFont("Segoe UI", 8))

        if step < 20 * time_utils.DAY:
            minor_step = step / 5.0
            painter.setPen(QPen(QColor("#2a2a2d"), 1))
            minor_moment = math.floor(self._view_start / minor_step) * minor_step
            limit = view_end + minor_step
            while minor_moment <= limit:
                x = self.time_to_x(minor_moment)
                if -10 <= x <= width + 10:
                    painter.drawLine(
                        QPointF(x, top + self.HEADER_H - 4),
                        QPointF(x, top + self.HEADER_H),
                    )
                minor_moment += minor_step

        for moment, label in time_utils.calendar_ticks(
            self._view_start, view_end, step, self._epoch
        ):
            x = self.time_to_x(moment)
            if not (-100 <= x <= width + 100):
                continue
            painter.setPen(QPen(QColor("#3a3a40"), 1))
            painter.drawLine(QPointF(x, top + self.HEADER_H - 7), QPointF(x, top + self.HEADER_H))
            painter.setPen(QColor(COLOR_TEXT_MUTED))
            if x < width - 70:
                painter.drawText(
                    QRectF(x + 4, top + 3, 110, 15),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    label,
                )
            else:
                painter.drawText(
                    QRectF(x - 94, top + 3, 90, 15),
                    Qt.AlignRight | Qt.AlignVCenter,
                    label,
                )

        painter.setPen(QPen(QColor("#2c2c30"), 1))
        painter.drawLine(QPointF(0, top + self.HEADER_H), QPointF(width, top + self.HEADER_H))

    def _paint_lanes(self, painter: QPainter, width: float) -> None:
        top = self._lanes_top()
        lane_count = max(1, self._lane_count)
        for lane in range(lane_count):
            y = top + lane * self.ROW_H
            if lane % 2 == 1:
                painter.fillRect(QRectF(0, y, width, self.ROW_H), QColor(255, 255, 255, 4))
            painter.setPen(QPen(QColor("#202023"), 1))
            painter.drawLine(QPointF(0, y), QPointF(width, y))

        if not self._events:
            painter.setPen(QColor(COLOR_TEXT_MUTED))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(
                QRectF(12, top, width - 24, self.ROW_H),
                Qt.AlignLeft | Qt.AlignVCenter,
                "Двойной клик по полосе — новое событие; оно сразу встанет на таймлайн.",
            )

    def _paint_events(self, painter: QPainter) -> None:
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        width = self.width()

        for event in self._events:
            event_id = int(event["id"])
            x1 = self.time_to_x(float(event["time_start"]))
            x2 = self.time_to_x(float(event["time_end"]))
            bar_width = x2 - x1
            lane = self._lanes.get(event_id, 0)
            center_y = self._lanes_top() + lane * self.ROW_H + self.ROW_H / 2.0
            if x2 < -20 or x1 > width + 20:
                continue

            selected = event_id == self._selected_event
            hovered = self._is_event_hovered(event_id)

            if bar_width < self.DOT_THRESHOLD:
                # При сильном отдалении событие превращается в точку.
                center = QPointF((x1 + x2) / 2.0, center_y)
                radius = 5.0 if (hovered or selected) else 4.0
                color = QColor(PLAYHEAD_COLOR if selected else COLOR_ACCENT)
                painter.setPen(QPen(color.lighter(140), 1.2))
                painter.setBrush(color)
                painter.drawEllipse(center, radius, radius)
                if hovered or selected:
                    painter.setPen(QPen(QColor("#ffffff"), 1))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(center, radius + 2.0, radius + 2.0)
                continue

            rect = QRectF(x1, center_y - self.BAR_H / 2.0, bar_width, self.BAR_H)
            visible = rect.intersected(QRectF(-300, rect.top(), width + 600, rect.height()))
            fill = QColor("#3a3366") if selected else (QColor("#31333a") if hovered else QColor("#2b2d30"))
            border = QColor(PLAYHEAD_COLOR if selected else COLOR_ACCENT) if (selected or hovered) else QColor(COLOR_BORDER)
            painter.setBrush(fill)
            painter.setPen(QPen(border, 1.3))
            painter.drawRoundedRect(visible, 3, 3)

            if visible.width() >= 7:
                painter.fillRect(
                    QRectF(visible.left() + 1, visible.top() + 2, 2.5, visible.height() - 4),
                    QColor(COLOR_ACCENT),
                )

            text = str(event.get("title") or "Без названия")
            text_rect = QRectF(visible.left() + 9, visible.top(), visible.width() - 14, visible.height())
            if text_rect.width() > 18:
                painter.setPen(QColor(COLOR_TEXT))
                painter.drawText(
                    text_rect,
                    Qt.AlignLeft | Qt.AlignVCenter,
                    metrics.elidedText(text, Qt.ElideRight, int(text_rect.width())),
                )

            if (hovered or selected) and visible.width() > 12:
                painter.setPen(QPen(QColor(PLAYHEAD_COLOR if selected else COLOR_ACCENT), 2))
                painter.drawLine(
                    QPointF(visible.left() + 2, visible.top() + 3),
                    QPointF(visible.left() + 2, visible.bottom() - 3),
                )
                painter.drawLine(
                    QPointF(visible.right() - 2, visible.top() + 3),
                    QPointF(visible.right() - 2, visible.bottom() - 3),
                )

    def _paint_period_chips(self, painter: QPainter, width: float) -> None:
        font = QFont("Segoe UI", 7)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        for period in self._periods:
            chip = self._period_chip_rect(period)
            if chip.right() < -20 or chip.left() > width + 20:
                continue
            visible = chip.intersected(QRectF(-200, chip.top(), width + 400, chip.height()))
            color = QColor(str(period.get("color") or COLOR_ACCENT))
            fill = QColor(color)
            fill.setAlpha(170 if self._is_period_hovered(int(period["id"])) else 130)
            painter.setBrush(fill)
            painter.setPen(QPen(color.lighter(130), 1))
            painter.drawRoundedRect(visible, 3, 3)

            title = str(period.get("title") or "Период")
            text_rect = QRectF(visible.left() + 5, visible.top(), visible.width() - 10, visible.height())
            if text_rect.width() > 16:
                painter.setPen(QColor("#ffffff"))
                painter.drawText(
                    text_rect,
                    Qt.AlignCenter,
                    metrics.elidedText(title, Qt.ElideRight, int(text_rect.width())),
                )

    def _paint_playhead(self, painter: QPainter, height: float) -> None:
        if self._playhead is None:
            return
        x = self.time_to_x(self._playhead)
        if not (-10 <= x <= self.width() + 10):
            return
        color = QColor(PLAYHEAD_COLOR)
        painter.setPen(QPen(color, 1.4))
        painter.drawLine(QPointF(x, self.PERIOD_BAND_H), QPointF(x, height))
        triangle = QPolygonF(
            [
                QPointF(x - 5, self.PERIOD_BAND_H),
                QPointF(x + 5, self.PERIOD_BAND_H),
                QPointF(x, self.PERIOD_BAND_H + 7),
            ]
        )
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(triangle)

    def _is_event_hovered(self, event_id: int) -> bool:
        return bool(self._hover and self._hover[0] == "event" and self._hover[1] == event_id)

    def _is_period_hovered(self, period_id: int) -> bool:
        return bool(self._hover and self._hover[0] == "period" and self._hover[1] == period_id)

    # ----------------------------------------------------------- курсор/подсказки ---
    def _update_hover(self, pos: QPointF) -> None:
        hit = self._hit_test(pos)
        previous = self._hover
        self._hover = (hit[0], hit[1], hit[2]) if hit[0] else None
        if hit[0] == "event":
            event = hit[3]
            text = (
                f"{event.get('title')}\n"
                f"{time_utils.format_range(float(event['time_start']), float(event['time_end']), self._epoch)}"
                f"  ·  {time_utils.format_duration(float(event['time_end']) - float(event['time_start']))}"
            )
            self.setToolTip(text)
            self.setCursor(Qt.SizeHorCursor if hit[2] in ("left", "right") else Qt.OpenHandCursor)
        elif hit[0] == "period":
            period = hit[3]
            text = (
                f"{period.get('title')}\n"
                f"{time_utils.format_range(float(period['start_time']), float(period['end_time']), self._epoch)}"
            )
            self.setToolTip(text)
            self.setCursor(Qt.SizeHorCursor if hit[2] in ("left", "right") else Qt.OpenHandCursor)
        else:
            if previous is not None:
                self.setToolTip("")
            self.setCursor(Qt.ArrowCursor)
        if previous != self._hover:
            self.update()

    # ------------------------------------------------------------ мышь ---
    def _near_playhead(self, x: float) -> bool:
        if self._playhead is None:
            return False
        return abs(self.time_to_x(self._playhead) - x) <= 4.0

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._maybe_autofit()
        self._clamp_zoom()
        pos = event.position()

        if event.button() == Qt.MiddleButton:
            self._panning_from = pos.x()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        if pos.y() < self._lanes_top() and self._near_playhead(pos.x()):
            # Курсор вставки тянется за верхнюю часть (линейка и зоны).
            self._dragging_playhead = True
            self.setCursor(Qt.SizeHorCursor)
            event.accept()
            return

        kind, ident, zone, obj = self._hit_test(pos)
        if kind == "event":
            self._selected_event = ident
            self._selected_period = None
            mode = {"left": "resize-left", "right": "resize-right"}.get(zone, "move")
            self._drag = {
                "kind": "event",
                "id": ident,
                "mode": mode,
                "press_x": pos.x(),
                "start": float(obj["time_start"]),
                "end": float(obj["time_end"]),
            }
            self.setCursor(Qt.SizeHorCursor if mode != "move" else Qt.ClosedHandCursor)
        elif kind == "period":
            self._selected_period = ident
            self._selected_event = None
            mode = {"left": "resize-left", "right": "resize-right"}.get(zone, "move")
            self._drag = {
                "kind": "period",
                "id": ident,
                "mode": mode,
                "press_x": pos.x(),
                "start": float(obj["start_time"]),
                "end": float(obj["end_time"]),
                "color": str(obj.get("color") or queries.PERIOD_COLORS[0]),
                "title": str(obj.get("title") or ""),
            }
            self.setCursor(Qt.SizeHorCursor if mode != "move" else Qt.ClosedHandCursor)
        else:
            self._selected_event = None
            self._selected_period = None
            self.set_playhead(self.x_to_time(pos.x()))
            self._panning_from = pos.x()
            self.setCursor(Qt.ClosedHandCursor)

        self.update()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        if self._dragging_playhead:
            self.set_playhead(self.x_to_time(pos.x()))
            self.viewChanged.emit()
            return

        if self._panning_from is not None:
            delta = pos.x() - self._panning_from
            self._panning_from = pos.x()
            # Панорама идёт через холст — он и таймлайн движутся вместе.
            self.panRequested.emit(delta)
            return

        if self._drag is not None:
            self._apply_drag(pos)
            return

        self._update_hover(pos)
        super().mouseMoveEvent(event)

    def _apply_drag(self, pos: QPointF) -> None:
        drag = self._drag
        if drag is None:
            return
        delta_time = (pos.x() - drag["press_x"]) * self.seconds_per_pixel
        start, end = drag["start"], drag["end"]
        min_duration = max(60.0, self.seconds_per_pixel * 3.0)

        low, high = time_utils.seconds_range(self._epoch)
        if drag["mode"] == "move":
            duration = max(end - start, min_duration)
            new_start = min(max(start + delta_time, low), max(low, high - duration))
            new_end = new_start + duration
        elif drag["mode"] == "resize-left":
            new_end = min(end, high)
            new_start = max(min(start + delta_time, new_end - min_duration), low)
        else:
            new_start = max(start, low)
            new_end = min(max(end + delta_time, new_start + min_duration), high)

        if drag["kind"] == "event":
            try:
                queries.update_event_time(self.db, drag["id"], new_start, new_end)
            except Exception:  # noqa: BLE001
                return
            for item in self._events:
                if int(item["id"]) == drag["id"]:
                    item["time_start"] = new_start
                    item["time_end"] = new_end
                    break
        else:
            try:
                queries.update_period(
                    self.db,
                    drag["id"],
                    drag["title"],
                    new_start,
                    new_end,
                    drag["color"],
                )
            except Exception:  # noqa: BLE001
                return
            for item in self._periods:
                if int(item["id"]) == drag["id"]:
                    item["start_time"] = new_start
                    item["end_time"] = new_end
                    break

        # Инкрементально: следующее движение считается от уже применённых значений.
        drag["press_x"] = pos.x()
        drag["start"] = new_start
        drag["end"] = new_end
        self.update()
        self.timesChanged.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        had_drag = self._drag is not None
        if self._dragging_playhead:
            self._dragging_playhead = False
        if self._drag is not None:
            self._drag = None
            self._compute_lanes()
            self._update_geometry()
            self.timesChanged.emit()
            self.update()
        if self._panning_from is not None:
            self._panning_from = None
        if event.button() == Qt.LeftButton or event.button() == Qt.MiddleButton:
            self.unsetCursor()
        if had_drag:
            self._update_hover(event.position())
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._maybe_autofit()
        self._clamp_zoom()
        # Двойной клик мог начать перетаскивание — сбрасываем состояние.
        self._drag = None
        self._panning_from = None
        self._dragging_playhead = False
        self.unsetCursor()

        pos = event.position()
        kind, ident, _zone, _obj = self._hit_test(pos)
        if kind == "event":
            self.eventOpenRequested.emit(int(ident))
        elif kind == "period":
            self.periodEditRequested.emit(int(ident))
        else:
            moment = self.x_to_time(pos.x())
            self.set_playhead(moment)
            if pos.y() <= self.PERIOD_BAND_H:
                half = self.default_period_duration() / 2.0
                self.addPeriodRequested.emit(moment - half, moment + half)
            else:
                self.addEventRequested.emit(moment)
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._maybe_autofit()
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            event.ignore()
            return
        if event.modifiers() & Qt.ShiftModifier:
            # Прокрутка идёт через холст, чтобы поле и таймлайн не расходились.
            self.panRequested.emit(-(delta / 120.0) * 40.0)
        else:
            # Колесо вверх приближает всё рабочее поле вместе с полосой.
            factor = 1.15 if delta > 0 else 1.0 / 1.15
            self.zoomRequested.emit(factor, event.position().x())
        event.accept()

    def leaveEvent(self, event) -> None:
        self._hover = None
        self.unsetCursor()
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._maybe_autofit()
        self._clamp_zoom()
        self._clamp_view()
        self._update_geometry()
        self.viewChanged.emit()

    # ------------------------------------------------------------ контекст ---
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self._maybe_autofit()
        self._clamp_zoom()
        pos = QPointF(event.pos())
        kind, ident, _zone, _obj = self._hit_test(pos)
        menu = QMenu(self)

        if kind == "event":
            open_action = menu.addAction("Открыть событие")
            remove_action = menu.addAction("Убрать с таймлайна")
            chosen = menu.exec(event.globalPos())
            if chosen is open_action:
                self.eventOpenRequested.emit(int(ident))
            elif chosen is remove_action:
                self._remove_from_timeline(int(ident))
        elif kind == "period":
            edit_action = menu.addAction("Изменить макропериод")
            delete_action = menu.addAction("Удалить макропериод")
            chosen = menu.exec(event.globalPos())
            if chosen is edit_action:
                self.periodEditRequested.emit(int(ident))
            elif chosen is delete_action:
                self._delete_period(int(ident))
        else:
            moment = self.x_to_time(pos.x())
            add_event = menu.addAction("Добавить событие здесь")
            add_period = menu.addAction("Добавить макропериод здесь")
            chosen = menu.exec(event.globalPos())
            if chosen is add_event:
                self.set_playhead(moment)
                self.addEventRequested.emit(moment)
            elif chosen is add_period:
                half = self.default_period_duration() / 2.0
                self.addPeriodRequested.emit(moment - half, moment + half)
        event.accept()

    def _remove_from_timeline(self, event_id: int) -> None:
        try:
            queries.clear_event_time(self.db, event_id)
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка", f"Не удалось убрать событие с таймлайна:\n{exc}")
            return
        self._events = [item for item in self._events if int(item["id"]) != event_id]
        self._selected_event = None
        self._compute_lanes()
        self._update_geometry()
        self.update()
        self.timesChanged.emit()

    def _delete_period(self, period_id: int) -> None:
        answer = QMessageBox.question(
            self,
            "Удаление периода",
            "Удалить этот макропериод?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            queries.delete_period(self.db, period_id)
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка", f"Не удалось удалить период:\n{exc}")
            return
        self._periods = [item for item in self._periods if int(item["id"]) != period_id]
        self._selected_period = None
        self.update()
        self.timesChanged.emit()

class TimelinePanel(QWidget):
    """Встроенная в рабочую область полоса таймлайна без собственной панели."""

    eventOpenRequested = Signal(int)
    addEventRequested = Signal(float)
    periodEditRequested = Signal(int)
    addPeriodRequested = Signal(float, float)
    timesChanged = Signal()
    zoomRequested = Signal(float, float)
    panRequested = Signal(float)

    def __init__(self, db, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.setObjectName("TimelinePanel")
        self.setMinimumHeight(70)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.widget = TimelineWidget(db)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.widget)
        layout.addWidget(self.scroll, 1)

        self.widget.eventOpenRequested.connect(self.eventOpenRequested)
        self.widget.addEventRequested.connect(self.addEventRequested)
        self.widget.periodEditRequested.connect(self.periodEditRequested)
        self.widget.addPeriodRequested.connect(self.addPeriodRequested)
        self.widget.timesChanged.connect(self.timesChanged)
        self.widget.zoomRequested.connect(self.zoomRequested)
        self.widget.panRequested.connect(self.panRequested)
        self.widget.contentHeightChanged.connect(self._sync_height)
        self._sync_height()

    def _sync_height(self) -> None:
        """Полоса занимает ровно столько, сколько нужно её содержимому."""
        content = self.widget.minimumHeight() or 70
        self.setFixedHeight(min(max(content + 2, 70), 300))

    # ------------------------------------------------------------- actions ---
    def reload(self, autofit: bool = False) -> None:
        self.widget.reload(autofit=autofit)
        self._sync_height()

    def scale_text(self) -> str:
        return f"Таймлайн: {time_utils.format_duration(self.widget.visible_span())}"

    def add_event(self) -> None:
        self.widget.add_event_at_center()

    def add_period(self) -> None:
        self.widget.add_period_at_center()

    def fit(self) -> None:
        self.widget.fit_all()

    def edit_epoch(self, parent=None) -> None:
        if self.db is None or not getattr(self.db, "is_open", False):
            return
        dialog = TimelineSettingsDialog(self.db, parent or self)
        if dialog.exec() == dialog.Accepted:
            self.widget.reload()
