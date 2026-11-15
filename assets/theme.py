"""Загрузка Obsidian Dark темы и палитры приложения."""

from __future__ import annotations

import os

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
STYLES_PATH = os.path.join(ASSETS_DIR, "styles.qss")

# Единая палитра из ТЗ (используется в графических элементах холста).
COLOR_APP_BG = "#1e1e1e"
COLOR_CANVAS_BG = "#141414"
COLOR_PANEL = "#252526"
COLOR_BORDER = "#3c3c3c"
COLOR_TEXT = "#dcddde"
COLOR_TEXT_MUTED = "#a0a0a0"
COLOR_ACCENT = "#7d5fff"
COLOR_ACCENT_HOVER = "#8f75ff"
COLOR_GRID = "#232323"
COLOR_GRID_MAJOR = "#1d1d1d"
COLOR_DANGER = "#d63031"
COLOR_SEQUENCE_LINE = "#a0a0a0"

# Размеры ноды события (ТЗ 5.3).
NODE_WIDTH = 180.0
NODE_HEIGHT = 90.0
NODE_RADIUS = 8.0


def load_stylesheet() -> str:
    """Читает assets/styles.qss. При ошибке возвращает строку-заглушку."""
    try:
        with open(STYLES_PATH, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return "QMainWindow { background-color: #1e1e1e; color: #dcddde; }"


def apply_theme(app) -> None:
    """Применяет QSS к приложению и включает тёмную палитру Qt."""
    from PySide6.QtGui import QColor, QPalette

    palette = app.palette()
    palette.setColor(QPalette.Window, QColor(COLOR_APP_BG))
    palette.setColor(QPalette.WindowText, QColor(COLOR_TEXT))
    palette.setColor(QPalette.Base, QColor("#1b1b1c"))
    palette.setColor(QPalette.AlternateBase, QColor(COLOR_PANEL))
    palette.setColor(QPalette.Text, QColor(COLOR_TEXT))
    palette.setColor(QPalette.Button, QColor(COLOR_PANEL))
    palette.setColor(QPalette.ButtonText, QColor(COLOR_TEXT))
    palette.setColor(QPalette.Highlight, QColor(COLOR_ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipBase, QColor(COLOR_PANEL))
    palette.setColor(QPalette.ToolTipText, QColor(COLOR_TEXT))
    app.setPalette(palette)
    app.setStyleSheet(load_stylesheet())
