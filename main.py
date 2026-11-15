"""Story Craft Canvas — главное окно приложения.

Запуск из корня проекта:
    python main.py
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, qInstallMessageHandler
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGraphicsScene,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from assets.theme import apply_theme
from database import DatabaseManager, queries
from ui.canvas_view import CanvasView
from ui.dialog_event import EventDetailsDialog
from ui.dialog_link import LinkEditDialog
from ui.dialog_period import PeriodDialog
from ui.event_node import EventNode
from ui.link_item import LinkItem
from ui.timeline_panel import TimelinePanel
from ui.window_characters import CharacterWindow

APP_NAME = "Story Craft Canvas"
APP_VERSION = "1.0.0"

PROJECT_FILTER = "Проект Story Craft (*.story *.db);;Story Project (*.story);;SQLite Database (*.db);;All Files (*)"

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LAST_PROJECT_FILE = os.path.join(
    os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "StoryCraftCanvas"),
    "last_project.txt",
)


class MainWindow(QMainWindow):
    def __init__(self, project_path: Optional[str] = None) -> None:
        super().__init__()
        self.db = DatabaseManager()
        self.node_items: dict[int, EventNode] = {}
        self.link_items: dict[int, LinkItem] = {}
        self.modified = False
        self.project_path: Optional[str] = None

        self.setWindowTitle(APP_NAME)
        self.resize(1360, 860)
        self.setMinimumSize(960, 600)

        self._build_scene()
        self._build_toolbar()
        self._build_menus()
        self._build_statusbar()

        explicit_project = bool(project_path)
        if not project_path:
            project_path = self._pick_initial_project()
        if project_path:
            self.load_project(project_path, show_errors=explicit_project)
        else:
            self._update_project_ui()

        self.center_on_content()

    # ======================================================================
    # Построение интерфейса
    # ======================================================================
    def _build_scene(self) -> None:
        self.scene = QGraphicsScene(self)
        self.scene.db = self.db  # доступ для нод (сохранение координат)
        self.view = CanvasView(self.scene, self)
        self.view.configure_scene()
        self.view.linkCompleted.connect(self.create_link)
        self.view.addEventRequested.connect(self.create_event_at)
        self.view.eventOpenRequested.connect(self.open_event)
        self.view.linkOpenRequested.connect(self.open_link)

        # Таймлайн — верхняя полоса рабочей области, холст — под ней.
        self.timeline = TimelinePanel(self.db, self)
        self.timeline.eventOpenRequested.connect(self.open_event)
        self.timeline.addEventRequested.connect(self.create_event_at_time)
        self.timeline.periodEditRequested.connect(self.edit_period)
        self.timeline.addPeriodRequested.connect(self.create_period)
        self.timeline.timesChanged.connect(self.mark_modified)

        # Холст и таймлайн — одно трансформируемое поле: зум и прокрутка общие.
        self.view.zoomChanged.connect(self._sync_timeline_zoom)
        self.view.panned.connect(self._sync_timeline_pan)
        self.timeline.zoomRequested.connect(self._zoom_from_timeline)
        self.timeline.panRequested.connect(self._pan_from_timeline)

        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.timeline)
        central_layout.addWidget(self.view, 1)
        self.setCentralWidget(central)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Основная панель", self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        brand = QLabel(APP_NAME)
        brand.setObjectName("AppTitleLabel")
        toolbar.addWidget(brand)
        toolbar.addSeparator()

        # Один QAction используется и в тулбаре, и в меню — иначе
        # одинаковые Ctrl+N/O/S регистрируются дважды и Qt ругается
        # на неоднозначную комбинацию.
        self.act_new = QAction("Новый проект...", self)
        self.act_new.setShortcut(QKeySequence.New)
        self.act_new.setShortcutContext(Qt.WindowShortcut)
        self.act_new.triggered.connect(self.new_project)

        self.act_open = QAction("Открыть проект...", self)
        self.act_open.setShortcut(QKeySequence.Open)
        self.act_open.setShortcutContext(Qt.WindowShortcut)
        self.act_open.triggered.connect(self.open_project)

        self.act_save = QAction("Сохранить проект", self)
        self.act_save.setShortcut(QKeySequence.Save)
        self.act_save.setShortcutContext(Qt.WindowShortcut)
        self.act_save.triggered.connect(self.save_project)

        toolbar.addAction(self.act_new)
        toolbar.addAction(self.act_open)
        toolbar.addAction(self.act_save)
        toolbar.addSeparator()

        self.btn_characters = QPushButton("Персонажи && Анкеты")
        self.btn_characters.setToolTip("Управление персонажами, анкетами и цепочками изменений")
        self.btn_characters.clicked.connect(self.open_characters_window)
        toolbar.addWidget(self.btn_characters)

        self.btn_add_event = QPushButton("+ Новое событие")
        self.btn_add_event.setToolTip("Создать событие в центре холста (или двойной клик по пустому месту)")
        self.btn_add_event.clicked.connect(self.create_event_center)
        toolbar.addWidget(self.btn_add_event)

        self.btn_add_period = QPushButton("+ Период")
        self.btn_add_period.setToolTip("Добавить цветную зону макропериода на таймлайн")
        self.btn_add_period.clicked.connect(self.create_period_at_center)
        toolbar.addWidget(self.btn_add_period)

        self.btn_link = QPushButton("Соединить ноды")
        self.btn_link.setCheckable(True)
        self.btn_link.setToolTip("Кликните первую ноду, затем вторую (Esc — отмена)")
        self.btn_link.toggled.connect(self.toggle_link_mode)
        toolbar.addWidget(self.btn_link)

        self.btn_timeline = QPushButton("Таймлайн")
        self.btn_timeline.setCheckable(True)
        self.btn_timeline.setChecked(True)
        self.btn_timeline.setToolTip("Показать/скрыть временную шкалу (Ctrl+T)")
        self.btn_timeline.toggled.connect(self.toggle_timeline)
        toolbar.addWidget(self.btn_timeline)

        toolbar.addSeparator()

        self.btn_zoom_in = QPushButton("＋")
        self.btn_zoom_in.setToolTip("Приблизить")
        self.btn_zoom_in.setFixedWidth(38)
        self.btn_zoom_in.clicked.connect(lambda: self.view.zoom_by(1.2))
        toolbar.addWidget(self.btn_zoom_in)

        self.btn_zoom_out = QPushButton("－")
        self.btn_zoom_out.setToolTip("Отдалить")
        self.btn_zoom_out.setFixedWidth(38)
        self.btn_zoom_out.clicked.connect(lambda: self.view.zoom_by(1 / 1.2))
        toolbar.addWidget(self.btn_zoom_out)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

    def _build_menus(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("Файл")
        file_menu.addAction(self.act_new)
        file_menu.addAction(self.act_open)
        file_menu.addAction(self.act_save)

        act_save_as = file_menu.addAction("Сохранить как...")
        act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_save_as.triggered.connect(self.save_project_as)

        file_menu.addSeparator()
        act_close = file_menu.addAction("Закрыть проект")
        act_close.triggered.connect(lambda: self.close_project(save_first=True))

        file_menu.addSeparator()
        act_quit = file_menu.addAction("Выход")
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)

        edit_menu = menubar.addMenu("Правка")
        act_add_event = edit_menu.addAction("Новое событие")
        act_add_event.setShortcut(QKeySequence("Ctrl+E"))
        act_add_event.triggered.connect(self.create_event_center)

        self.act_link = edit_menu.addAction("Соединить ноды")
        self.act_link.setCheckable(True)
        self.act_link.setShortcut(QKeySequence("Ctrl+L"))
        self.act_link.toggled.connect(self.toggle_link_mode)

        edit_menu.addSeparator()
        act_chars = edit_menu.addAction("Персонажи && Анкеты...")
        act_chars.setShortcut(QKeySequence("Ctrl+P"))
        act_chars.triggered.connect(self.open_characters_window)

        view_menu = menubar.addMenu("Вид")
        act_zin = view_menu.addAction("Приблизить")
        act_zin.setShortcut(QKeySequence.ZoomIn)
        act_zin.triggered.connect(lambda: self.view.zoom_by(1.2))

        act_zout = view_menu.addAction("Отдалить")
        act_zout.setShortcut(QKeySequence.ZoomOut)
        act_zout.triggered.connect(lambda: self.view.zoom_by(1 / 1.2))

        act_reset = view_menu.addAction("Сбросить масштаб (100%)")
        act_reset.setShortcut(QKeySequence("Ctrl+0"))
        act_reset.triggered.connect(self.reset_view)

        act_fit = view_menu.addAction("Показать все события")
        act_fit.setShortcut(QKeySequence("Ctrl+Shift+F"))
        act_fit.triggered.connect(self.fit_content)

        view_menu.addSeparator()
        self.act_timeline = view_menu.addAction("Показывать таймлайн")
        self.act_timeline.setCheckable(True)
        self.act_timeline.setChecked(True)
        self.act_timeline.setShortcut(QKeySequence("Ctrl+T"))
        self.act_timeline.toggled.connect(self.toggle_timeline)

        act_fit_timeline = view_menu.addAction("Вписать таймлайн")
        act_fit_timeline.setShortcut(QKeySequence("Ctrl+Alt+F"))
        act_fit_timeline.triggered.connect(self.fit_timeline)

        act_epoch = view_menu.addAction("Дата отсчёта таймлайна...")
        act_epoch.triggered.connect(self.edit_timeline_epoch)

        act_reload = view_menu.addAction("Обновить холст")
        act_reload.setShortcut(QKeySequence("F5"))
        act_reload.triggered.connect(self.reload_canvas)

        help_menu = menubar.addMenu("Справка")
        act_about = help_menu.addAction("О программе")
        act_about.triggered.connect(self.show_about)
        act_shortcuts = help_menu.addAction("Горячие клавиши")
        act_shortcuts.triggered.connect(self.show_shortcuts)

    def _build_statusbar(self) -> None:
        self.status_project = QLabel("")
        self.status_stats = QLabel("")
        self.status_timeline = QLabel("")
        self.status_zoom = QLabel("100%")
        self.statusBar().addWidget(self.status_project, 1)
        self.statusBar().addPermanentWidget(self.status_timeline)
        self.statusBar().addPermanentWidget(self.status_stats)
        self.statusBar().addPermanentWidget(self.status_zoom)
        self.view.viewport().installEventFilter(self)
        self.timeline.widget.viewChanged.connect(self._update_timeline_scale)

    # ======================================================================
    # Проект: открытие / создание / сохранение
    # ======================================================================
    def _pick_initial_project(self) -> Optional[str]:
        """Открывает последний проект или default_project.story из корня."""
        candidates = []
        try:
            if os.path.isfile(LAST_PROJECT_FILE):
                with open(LAST_PROJECT_FILE, "r", encoding="utf-8") as fh:
                    candidates.append(fh.read().strip())
        except OSError:
            pass
        candidates.append(os.path.join(PROJECT_ROOT, "default_project.story"))
        for path in candidates:
            if not path or not os.path.isfile(path):
                continue
            if not os.access(path, os.R_OK | os.W_OK):
                continue
            if DatabaseManager.is_project_file(path):
                return os.path.abspath(path)
        return None

    def _remember_project(self, path: str) -> None:
        try:
            os.makedirs(os.path.dirname(LAST_PROJECT_FILE), exist_ok=True)
            with open(LAST_PROJECT_FILE, "w", encoding="utf-8") as fh:
                fh.write(path)
        except OSError:
            pass

    def load_project(self, path: str, show_errors: bool = True) -> bool:
        try:
            self.db.open(path)
        except Exception as exc:  # noqa: BLE001
            if show_errors:
                QMessageBox.critical(
                    self, "Ошибка открытия", f"Не удалось открыть проект:\n{path}\n\n{exc}"
                )
            else:
                self.statusBar().showMessage(
                    f"Не удалось открыть последний проект: {os.path.basename(path)}", 7000
                )
            self.timeline.reload()
            self._update_project_ui()
            return False
        self.project_path = path
        self.modified = False
        self._remember_project(path)
        self.reload_canvas()
        self.timeline.widget.fit_all()
        self._update_project_ui()
        return True

    def confirm_discard(self) -> bool:
        """Спрашивает о сохранении, если есть несохранённые изменения."""
        if not self.modified or not self.db.is_open:
            return True
        answer = QMessageBox.question(
            self,
            "Несохранённые изменения",
            "Текущий проект изменён. Сохранить изменения перед продолжением?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            self.save_project()
        return True

    def new_project(self) -> None:
        if not self.confirm_discard():
            return
        default_name = os.path.join(os.path.expanduser("~"), "Моя новая книга.story")
        path, _ = QFileDialog.getSaveFileName(self, "Новый проект книги", default_name, PROJECT_FILTER)
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".story"
        try:
            self.db.create(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка создания", f"Не удалось создать проект:\n{exc}")
            return
        self.project_path = os.path.abspath(path)
        self.modified = False
        self._remember_project(self.project_path)
        self.reload_canvas()
        self.fit_content()
        self._update_project_ui()
        self.statusBar().showMessage(f"Создан новый проект: {os.path.basename(self.project_path)}", 5000)

    def open_project(self) -> None:
        if not self.confirm_discard():
            return
        start_dir = os.path.dirname(self.project_path) if self.project_path else PROJECT_ROOT
        path, _ = QFileDialog.getOpenFileName(self, "Открыть проект", start_dir, PROJECT_FILTER)
        if not path:
            return
        if not DatabaseManager.is_project_file(path):
            answer = QMessageBox.question(
                self,
                "Не похоже на проект",
                "Файл не является проектом Story Craft Canvas.\n"
                "Создать в нём новую структуру таблиц (данные не удаляются)?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        if self.load_project(path):
            self.center_on_content()
            self.statusBar().showMessage(f"Открыт проект: {os.path.basename(path)}", 5000)

    def save_project(self) -> bool:
        """Принудительно сохраняет координаты нод и фиксирует транзакцию."""
        if not self.db.is_open:
            return self.save_project_as()
        try:
            self.persist_node_positions()
            self.db.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить проект:\n{exc}")
            return False
        self.modified = False
        self._update_project_ui()
        self.statusBar().showMessage("Проект сохранён", 3000)
        return True

    def save_project_as(self) -> bool:
        if not self.db.is_open:
            return self.save_project()
        start = self.project_path or os.path.join(os.path.expanduser("~"), "book.story")
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить проект как", start, PROJECT_FILTER)
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += ".story"
        try:
            self.persist_node_positions()
            self.db.save()
            import shutil

            shutil.copyfile(self.project_path, path)
            self.db.open(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось сохранить копию:\n{exc}")
            return False
        self.project_path = os.path.abspath(path)
        self.modified = False
        self._remember_project(self.project_path)
        self._update_project_ui()
        self.reload_canvas()
        return True

    def close_project(self, save_first: bool = False) -> None:
        if save_first and not self.confirm_discard():
            return
        self.db.close()
        self.project_path = None
        self.modified = False
        self.scene.clear()
        self.node_items.clear()
        self.link_items.clear()
        self.timeline.reload()
        self._update_project_ui()
        self.statusBar().showMessage("Проект закрыт")

    def persist_node_positions(self) -> None:
        positions = {eid: (node.pos().x(), node.pos().y()) for eid, node in self.node_items.items()}
        queries.update_event_positions(self.db, positions)

    def mark_modified(self) -> None:
        """Помечает проект изменённым (вызывается только явными действиями)."""
        if not self.modified:
            self.modified = True
            self._update_project_ui()

    # ======================================================================
    # Обновление UI
    # ======================================================================
    def _update_project_ui(self) -> None:
        has_project = self.db.is_open
        name = self.db.file_name if has_project else "проект не открыт"
        star = " •" if self.modified else ""
        self.setWindowTitle(f"{APP_NAME} — {name}{star}")
        self.status_project.setText(f"Проект: {name}{'  (изменён)' if self.modified else ''}")
        for widget in (self.btn_characters, self.btn_add_event, self.btn_add_period,
                       self.btn_link, self.act_new, self.act_open, self.act_save):
            widget.setEnabled(has_project)
        self.timeline.setEnabled(has_project)
        if not has_project:
            self.status_stats.setText("")
        else:
            events, links, characters = self.db.stats()
            self.status_stats.setText(f"События: {events} · Связи: {links} · Персонажи: {characters}")
        self._update_timeline_scale()
        self._refresh_zoom_label()

    def _refresh_zoom_label(self) -> None:
        self.status_zoom.setText(f"{int(round(self.view.current_zoom() * 100))}%")

    def eventFilter(self, obj, event):
        if obj is self.view.viewport() and event.type() == QEvent.Wheel:
            self._refresh_zoom_label()
        return super().eventFilter(obj, event)

    # ======================================================================
    # Холст
    # ======================================================================
    def reload_canvas(self) -> None:
        self.view.cancel_link_operation()
        self.scene.clear()
        self.node_items.clear()
        self.link_items.clear()

        if not self.db.is_open:
            self._update_project_ui()
            return

        for event in queries.get_events(self.db):
            node = EventNode(
                int(event["id"]),
                event.get("title") or "Без названия",
                event.get("description") or "",
                float(event.get("x") or 0.0),
                float(event.get("y") or 0.0),
            )
            self.scene.addItem(node)
            self.node_items[int(event["id"])] = node

        for link in queries.get_links(self.db):
            source = self.node_items.get(int(link["source_event_id"]))
            target = self.node_items.get(int(link["target_event_id"]))
            if source is None or target is None:
                continue
            item = LinkItem(
                int(link["id"]),
                source,
                target,
                link.get("link_type") or "sequence",
                link.get("description") or "",
            )
            self.scene.addItem(item)
            self.link_items[int(link["id"])] = item

        self.view.update_lod()
        self.timeline.reload()
        self._update_project_ui()

    def center_on_content(self) -> None:
        if self.node_items:
            rect = QRectF()
            for node in self.node_items.values():
                rect = rect.united(node.sceneBoundingRect())
            self.view.centerOn(rect.center())
        else:
            self.view.centerOn(QPointF(0, 0))

    def reset_view(self) -> None:
        self.view.reset_zoom()
        self.view.update_lod()
        if self.db.is_open:
            self.timeline.widget.fit_all()
        self._refresh_zoom_label()

    def fit_content(self) -> None:
        if not self.node_items:
            self.reset_view()
            return
        rect = QRectF()
        for node in self.node_items.values():
            rect = rect.united(node.sceneBoundingRect())
        rect = rect.adjusted(-80, -80, 80, 80)
        self.view.fitInView(rect, Qt.KeepAspectRatio)
        if self.view.current_zoom() > 1.5:
            self.view.resetTransform()
            self.view.centerOn(rect.center())
        self.view.update_lod()
        if self.db.is_open:
            self.timeline.widget.fit_all()
        self._refresh_zoom_label()

    # ======================================================================
    # События
    # ======================================================================
    def toggle_link_mode(self, checked: bool) -> None:
        if checked and not self.db.is_open:
            return
        self.view.set_link_mode(checked)
        for widget in (self.btn_link, self.act_link):
            if widget.isChecked() != checked:
                blocked = widget.blockSignals(True)
                widget.setChecked(checked)
                widget.blockSignals(blocked)
        if checked:
            self.btn_link.setText("Выберите 2 ноды…")
            self.statusBar().showMessage("Режим связывания: кликните источник, затем приёмник (Esc — отмена)")
        else:
            self.btn_link.setText("Соединить ноды")
            self.statusBar().clearMessage()
        self.view.setFocus()

    def create_event_at(self, scene_pos: QPointF) -> None:
        """Создание события двойным кликом по пустому месту холста.

        Новое событие автоматически получает отрезок на таймлайне —
        от курсора вставки и на длительность текущего масштаба.
        """
        if not self.db.is_open:
            return
        pos = QPointF(scene_pos.x() - 90.0, scene_pos.y() - 45.0)
        time_range = self.timeline.widget.next_event_range()
        dialog = EventDetailsDialog(
            self.db,
            event_id=None,
            scene_position=pos,
            time_range=time_range,
            parent=self,
        )
        result = dialog.exec()
        if result == QDialog.Accepted and dialog.saved and dialog.event_id:
            self.mark_modified()
            self.reload_canvas()
            self._advance_playhead_after(int(dialog.event_id))
            node = self.node_items.get(int(dialog.event_id))
            if node is not None:
                self.scene.clearSelection()
                node.setSelected(True)
        self.view.setFocus()

    def _advance_playhead_after(self, event_id: int) -> None:
        record = queries.get_event(self.db, event_id)
        if not record or record.get("time_end") is None:
            return
        end = float(record["time_end"])
        self.timeline.widget.advance_playhead(end)
        self.timeline.widget.ensure_visible(end)

    def create_event_center(self) -> None:
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self.create_event_at(center)

    # ======================================================================
    # Таймлайн
    # ======================================================================
    def toggle_timeline(self, checked: bool) -> None:
        self.timeline.setVisible(checked)
        for widget in (self.btn_timeline, getattr(self, "act_timeline", None)):
            if widget is None or widget.isChecked() == checked:
                continue
            blocked = widget.blockSignals(True)
            widget.setChecked(checked)
            widget.blockSignals(blocked)

    def _sync_timeline_zoom(self, factor: float, anchor: QPointF) -> None:
        """Масштаб полосы повторяет масштаб рабочего поля."""
        if not self.timeline.isVisible() or abs(factor - 1.0) < 1e-9:
            return
        view_width = max(1, self.view.viewport().width())
        timeline_width = max(1, self.timeline.widget.width())
        anchor_x = anchor.x() * timeline_width / view_width
        self.timeline.widget.zoom_by(1.0 / factor, anchor_x)

    def _sync_timeline_pan(self, delta_x: float, delta_y: float) -> None:
        """Горизонтальная прокрутка поля двигает и таймлайн."""
        if self.timeline.isVisible() and abs(delta_x) > 1e-9:
            self.timeline.widget.pan_by_pixels(delta_x)

    def _zoom_from_timeline(self, factor: float, anchor_x: float) -> None:
        if not self.db.is_open:
            return
        x = min(max(float(anchor_x), 0.0), max(1.0, self.view.viewport().width() - 1.0))
        self.view.zoom_by(factor, QPointF(x, self.view.viewport().height() / 2.0))

    def _pan_from_timeline(self, delta_x: float) -> None:
        if not self.db.is_open:
            return
        self.view.pan_horizontal_by_pixels(delta_x)

    def create_event_at_time(self, start_time: float) -> None:
        """Событие создаётся двойным кликом по дорожке таймлайна."""
        if not self.db.is_open:
            return
        duration = self.timeline.widget.default_duration()
        center = self.view.mapToScene(self.view.viewport().rect().center())
        pos = QPointF(center.x() - 90.0, center.y() - 45.0)
        dialog = EventDetailsDialog(
            self.db,
            event_id=None,
            scene_position=pos,
            time_range=(float(start_time), float(start_time) + duration),
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted and dialog.saved and dialog.event_id:
            self.mark_modified()
            self.reload_canvas()
            self._advance_playhead_after(int(dialog.event_id))
            node = self.node_items.get(int(dialog.event_id))
            if node is not None:
                self.scene.clearSelection()
                node.setSelected(True)
        self.view.setFocus()

    def create_period_at_center(self) -> None:
        if not self.db.is_open:
            return
        self.timeline.add_period()

    def fit_timeline(self) -> None:
        if self.db.is_open:
            self.timeline.fit()

    def edit_timeline_epoch(self) -> None:
        if self.db.is_open:
            self.timeline.edit_epoch(self)

    def _update_timeline_scale(self) -> None:
        if not hasattr(self, "status_timeline"):
            return
        if self.db.is_open:
            self.status_timeline.setText(self.timeline.scale_text())
        else:
            self.status_timeline.setText("")

    def create_period(self, start_time: float, end_time: float) -> None:
        if not self.db.is_open:
            return
        dialog = PeriodDialog(self.db, start=start_time, end=end_time, parent=self)
        if dialog.exec() == QDialog.Accepted and dialog.saved:
            self.mark_modified()
            self.timeline.reload()
            self.statusBar().showMessage("Макропериод добавлен", 3000)

    def edit_period(self, period_id: int) -> None:
        if not self.db.is_open:
            return
        dialog = PeriodDialog(self.db, period_id=int(period_id), parent=self)
        dialog.exec()
        if dialog.saved or dialog.deleted:
            self.mark_modified()
            self.timeline.reload()

    def open_event(self, event_id: int) -> None:
        node = self.node_items.get(int(event_id))
        if node is None:
            return
        position = QPointF(node.pos())
        dialog = EventDetailsDialog(self.db, event_id=int(event_id), scene_position=position, parent=self)
        result = dialog.exec()
        if result == QDialog.Accepted and (dialog.saved or dialog.deleted):
            self.mark_modified()
            self.reload_canvas()

    # ======================================================================
    # Связи
    # ======================================================================
    def create_link(self, source_id: int, target_id: int) -> None:
        if source_id == target_id:
            self.statusBar().showMessage("Нельзя связать ноду с самой собой", 4000)
            return
        if queries.link_exists(self.db, source_id, target_id):
            self.statusBar().showMessage("Такая связь уже существует", 4000)
        else:
            try:
                queries.create_link(self.db, source_id, target_id, "sequence", "")
                self.db.save()
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Ошибка", f"Не удалось создать связь:\n{exc}")
            else:
                self.mark_modified()
                self.reload_canvas()
        # Режим связывания выключается после любой попытки.
        self.toggle_link_mode(False)

    def open_link(self, link_id: int) -> None:
        item = self.link_items.get(int(link_id))
        if item is None:
            return
        source_title = getattr(item.source_node, "title_text", "?")
        target_title = getattr(item.target_node, "title_text", "?")
        try:
            dialog = LinkEditDialog(self.db, int(link_id), source_title, target_title, parent=self)
        except ValueError as exc:
            QMessageBox.warning(self, "Связь не найдена", str(exc))
            self.reload_canvas()
            return
        dialog.exec()
        if dialog.deleted:
            self.mark_modified()
            self.reload_canvas()
        elif dialog.changed:
            self.mark_modified()
            item.set_link_type(dialog.link_type)
            item.set_description(dialog.description)
            self._update_project_ui()

    # ======================================================================
    # Персонажи
    # ======================================================================
    def open_characters_window(self) -> None:
        if not self.db.is_open:
            return
        dialog = CharacterWindow(self.db, parent=self)
        dialog.exec()
        self._update_project_ui()

    # ======================================================================
    # Справка
    # ======================================================================
    def show_about(self) -> None:
        QMessageBox.about(
            self,
            f"О программе {APP_NAME}",
            f"<h3>{APP_NAME} {APP_VERSION}</h3>"
            "<p>Персональный инструмент писателя для визуального проектирования сюжета.</p>"
            "<p>Один файл проекта (<code>.story</code> / <code>.db</code>) — одна книга.</p>",
        )

    def show_shortcuts(self) -> None:
        QMessageBox.information(
            self,
            "Горячие клавиши",
            "Ctrl+N — новый проект\n"
            "Ctrl+O — открыть проект\n"
            "Ctrl+S — сохранить проект\n"
            "Ctrl+Shift+S — сохранить как\n"
            "Ctrl+E — новое событие\n"
            "Ctrl+L — режим соединения нод\n"
            "Ctrl+P — персонажи и анкеты\n"
            "Колесо мыши — зум\n"
            "Средняя кнопка / Space+LMB — панорама\n"
            "Двойной клик по пустому месту — новое событие\n"
            "Двойной клик по ноде — редактировать событие\n"
            "Двойной клик по линии — редактировать связь\n"
            "F5 — обновить холст\n"
            "Esc — отменить связывание",
        )

    # ======================================================================
    # Закрытие
    # ======================================================================
    def closeEvent(self, event) -> None:
        if self.db.is_open and not self.confirm_discard():
            event.ignore()
            return
        try:
            if self.db.is_open:
                self.persist_node_positions()
                self.db.save()
        except Exception:  # noqa: BLE001
            pass
        self.db.close()
        event.accept()


# Безобидное предупреждение Qt, возникающее при первом открытии календаря
# в редакторе даты (внутренний шрифт QCalendarWidget). В консоль не выводим.
_IGNORED_QT_WARNINGS = ("QFont::setPointSize: Point size <= 0",)


def _qt_message_handler(mode, context, message: str) -> None:
    if message.startswith(_IGNORED_QT_WARNINGS):
        return
    sys.stderr.write(message + "\n")


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    qInstallMessageHandler(_qt_message_handler)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("StoryCraft")
    apply_theme(app)

    project = None
    extra = [a for a in argv[1:] if not a.startswith("-")]
    if extra and os.path.isfile(extra[0]):
        project = os.path.abspath(extra[0])

    window = MainWindow(project_path=project)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
