"""Диалоги макропериодов таймлайна и его настроек."""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from database import queries
from ui import time_utils
from ui.qt_time import DateInput, DateTimeInput

PERIOD_COLOR_NAMES = {
    "#7d5fff": "Фиолетовый",
    "#4a90d9": "Синий",
    "#2ecc71": "Зелёный",
    "#e6a23c": "Оранжевый",
    "#d63031": "Красный",
    "#9b59b6": "Пурпурный",
    "#16a085": "Бирюзовый",
    "#7f8c8d": "Серый",
}


def _color_icon(color: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class PeriodDialog(QDialog):
    """Создание и редактирование макропериода (например, «Первый поход»)."""

    def __init__(
        self,
        db,
        period_id: Optional[int] = None,
        start: Optional[float] = None,
        end: Optional[float] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.period_id = int(period_id) if period_id else None
        self.epoch = time_utils.parse_epoch(queries.get_timeline_epoch(db))
        self.saved = False
        self.deleted = False

        existing = queries.get_period(db, self.period_id) if self.period_id else None
        if existing is None:
            self.period_id = None
        self._existing = existing or {}

        if existing is not None:
            start_value = float(existing["start_time"])
            end_value = float(existing["end_time"])
        else:
            start_value = float(start if start is not None else 0.0)
            end_value = float(end if end is not None else start_value + time_utils.DAY)

        self.setWindowTitle("Макропериод" if existing else "Новый макропериод")
        self.setModal(True)
        self.resize(520, 240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Название периода:"))
        self.title_input = QLineEdit(str(self._existing.get("title", "")) or "")
        self.title_input.setPlaceholderText("Например: Предвоенный период, Первый поход")
        title_row.addWidget(self.title_input, 1)
        layout.addLayout(title_row)

        dates_row = QHBoxLayout()
        dates_row.addWidget(QLabel("Начало:"))
        self.start_edit = DateTimeInput(self.epoch)
        self.start_edit.set_seconds(start_value)
        dates_row.addWidget(self.start_edit, 1)

        dates_row.addWidget(QLabel("Конец:"))
        self.end_edit = DateTimeInput(self.epoch)
        self.end_edit.set_seconds(end_value)
        dates_row.addWidget(self.end_edit, 1)
        layout.addLayout(dates_row)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Цвет:"))
        self.color_combo = QComboBox()
        self.color_combo.setMinimumWidth(180)
        for color in queries.PERIOD_COLORS:
            name = PERIOD_COLOR_NAMES.get(color, color)
            self.color_combo.addItem(_color_icon(color), name, color)
        current_color = str(self._existing.get("color") or queries.PERIOD_COLORS[0])
        index = self.color_combo.findData(current_color)
        self.color_combo.setCurrentIndex(index if index >= 0 else 0)
        color_row.addWidget(self.color_combo)
        color_row.addStretch(1)
        layout.addLayout(color_row)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("HintLabel")
        layout.addWidget(self.hint_label)

        buttons = QHBoxLayout()
        if self.period_id:
            delete_btn = QPushButton("Удалить период")
            delete_btn.setObjectName("dangerButton")
            delete_btn.clicked.connect(self._on_delete)
            buttons.addWidget(delete_btn)
        buttons.addStretch(1)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        save_btn = QPushButton("Сохранить")
        save_btn.setObjectName("primaryButton")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)

        self.start_edit.valueChanged.connect(self._update_hint)
        self.end_edit.valueChanged.connect(self._update_hint)
        self._update_hint()
        self.title_input.setFocus()

    def _update_hint(self) -> None:
        start = self.start_edit.seconds()
        end = self.end_edit.seconds()
        if start is None or end is None:
            self.hint_label.setText("Дата в формате дд.мм.гггг чч:мм")
        elif end <= start:
            self.hint_label.setText("Конец периода должен быть позже начала.")
        else:
            self.hint_label.setText(f"Длительность: {time_utils.format_duration(end - start)}")

    def _on_save(self) -> None:
        title = self.title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "Название обязательно", "Введите название макропериода.")
            self.title_input.setFocus()
            return
        start = self.start_edit.seconds()
        end = self.end_edit.seconds()
        if start is None or end is None:
            QMessageBox.warning(self, "Неверная дата", "Введите даты в формате дд.мм.гггг чч:мм.")
            return
        if end <= start:
            QMessageBox.warning(self, "Неверный период", "Конец периода должен быть позже начала.")
            return
        color = self.color_combo.currentData() or queries.PERIOD_COLORS[0]
        try:
            if self.period_id:
                queries.update_period(self.db, self.period_id, title, start, end, color)
            else:
                new_id = queries.create_period(self.db, title, start, end, color)
                self.period_id = int(new_id) if new_id else None
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить период:\n{exc}")
            return
        self.saved = True
        self.accept()

    def _on_delete(self) -> None:
        if not self.period_id:
            return
        answer = QMessageBox.question(
            self,
            "Удаление периода",
            f"Удалить макропериод «{self._existing.get('title', '')}»?\nСобытия останутся на таймлайне.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            queries.delete_period(self.db, self.period_id)
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка удаления", f"Не удалось удалить период:\n{exc}")
            return
        self.deleted = True
        self.period_id = None
        self.accept()


class TimelineSettingsDialog(QDialog):
    """Дата отсчёта: какой реальный год соответствует нулю таймлайна."""

    def __init__(self, db, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        epoch = time_utils.parse_epoch(queries.get_timeline_epoch(db))

        self.setWindowTitle("Настройки таймлайна")
        self.setModal(True)
        self.resize(460, 220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Дата отсчёта (нулевая точка таймлайна):"))
        self.date_edit = DateInput()
        self.date_edit.set_date(epoch)
        layout.addWidget(self.date_edit)

        hint = QLabel(
            "Все даты на таймлайне считаются от этой точки. "
            "Для вымышленного мира поставьте, например, 1245 год — "
            "и события будут подписаны годами вашей истории."
        )
        hint.setWordWrap(True)
        hint.setObjectName("HintLabel")
        layout.addWidget(hint)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        save_btn = QPushButton("Сохранить")
        save_btn.setObjectName("primaryButton")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)

    def _on_save(self) -> None:
        date = self.date_edit.date()
        if date is None:
            QMessageBox.warning(self, "Неверная дата", "Введите дату в формате дд.мм.гггг.")
            return
        iso = f"{date.year:04d}-{date.month:02d}-{date.day:02d}"
        try:
            queries.set_meta(self.db, "timeline_epoch", iso)
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить настройки:\n{exc}")
            return
        self.accept()
