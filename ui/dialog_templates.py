"""Управление шаблонами анкет персонажей (пресетами граф)."""

from __future__ import annotations

import uuid
from typing import Iterable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from database import queries


class FieldEditorDialog(QDialog):
    """Редактор одной графы анкеты."""

    def __init__(
        self,
        field: Optional[dict] = None,
        used_keys: Iterable[str] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.original = dict(field) if field else None
        self.used_keys = set(used_keys)
        self.result_field: Optional[dict] = None

        self.setWindowTitle("Изменить графу" if field else "Новая графа")
        self.setModal(True)
        self.resize(420, 240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.source_combo: Optional[QComboBox] = None
        if field is None:
            layout.addWidget(QLabel("Основа графы:"))
            self.source_combo = QComboBox()
            self.source_combo.addItem("Произвольное поле", None)
            for key, label in queries.CHARACTER_FIELDS:
                if key in self.used_keys:
                    continue
                self.source_combo.addItem(f"Стандартное: {label}", key)
            self.source_combo.currentIndexChanged.connect(self._on_source_changed)
            layout.addWidget(self.source_combo)

        layout.addWidget(QLabel("Название графы:"))
        self.label_edit = QLineEdit(field["label"] if field else "")
        self.label_edit.setPlaceholderText("Например: Тайная цель, Отношение к магии")
        layout.addWidget(self.label_edit)

        self.multiline_check = QCheckBox("Многострочное поле (для длинных описаний)")
        self.multiline_check.setChecked(bool(field.get("multiline")) if field else True)
        layout.addWidget(self.multiline_check)

        self.key_label = QLabel("")
        self.key_label.setObjectName("HintLabel")
        if field is not None:
            self.key_label.setText(
                f"Ключ: {field['key']}" + ("  ·  стандартное поле" if field.get("builtin") else "")
            )
        layout.addWidget(self.key_label)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        ok_btn = QPushButton("Готово")
        ok_btn.setObjectName("primaryButton")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_accept)
        buttons.addWidget(ok_btn)
        layout.addLayout(buttons)

        self._builtin_key: Optional[str] = None

    def _on_source_changed(self, index: int) -> None:
        if self.source_combo is None:
            return
        key = self.source_combo.itemData(index)
        self._builtin_key = key
        if key:
            label = dict(queries.CHARACTER_FIELDS).get(key, key)
            self.label_edit.setText(label)
            self.multiline_check.setChecked(key not in queries.SINGLE_LINE_BUILTIN)
        self.key_label.setText(f"Ключ: {key}" if key else "")

    def _on_accept(self) -> None:
        label = self.label_edit.text().strip()
        if not label:
            QMessageBox.warning(self, "Название обязательно", "Введите название графы.")
            self.label_edit.setFocus()
            return

        multiline = self.multiline_check.isChecked()
        if self.original is not None:
            result = dict(self.original)
            result["label"] = label
            result["multiline"] = multiline
            if result["key"] == "name":
                result["multiline"] = False
                result["builtin"] = True
        else:
            if self._builtin_key:
                key = self._builtin_key
                builtin = True
            else:
                key = f"custom_{uuid.uuid4().hex[:10]}"
                builtin = False
            if key == "name":
                multiline = False
            result = {
                "key": key,
                "label": label,
                "multiline": multiline,
                "builtin": builtin,
            }
        self.result_field = result
        self.accept()


class TemplateManagerDialog(QDialog):
    """Список шаблонов анкеты и редактор граф выбранного шаблона."""

    def __init__(self, db, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.templates: list[dict] = []
        self.current_id: Optional[int] = None
        self.fields: list[dict] = []
        self.dirty = False
        self._loading = False

        self.setWindowTitle("Шаблоны анкет")
        self.setModal(True)
        self.resize(880, 620)
        self.setMinimumSize(720, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # ------------------------------------------------------ шаблоны ----
        left = QWidget()
        left.setObjectName("PanelBox")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)

        left_title = QLabel("Пресеты анкет")
        left_title.setStyleSheet("font-weight: 600; color: #7d5fff;")
        left_layout.addWidget(left_title)

        self.template_list = QListWidget()
        self.template_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.template_list.currentRowChanged.connect(self._on_template_selected)
        left_layout.addWidget(self.template_list, 1)

        left_buttons = QHBoxLayout()
        left_buttons.setSpacing(6)
        new_btn = QPushButton("+ Новый")
        new_btn.clicked.connect(self._new_template)
        left_buttons.addWidget(new_btn)
        duplicate_btn = QPushButton("Дублировать")
        duplicate_btn.clicked.connect(self._duplicate_template)
        left_buttons.addWidget(duplicate_btn)
        delete_btn = QPushButton("Удалить")
        delete_btn.setObjectName("dangerButton")
        delete_btn.clicked.connect(self._delete_template)
        left_buttons.addWidget(delete_btn)
        left_layout.addLayout(left_buttons)
        splitter.addWidget(left)

        # -------------------------------------------------------- графы ----
        right = QWidget()
        right.setObjectName("PanelBox")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(8)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Название шаблона:"))
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._mark_dirty)
        name_row.addWidget(self.name_edit, 1)
        right_layout.addLayout(name_row)

        right_layout.addWidget(QLabel("Графы анкеты (порядок сверху вниз):"))
        self.fields_list = QListWidget()
        self.fields_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.fields_list.currentRowChanged.connect(self._update_field_buttons)
        right_layout.addWidget(self.fields_list, 1)

        field_buttons = QHBoxLayout()
        field_buttons.setSpacing(6)
        add_field_btn = QPushButton("+ Добавить графу")
        add_field_btn.clicked.connect(self._add_field)
        field_buttons.addWidget(add_field_btn)
        self.edit_field_btn = QPushButton("Изменить")
        self.edit_field_btn.clicked.connect(self._edit_field)
        field_buttons.addWidget(self.edit_field_btn)
        self.remove_field_btn = QPushButton("Удалить графу")
        self.remove_field_btn.setObjectName("dangerButton")
        self.remove_field_btn.clicked.connect(self._remove_field)
        field_buttons.addWidget(self.remove_field_btn)
        field_buttons.addStretch(1)
        self.up_field_btn = QPushButton("↑")
        self.up_field_btn.setFixedWidth(38)
        self.up_field_btn.clicked.connect(lambda: self._move_field(-1))
        field_buttons.addWidget(self.up_field_btn)
        self.down_field_btn = QPushButton("↓")
        self.down_field_btn.setFixedWidth(38)
        self.down_field_btn.clicked.connect(lambda: self._move_field(1))
        field_buttons.addWidget(self.down_field_btn)
        right_layout.addLayout(field_buttons)

        self.status_label = QLabel("")
        self.status_label.setObjectName("HintLabel")
        right_layout.addWidget(self.status_label)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 600])

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        self.save_btn = QPushButton("Сохранить шаблон")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.clicked.connect(self._save_current)
        bottom.addWidget(self.save_btn)
        root.addLayout(bottom)

        self._load_templates(select_first=True)
        self._update_field_buttons()

    # ---------------------------------------------------------- список ---
    def _load_templates(self, select_id: Optional[int] = None, select_first: bool = False) -> None:
        self.templates = queries.list_templates(self.db)
        self._loading = True
        self.template_list.clear()
        for template in self.templates:
            item = QListWidgetItem(template["name"])
            item.setData(Qt.UserRole, template["id"])
            suffix = "  · стандартный" if template["builtin"] else ""
            item.setToolTip(f"{template['name']}{suffix}")
            self.template_list.addItem(item)

        target_id = select_id
        if target_id is None and self.current_id is not None:
            target_id = self.current_id
        if target_id is None and select_first and self.templates:
            target_id = self.templates[0]["id"]

        row = -1
        if target_id is not None:
            for index in range(self.template_list.count()):
                if self.template_list.item(index).data(Qt.UserRole) == target_id:
                    row = index
                    break
        if row < 0 and self.template_list.count():
            row = 0

        if row >= 0:
            self.template_list.setCurrentRow(row)
        self._loading = False
        if row >= 0:
            self._load_into_editor(self.templates[row])

    def _on_template_selected(self, row: int) -> None:
        if self._loading or row < 0 or row >= len(self.templates):
            return
        template = self.templates[row]
        template_id = int(template["id"])
        if template_id == self.current_id:
            return
        if not self._maybe_save():
            self._restore_selection()
            return
        # Список мог пересортироваться после сохранения — берём шаблон заново.
        fresh = queries.get_template(self.db, template_id)
        if fresh is None:
            self._load_templates(select_first=True)
            return
        self._select_template_row(template_id)
        self._load_into_editor(fresh)

    def _select_template_row(self, template_id: int) -> None:
        self._loading = True
        for index in range(self.template_list.count()):
            if self.template_list.item(index).data(Qt.UserRole) == template_id:
                self.template_list.setCurrentRow(index)
                break
        self._loading = False

    def _restore_selection(self) -> None:
        if self.current_id is None:
            return
        self._select_template_row(self.current_id)

    def _load_into_editor(self, template: dict) -> None:
        self.current_id = int(template["id"])
        self.name_edit.setText(template["name"])
        self.fields = [dict(field) for field in template["fields"]]
        self.dirty = False
        self._refresh_fields_list()
        self.status_label.setText("")
        self._update_field_buttons()

    def _refresh_fields_list(self, select_row: int = 0) -> None:
        self.fields_list.clear()
        for field in self.fields:
            suffix = "" if field.get("builtin") else "  · своя"
            item = QListWidgetItem(f"{field['label']}{suffix}")
            item.setToolTip(f"Ключ: {field['key']}")
            self.fields_list.addItem(item)
        if self.fields:
            row = min(max(select_row, 0), len(self.fields) - 1)
            self.fields_list.setCurrentRow(row)
        self._update_field_buttons()

    def _update_field_buttons(self) -> None:
        field = self._selected_field()
        self.edit_field_btn.setEnabled(field is not None)
        self.up_field_btn.setEnabled(field is not None)
        self.down_field_btn.setEnabled(field is not None)
        self.remove_field_btn.setEnabled(field is not None and field["key"] != "name")

    def _selected_field(self) -> Optional[dict]:
        row = self.fields_list.currentRow()
        if 0 <= row < len(self.fields):
            return self.fields[row]
        return None

    # ---------------------------------------------------------- правки ---
    def _mark_dirty(self) -> None:
        if self._loading:
            return
        self.dirty = True
        self.status_label.setText("Есть несохранённые изменения.")

    def _add_field(self) -> None:
        used = {field["key"] for field in self.fields}
        dialog = FieldEditorDialog(None, used_keys=used, parent=self)
        if dialog.exec() != QDialog.Accepted or dialog.result_field is None:
            return
        self.fields.append(dialog.result_field)
        self._refresh_fields_list(len(self.fields) - 1)
        self._mark_dirty()

    def _edit_field(self) -> None:
        field = self._selected_field()
        if field is None:
            return
        used = {item["key"] for item in self.fields if item["key"] != field["key"]}
        dialog = FieldEditorDialog(field, used_keys=used, parent=self)
        if dialog.exec() != QDialog.Accepted or dialog.result_field is None:
            return
        row = self.fields_list.currentRow()
        self.fields[row] = dialog.result_field
        self._refresh_fields_list(row)
        self._mark_dirty()

    def _remove_field(self) -> None:
        field = self._selected_field()
        if field is None:
            return
        if field["key"] == "name":
            QMessageBox.information(
                self,
                "Имя обязательно",
                "Графу «Имя» нельзя удалить: она нужна для списка персонажей.",
            )
            return
        row = self.fields_list.currentRow()
        del self.fields[row]
        if not self.fields:
            self.fields = [
                {"key": "name", "label": "Имя", "multiline": False, "builtin": True}
            ]
        self._refresh_fields_list(row)
        self._mark_dirty()

    def _move_field(self, direction: int) -> None:
        row = self.fields_list.currentRow()
        target = row + direction
        if row < 0 or not (0 <= target < len(self.fields)):
            return
        self.fields[row], self.fields[target] = self.fields[target], self.fields[row]
        self._refresh_fields_list(target)
        self._mark_dirty()

    # ---------------------------------------------------------- шаблоны ---
    def _unique_name(self, base: str) -> str:
        existing = {template["name"] for template in queries.list_templates(self.db)}
        name = base
        index = 2
        while name in existing:
            name = f"{base} {index}"
            index += 1
        return name

    def _new_template(self) -> None:
        if not self._maybe_save():
            return
        name = self._unique_name("Новый шаблон")
        fields = [
            {"key": "name", "label": "Имя", "multiline": False, "builtin": True},
            {"key": "age", "label": "Возраст", "multiline": False, "builtin": True},
        ]
        try:
            new_id = queries.save_template(self.db, name, fields)
            self.db.save()
        except ValueError as exc:
            QMessageBox.warning(self, "Не удалось создать шаблон", str(exc))
            return
        self._load_templates(select_id=new_id)

    def _duplicate_template(self) -> None:
        if self.current_id is None:
            return
        if not self._maybe_save():
            return
        try:
            new_id = queries.duplicate_template(self.db, self.current_id)
            self.db.save()
        except ValueError as exc:
            QMessageBox.warning(self, "Не удалось дублировать", str(exc))
            return
        self._load_templates(select_id=new_id)

    def _delete_template(self) -> None:
        if self.current_id is None:
            return
        row = self.template_list.currentRow()
        name = self.template_list.item(row).text() if row >= 0 else "шаблон"
        answer = QMessageBox.question(
            self,
            "Удаление шаблона",
            f"Удалить шаблон «{name}»?\nДанные персонажей при этом не удаляются.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            queries.delete_template(self.db, self.current_id)
            self.db.save()
        except ValueError as exc:
            QMessageBox.warning(self, "Нельзя удалить", str(exc))
            return
        self.current_id = None
        self.dirty = False
        self._load_templates(select_first=True)

    def _save_current(self) -> bool:
        if self.current_id is None:
            return False
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Название обязательно", "Введите название шаблона.")
            self.name_edit.setFocus()
            return False
        try:
            new_id = queries.save_template(self.db, name, self.fields, self.current_id)
            self.db.save()
        except ValueError as exc:
            QMessageBox.warning(self, "Не удалось сохранить шаблон", str(exc))
            return False
        self.current_id = new_id
        self.dirty = False
        self._load_templates(select_id=new_id)
        self.status_label.setText("Шаблон сохранён.")
        return True

    def _maybe_save(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Несохранённые изменения",
            "Сохранить изменения текущего шаблона?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self._save_current()
        self.dirty = False
        return True

    def accept(self) -> None:
        if not self._maybe_save():
            return
        super().accept()
