"""Окно управления персонажами: анкета по шаблону и цепочка событий."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from database import queries
from ui.dialog_templates import TemplateManagerDialog


class CharacterWindow(QDialog):
    """Левая панель — список персонажей, правая — анкета и таймлайн."""

    def __init__(self, db, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.current_character_id: Optional[int] = None
        self._loading = False
        self.field_widgets: dict[str, QWidget] = {}
        self.current_fields: list[dict] = []
        self.custom_values: dict[str, str] = {}
        self.templates: list[dict] = []
        self.active_template: Optional[dict] = None
        self.timeline_notes: dict[int, str] = {}
        self._profile_snapshot: dict[str, str] = {}

        self.setWindowTitle("Персонажи && Анкеты")
        self.setModal(True)
        self.resize(1040, 760)
        self.setMinimumSize(860, 560)

        self._build_ui()
        self.refresh_templates()
        self.refresh_character_list()

    # ------------------------------------------------------------------ ui ---
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # ------------------------------------------------ левая панель ----
        left = QWidget()
        left.setObjectName("PanelBox")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)

        left_title = QLabel("Персонажи проекта")
        left_title.setStyleSheet("font-weight: 600; color: #7d5fff;")
        left_layout.addWidget(left_title)

        self.character_list = QListWidget()
        self.character_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.character_list.currentItemChanged.connect(self._on_character_changed)
        left_layout.addWidget(self.character_list, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)

        add_btn = QPushButton("+ Добавить персонажа")
        add_btn.clicked.connect(self.add_character)
        buttons.addWidget(add_btn)

        del_btn = QPushButton("Удалить")
        del_btn.setObjectName("dangerButton")
        del_btn.clicked.connect(self.delete_character)
        buttons.addWidget(del_btn)

        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        # ----------------------------------------------- правая панель ----
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_profile_tab(), "Анкета персонажа")
        self.tabs.addTab(self._build_timeline_tab(), "Цепочка событий (Timeline)")
        splitter.addWidget(self.tabs)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 760])

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    def _build_profile_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        template_row = QHBoxLayout()
        template_row.setSpacing(8)
        template_row.addWidget(QLabel("Шаблон анкеты:"))
        self.template_combo = QComboBox()
        self.template_combo.setMinimumWidth(240)
        self.template_combo.currentIndexChanged.connect(self._on_template_changed)
        template_row.addWidget(self.template_combo, 1)
        manage_btn = QPushButton("Шаблоны…")
        manage_btn.setToolTip("Добавлять и убирать графы, сохранять пресеты анкет")
        manage_btn.clicked.connect(self.manage_templates)
        template_row.addWidget(manage_btn)
        layout.addLayout(template_row)

        self.profile_scroll = QScrollArea()
        self.profile_scroll.setWidgetResizable(True)
        self.profile_scroll.setFrameShape(QScrollArea.NoFrame)
        layout.addWidget(self.profile_scroll, 1)

        return widget

    def _build_timeline_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        caption = QLabel("Все события проекта, где персонаж участвует (по порядку):")
        caption.setObjectName("HintLabel")
        layout.addWidget(caption)

        self.timeline_list = QListWidget()
        self.timeline_list.currentRowChanged.connect(self._on_timeline_selected)
        layout.addWidget(self.timeline_list, 1)

        note_caption = QLabel("Как персонаж изменился в выбранном событии:")
        note_caption.setObjectName("HintLabel")
        layout.addWidget(note_caption)

        self.timeline_note = QTextEdit()
        self.timeline_note.setReadOnly(True)
        self.timeline_note.setMinimumHeight(140)
        self.timeline_note.setPlaceholderText("Выберите событие в списке выше.")
        layout.addWidget(self.timeline_note, 1)

        return widget

    # -------------------------------------------------------------- шаблоны ---
    def refresh_templates(self) -> None:
        self.templates = queries.list_templates(self.db)
        active = queries.get_active_template(self.db)
        self.active_template = active

        self._loading = True
        self.template_combo.clear()
        for template in self.templates:
            self.template_combo.addItem(template["name"], template["id"])
        if active is not None:
            target = int(active["id"])
            for index in range(self.template_combo.count()):
                if int(self.template_combo.itemData(index)) == target:
                    self.template_combo.setCurrentIndex(index)
                    break
        self._loading = False
        self.rebuild_form()

    def _on_template_changed(self, index: int) -> None:
        if self._loading or index < 0:
            return
        template_id = self.template_combo.itemData(index)
        if template_id is None:
            return
        if not self._ask_save_profile():
            self._restore_template_combo()
            return
        try:
            queries.set_active_template(self.db, int(template_id))
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка", f"Не удалось применить шаблон:\n{exc}")
            return
        self.active_template = next(
            (item for item in self.templates if int(item["id"]) == int(template_id)),
            None,
        )
        self.rebuild_form()
        if self.current_character_id is not None:
            self.load_profile(self.current_character_id)
        self.profile_status.setText("Шаблон применён.")

    def manage_templates(self) -> None:
        dialog = TemplateManagerDialog(self.db, self)
        dialog.exec()
        self.refresh_templates()
        if self.current_character_id is not None:
            self.load_profile(self.current_character_id)

    # -------------------------------------------------------------- форма ---
    def rebuild_form(self) -> None:
        """Пересобирает анкету под активный шаблон."""
        old = self.profile_scroll.takeWidget()
        if old is not None:
            old.deleteLater()

        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.field_widgets = {}
        self.current_fields = list(self.active_template["fields"]) if self.active_template else []

        for field in self.current_fields:
            key = str(field["key"])
            caption = QLabel(f"{field.get('label', key)}:")
            caption.setWordWrap(True)
            if field.get("multiline"):
                editor = QPlainTextEdit()
                editor.setFixedHeight(64)
                editor.setTabChangesFocus(True)
                widget: QWidget = editor
            else:
                widget = QLineEdit()
            widget.setEnabled(False)
            self.field_widgets[key] = widget
            form.addRow(caption, widget)

        save_row = QHBoxLayout()
        self.profile_status = QLabel("")
        self.profile_status.setObjectName("HintLabel")
        save_row.addWidget(self.profile_status, 1)

        save_btn = QPushButton("Сохранить анкету")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self.save_profile)
        save_row.addWidget(save_btn)

        save_holder = QWidget()
        save_holder.setLayout(save_row)
        form.addRow(save_holder)

        self.profile_scroll.setWidget(content)
        self._profile_snapshot = {}

    # --------------------------------------------------------------- list ---
    def refresh_character_list(self, select_id: Optional[int] = None) -> None:
        target = select_id if select_id is not None else self.current_character_id
        self._loading = True
        self.character_list.clear()
        characters = queries.get_characters(self.db)
        for character in characters:
            item = QListWidgetItem(str(character["name"]))
            item.setData(Qt.UserRole, int(character["id"]))
            self.character_list.addItem(item)
        self._loading = False

        if not characters:
            self.current_character_id = None
            self._clear_profile()
            self._clear_timeline("Персонажей пока нет.")
            return

        row = 0
        if target is not None:
            for index in range(self.character_list.count()):
                if self.character_list.item(index).data(Qt.UserRole) == target:
                    row = index
                    break
        self.character_list.setCurrentRow(row)

    def _on_character_changed(self, current: Optional[QListWidgetItem], previous=None) -> None:
        if self._loading or current is None:
            return
        character_id = current.data(Qt.UserRole)
        if character_id == self.current_character_id:
            return
        if not self._ask_save_profile():
            self._loading = True
            if previous is not None:
                self.character_list.setCurrentItem(previous)
            self._loading = False
            return
        self.current_character_id = int(character_id)
        self.load_profile(self.current_character_id)
        self.load_timeline(self.current_character_id)

    # ------------------------------------------------ несохранённые правки ---
    def _current_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for field in self.current_fields:
            key = str(field["key"])
            widget = self.field_widgets.get(key)
            if widget is not None:
                values[key] = self._widget_value(widget)
        return values

    def _profile_dirty(self) -> bool:
        if self.current_character_id is None:
            return False
        return self._current_values() != self._profile_snapshot

    def _ask_save_profile(self) -> bool:
        """True — можно продолжать; False — пользователь отменил действие."""
        if not self._profile_dirty():
            return True
        answer = QMessageBox.question(
            self,
            "Несохранённые изменения",
            "В анкете есть несохранённые изменения. Сохранить их?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self.save_profile()
        return True

    def _restore_template_combo(self) -> None:
        if self.active_template is None:
            return
        target = int(self.active_template["id"])
        self._loading = True
        for index in range(self.template_combo.count()):
            if int(self.template_combo.itemData(index)) == target:
                self.template_combo.setCurrentIndex(index)
                break
        self._loading = False

    # ------------------------------------------------------------- profile ---
    @staticmethod
    def _set_widget_value(widget: QWidget, value: str) -> None:
        if isinstance(widget, QLineEdit):
            widget.setText(value)
        elif isinstance(widget, QPlainTextEdit):
            widget.setPlainText(value)

    @staticmethod
    def _widget_value(widget: QWidget) -> str:
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText().strip()
        return ""

    def _clear_profile(self) -> None:
        self._loading = True
        for widget in self.field_widgets.values():
            self._set_widget_value(widget, "")
            widget.setEnabled(False)
        self.profile_status.setText("")
        self._profile_snapshot = {}
        self._loading = False

    def load_profile(self, character_id: int) -> None:
        data = queries.get_character(self.db, character_id)
        if not data:
            return
        self.custom_values = queries.get_custom_values(self.db, character_id)

        self._loading = True
        for field in self.current_fields:
            key = str(field["key"])
            widget = self.field_widgets.get(key)
            if widget is None:
                continue
            widget.setEnabled(True)
            if key in queries.CHARACTER_FIELD_KEYS:
                value = data.get(key) or ""
            else:
                value = self.custom_values.get(key, "")
            self._set_widget_value(widget, str(value))
        self._profile_snapshot = self._current_values()
        self.profile_status.setText("")
        self._loading = False

    def save_profile(self) -> bool:
        if self.current_character_id is None:
            QMessageBox.information(self, "Нет персонажа", "Сначала добавьте персонажа.")
            return False

        builtin: dict[str, str] = {}
        custom: dict[str, str] = {}
        for field in self.current_fields:
            key = str(field["key"])
            widget = self.field_widgets.get(key)
            if widget is None:
                continue
            value = self._widget_value(widget)
            if key in queries.CHARACTER_FIELD_KEYS:
                builtin[key] = value
            else:
                custom[key] = value

        if "name" in builtin and not builtin["name"]:
            QMessageBox.warning(self, "Имя обязательно", "Введите имя персонажа.")
            return False

        try:
            if builtin:
                queries.update_character(self.db, self.current_character_id, builtin)
            queries.set_custom_values(self.db, self.current_character_id, custom)
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить анкету:\n{exc}")
            return False

        if builtin.get("name"):
            self._refresh_current_item_text(builtin["name"])
        self._profile_snapshot = self._current_values()
        self.profile_status.setText("Анкета сохранена.")
        return True

    def _refresh_current_item_text(self, name: str) -> None:
        item = self.character_list.currentItem()
        if item is not None:
            self._loading = True
            item.setText(name)
            self._loading = False

    def accept(self) -> None:
        if not self._ask_save_profile():
            return
        super().accept()

    def reject(self) -> None:
        if not self._ask_save_profile():
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if not self._ask_save_profile():
            event.ignore()
            return
        super().closeEvent(event)

    # ------------------------------------------------------------ timeline ---
    def _clear_timeline(self, message: str = "") -> None:
        self.timeline_list.clear()
        self.timeline_notes.clear()
        self.timeline_note.setPlainText(message)

    def load_timeline(self, character_id: int) -> None:
        self.timeline_list.clear()
        self.timeline_notes.clear()
        self.timeline_note.clear()

        timeline = queries.get_character_timeline(self.db, character_id)
        if not timeline:
            self.timeline_note.setPlainText(
                "Персонаж пока не отмечен ни в одном событии.\n"
                "Отметьте его участие в окне события."
            )
            return

        for entry in timeline:
            event_id = int(entry["event_id"])
            item = QListWidgetItem(f"#{event_id} — {entry['title']}")
            item.setData(Qt.UserRole, event_id)
            self.timeline_list.addItem(item)
            self.timeline_notes[event_id] = entry.get("impact_note") or ""

        self.timeline_list.setCurrentRow(0)

    def _on_timeline_selected(self, row: int) -> None:
        item = self.timeline_list.item(row)
        if item is None:
            self.timeline_note.clear()
            return
        event_id = int(item.data(Qt.UserRole))
        note = self.timeline_notes.get(event_id, "").strip()
        self.timeline_note.setPlainText(note or "Заметка об изменениях не заполнена.")

    # ------------------------------------------------------------- actions ---
    def add_character(self) -> None:
        try:
            new_id = queries.create_character(self.db, "Новый персонаж")
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать персонажа:\n{exc}")
            return
        if new_id is None:
            return
        self.current_character_id = None
        self.refresh_character_list(select_id=int(new_id))
        name_widget = self.field_widgets.get("name")
        if isinstance(name_widget, QLineEdit):
            name_widget.setFocus()
            name_widget.selectAll()

    def delete_character(self) -> None:
        if self.current_character_id is None:
            return
        item = self.character_list.currentItem()
        name = item.text() if item is not None else "персонажа"
        answer = QMessageBox.question(
            self,
            "Удаление персонажа",
            f"Удалить персонажа «{name}»?\nВсе заметки о его изменениях в событиях будут удалены.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            queries.delete_character(self.db, self.current_character_id)
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка удаления", f"Не удалось удалить персонажа:\n{exc}")
            return

        self.current_character_id = None
        self.refresh_character_list()
