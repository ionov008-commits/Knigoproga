"""Диалоговое окно создания и редактирования события."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QPointF
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from database import queries
from ui import time_utils
from ui.qt_time import DateTimeInput


class _CharacterImpactRow(QWidget):
    """Строка персонажа: чекбокс участия + раскрывающееся поле заметки."""

    def __init__(self, character_id: int, name: str, checked: bool, note: str, parent=None) -> None:
        super().__init__(parent)
        self.character_id = int(character_id)
        self.name = name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)

        self.checkbox = QCheckBox(name)
        self.checkbox.setChecked(checked)
        layout.addWidget(self.checkbox)

        self.note_container = QWidget()
        note_layout = QVBoxLayout(self.note_container)
        note_layout.setContentsMargins(24, 2, 0, 6)
        note_layout.setSpacing(3)

        caption = QLabel("Как персонаж изменился в ходе этого события:")
        caption.setObjectName("HintLabel")
        note_layout.addWidget(caption)

        self.note_edit = QTextEdit()
        self.note_edit.setPlaceholderText(
            f"Что произошло с персонажем «{name}» и как он изменился..."
        )
        self.note_edit.setFixedHeight(70)
        self.note_edit.setPlainText(note or "")
        note_layout.addWidget(self.note_edit)

        self.note_container.setVisible(checked)
        layout.addWidget(self.note_container)

        self.checkbox.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self.note_container.setVisible(checked)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def note(self) -> str:
        return self.note_edit.toPlainText().strip()


class EventDetailsDialog(QDialog):
    """Создание/редактирование события и заметок изменений персонажей.

    Атрибуты после ``exec()``:
      * ``event_id`` — id сохранённого события (None, если не сохранено);
      * ``deleted`` — True, если событие было удалено;
      * ``saved`` — True, если данные записаны в БД.
    """

    def __init__(
        self,
        db,
        event_id: Optional[int] = None,
        scene_position: Optional[QPointF] = None,
        default_title: str = "",
        time_range: Optional[tuple[float, float]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.event_id = int(event_id) if event_id else None
        self.scene_position = scene_position or QPointF(0.0, 0.0)
        self.time_range = time_range
        self.deleted = False
        self.saved = False
        self.rows: list[_CharacterImpactRow] = []
        self._epoch = time_utils.parse_epoch(queries.get_timeline_epoch(db))

        self._existing: dict = {}
        if self.event_id:
            found = queries.get_event(db, self.event_id)
            if found:
                self._existing = found
            else:
                self.event_id = None

        self._build_ui(default_title)
        self._load_impacts()

    # ------------------------------------------------------------------ ui ---
    def _build_ui(self, default_title: str) -> None:
        is_edit = self.event_id is not None
        self.setWindowTitle("Редактирование события" if is_edit else "Новое событие")
        self.setModal(True)
        self.resize(620, 720)
        self.setMinimumSize(520, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_label = QLabel("Название события:")
        title_label.setMinimumWidth(140)
        self.title_input = QLineEdit(self._existing.get("title", default_title) or "")
        self.title_input.setPlaceholderText("Например: Предательство у Северных врат")
        self.title_input.textChanged.connect(self._refresh_buttons)
        title_row.addWidget(title_label)
        title_row.addWidget(self.title_input, 1)
        layout.addLayout(title_row)

        layout.addWidget(QLabel("Описание события / основной сюжет:"))
        self.desc_input = QTextEdit()
        self.desc_input.setPlaceholderText("Что происходит в этой сцене, кто участвует, чем она важна...")
        self.desc_input.setPlainText(self._existing.get("description", "") or "")
        self.desc_input.setMinimumHeight(120)
        layout.addWidget(self.desc_input, 1)

        layout.addWidget(self._build_time_box())

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("color: #3c3c3c;")
        layout.addWidget(separator)

        characters_header = QLabel("Персонажи в событии и их изменения")
        characters_header.setStyleSheet("font-weight: 600; color: #7d5fff;")
        layout.addWidget(characters_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        self.impacts_layout = QVBoxLayout(content)
        self.impacts_layout.setContentsMargins(4, 4, 4, 4)
        self.impacts_layout.setSpacing(6)

        characters = queries.get_characters(self.db)
        if not characters:
            hint = QLabel(
                "В проекте пока нет персонажей.\n"
                "Создайте их в окне «Персонажи & Анкеты», чтобы отмечать участие в событиях."
            )
            hint.setWordWrap(True)
            hint.setObjectName("HintLabel")
            self.impacts_layout.addWidget(hint)

        for character in characters:
            row = _CharacterImpactRow(int(character["id"]), str(character["name"]), False, "")
            self.rows.append(row)
            self.impacts_layout.addWidget(row)

        self.impacts_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        if is_edit:
            delete_btn = QPushButton("Удалить событие")
            delete_btn.setObjectName("dangerButton")
            delete_btn.clicked.connect(self._on_delete)
            buttons.addWidget(delete_btn)

        buttons.addStretch(1)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)

        self.save_btn = QPushButton("Сохранить событие")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._on_save)
        buttons.addWidget(self.save_btn)

        layout.addLayout(buttons)

        self._refresh_buttons()
        self.title_input.setFocus()

    # ----------------------------------------------------------- таймлайн ---
    def _build_time_box(self) -> QWidget:
        group = QGroupBox("Время на таймлайне")
        box = QVBoxLayout(group)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(6)

        self.time_check = QCheckBox("Показывать событие на таймлайне")
        box.addWidget(self.time_check)

        row = QHBoxLayout()
        row.addWidget(QLabel("Начало:"))
        self.start_edit = DateTimeInput(self._epoch)
        row.addWidget(self.start_edit, 1)
        row.addWidget(QLabel("Конец:"))
        self.end_edit = DateTimeInput(self._epoch)
        row.addWidget(self.end_edit, 1)
        box.addLayout(row)

        self.duration_label = QLabel("")
        self.duration_label.setObjectName("HintLabel")
        box.addWidget(self.duration_label)

        existing_start = self._existing.get("time_start")
        existing_end = self._existing.get("time_end")
        if existing_start is not None and existing_end is not None:
            start_value = float(existing_start)
            end_value = float(existing_end)
            checked = True
        elif self.time_range is not None:
            start_value = float(self.time_range[0])
            end_value = float(self.time_range[1])
            checked = True
        else:
            start_value = 0.0
            end_value = time_utils.HOUR
            # Новое событие по умолчанию сразу ставится на таймлайн.
            checked = self.event_id is None

        if end_value <= start_value:
            end_value = start_value + time_utils.HOUR

        self.start_edit.set_seconds(start_value)
        self.end_edit.set_seconds(end_value)
        self.time_check.setChecked(checked)

        self.time_check.toggled.connect(self._sync_time_editors)
        self.start_edit.valueChanged.connect(self._update_duration)
        self.end_edit.valueChanged.connect(self._update_duration)
        self._sync_time_editors(checked)
        return group

    def _sync_time_editors(self, checked: bool) -> None:
        self.start_edit.setEnabled(checked)
        self.end_edit.setEnabled(checked)
        self._update_duration()

    def _update_duration(self) -> None:
        if not hasattr(self, "duration_label"):
            return
        start = self.start_edit.seconds()
        end = self.end_edit.seconds()
        if start is None or end is None:
            self.duration_label.setText("Дата в формате дд.мм.гггг чч:мм")
        elif end <= start:
            self.duration_label.setText("Конец должен быть позже начала.")
        else:
            self.duration_label.setText(f"Длительность: {time_utils.format_duration(end - start)}")

    # ---------------------------------------------------------------- data ---
    def _load_impacts(self) -> None:
        if not self.event_id:
            return
        impacts = queries.get_event_impacts(self.db, self.event_id)
        for row in self.rows:
            note = impacts.get(row.character_id)
            if note is not None:
                row.checkbox.setChecked(True)
                row.note_edit.setPlainText(note)

    def _collect_impacts(self) -> dict[int, str]:
        impacts: dict[int, str] = {}
        for row in self.rows:
            if row.is_checked():
                impacts[row.character_id] = row.note()
        return impacts

    def _refresh_buttons(self) -> None:
        self.save_btn.setEnabled(bool(self.title_input.text().strip()))

    # ------------------------------------------------------------- actions ---
    def _on_save(self) -> None:
        title = self.title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "Название обязательно", "Введите название события.")
            self.title_input.setFocus()
            return

        description = self.desc_input.toPlainText().strip()

        timeline_enabled = self.time_check.isChecked()
        start_time = end_time = None
        if timeline_enabled:
            start_time = self.start_edit.seconds()
            end_time = self.end_edit.seconds()
            if start_time is None or end_time is None:
                QMessageBox.warning(
                    self,
                    "Неверная дата",
                    "Введите дату в формате дд.мм.гггг чч:мм.",
                )
                return
            if end_time <= start_time:
                QMessageBox.warning(
                    self,
                    "Неверное время",
                    "Конец события должен быть позже начала.",
                )
                return

        try:
            if self.event_id:
                queries.update_event(
                    self.db,
                    self.event_id,
                    title,
                    description,
                    self.scene_position.x(),
                    self.scene_position.y(),
                )
            else:
                new_id = queries.create_event(
                    self.db,
                    title,
                    description,
                    self.scene_position.x(),
                    self.scene_position.y(),
                )
                if new_id is None:
                    QMessageBox.critical(self, "Ошибка", "Не удалось создать событие в базе данных.")
                    return
                self.event_id = int(new_id)

            queries.set_event_impacts(self.db, self.event_id, self._collect_impacts())
            if timeline_enabled and start_time is not None and end_time is not None:
                queries.update_event_time(self.db, self.event_id, start_time, end_time)
            else:
                queries.clear_event_time(self.db, self.event_id)
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить событие:\n{exc}")
            return

        self.saved = True
        self.accept()

    def _on_delete(self) -> None:
        if not self.event_id:
            return
        answer = QMessageBox.question(
            self,
            "Удаление события",
            f"Удалить событие «{self._existing.get('title', '')}»?\n"
            "Вместе с ним исчезнут все его связи и заметки персонажей.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            queries.delete_event(self.db, self.event_id)
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка удаления", f"Не удалось удалить событие:\n{exc}")
            return
        self.deleted = True
        self.event_id = None
        self.accept()