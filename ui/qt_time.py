"""Редакторы даты и времени для таймлайна.

Стандартный QDateTimeEdit ограничен 1752 годом, поэтому для вымышленных
миров используются собственные текстовые поля с валидацией и поддержкой
любого года от 1 до 9999.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from ui import time_utils

DATE_FORMAT = "%d.%m.%Y"
DATETIME_FORMATS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y")


def format_date(value: _dt.datetime) -> str:
    return f"{value.day:02d}.{value.month:02d}.{value.year:04d}"


def format_datetime(value: _dt.datetime) -> str:
    return f"{format_date(value)} {value.hour:02d}:{value.minute:02d}"


def parse_date(text: str) -> Optional[_dt.datetime]:
    try:
        value = _dt.datetime.strptime(" ".join(text.split()), DATE_FORMAT)
    except ValueError:
        return None
    return value


def parse_datetime(text: str) -> Optional[_dt.datetime]:
    cleaned = " ".join(text.split())
    for fmt in DATETIME_FORMATS:
        try:
            return _dt.datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


class _TextInput(QWidget):
    """Общая база: QLineEdit + подсветка неверного ввода."""

    valueChanged = Signal()

    def __init__(self, placeholder: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textEdited.connect(self._on_edited)
        layout.addWidget(self.edit)
        self.setFocusProxy(self.edit)

    def _on_edited(self, _text: str) -> None:
        self._apply_validity()
        self.valueChanged.emit()

    def _apply_validity(self) -> None:
        self.edit.setProperty("invalid", "false" if self._parse() is not None else "true")
        style = self.edit.style()
        style.unpolish(self.edit)
        style.polish(self.edit)

    def _parse(self) -> Optional[_dt.datetime]:
        raise NotImplementedError

    def is_valid(self) -> bool:
        return self._parse() is not None

    def text(self) -> str:
        return self.edit.text().strip()

    def clear(self) -> None:
        self.edit.clear()


class DateTimeInput(_TextInput):
    """Поле «дд.мм.гггг чч:мм» с привязкой к дате отсчёта проекта."""

    def __init__(self, epoch: _dt.datetime, parent=None) -> None:
        self.epoch = epoch
        super().__init__("дд.мм.гггг чч:мм", parent)

    def set_seconds(self, seconds: float) -> None:
        self.edit.setText(format_datetime(time_utils.seconds_to_datetime(seconds, self.epoch)))
        self._apply_validity()

    def seconds(self) -> Optional[float]:
        parsed = self._parse()
        if parsed is None:
            return None
        return time_utils.datetime_to_seconds(parsed, self.epoch)

    def _parse(self) -> Optional[_dt.datetime]:
        return parse_datetime(self.edit.text())


class DateInput(_TextInput):
    """Поле «дд.мм.гггг» без времени."""

    def __init__(self, parent=None) -> None:
        super().__init__("дд.мм.гггг", parent)

    def set_date(self, value: _dt.datetime) -> None:
        self.edit.setText(format_date(value))
        self._apply_validity()

    def date(self) -> Optional[_dt.datetime]:
        return self._parse()

    def _parse(self) -> Optional[_dt.datetime]:
        return parse_date(self.edit.text())
