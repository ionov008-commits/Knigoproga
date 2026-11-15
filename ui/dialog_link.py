"""Диалог настройки типа и текста связи между событиями."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from database import queries


class LinkEditDialog(QDialog):
    """Редактирование существующей связи: тип, описание, удаление.

    После ``exec()``:
      * ``link_type`` / ``description`` — актуальные значения;
      * ``deleted`` — True, если пользователь нажал «Удалить связь»;
      * ``changed`` — True, если данные были сохранены.
    """

    def __init__(self, db, link_id: int, source_title: str, target_title: str, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.link_id = int(link_id)
        self.deleted = False
        self.changed = False

        record = queries.get_link(db, self.link_id)
        if record is None:
            raise ValueError(f"Связь id={self.link_id} не найдена")

        self.link_type: str = record.get("link_type") or "sequence"
        self.description: str = record.get("description") or ""

        self.setWindowTitle("Редактирование связи")
        self.setModal(True)
        self.resize(460, 380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QLabel(f"<b>{source_title}</b>  →  <b>{target_title}</b>")
        header.setWordWrap(True)
        header.setTextFormat(Qt.RichText)
        layout.addWidget(header)

        layout.addWidget(QLabel("Тип связи:"))
        self.type_combo = QComboBox()
        for value, label in queries.LINK_TYPES:
            self.type_combo.addItem(label, value)
        index = self.type_combo.findData(self.link_type)
        self.type_combo.setCurrentIndex(index if index >= 0 else 0)
        layout.addWidget(self.type_combo)

        self.style_hint = QLabel()
        self.style_hint.setObjectName("HintLabel")
        layout.addWidget(self.style_hint)

        layout.addWidget(QLabel("Подробное описание связи:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText(
            "Например: смерть наставника подталкивает героя к решению вступить в конфликт..."
        )
        self.desc_edit.setPlainText(self.description)
        layout.addWidget(self.desc_edit, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        delete_btn = QPushButton("Удалить связь")
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

        self.type_combo.currentIndexChanged.connect(self._refresh_hint)
        self._refresh_hint()

    # ------------------------------------------------------------------ ui ---
    def _refresh_hint(self) -> None:
        if self.type_combo.currentData() == "influence":
            self.style_hint.setText("Косвенное влияние — фиолетовая штрих-пунктирная линия.")
        else:
            self.style_hint.setText("Прямая последовательность — сплошная светло-серая линия.")

    # -------------------------------------------------------------- actions ---
    def _on_save(self) -> None:
        new_type = self.type_combo.currentData() or "sequence"
        new_desc = self.desc_edit.toPlainText().strip()
        try:
            queries.update_link(self.db, self.link_id, new_type, new_desc)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось обновить связь:\n{exc}")
            return
        self.link_type = new_type
        self.description = new_desc
        self.changed = True
        self.accept()

    def _on_delete(self) -> None:
        answer = QMessageBox.question(
            self,
            "Удаление связи",
            "Удалить эту связь между событиями?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            queries.delete_link(self.db, self.link_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка удаления", f"Не удалось удалить связь:\n{exc}")
            return
        self.deleted = True
        self.accept()