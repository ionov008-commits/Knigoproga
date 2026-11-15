"""Управление подключением к файлу проекта Story Craft Canvas.

Архитектура "один файл — одна книга": каждый проект — отдельный файл SQLite
(*.story / *.db). Здесь живёт только жизненный цикл соединения и схемы,
а все CRUD-операции находятся в ``queries.py``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Optional

from database import queries

PROJECT_EXTENSIONS = (".story", ".db")

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    age TEXT,
    biometrics TEXT,
    economic_base TEXT,
    family_romance TEXT,
    weak_sides TEXT,
    strong_sides TEXT,
    barriers TEXT,
    internal_conflict TEXT,
    external_conflict TEXT,
    talents TEXT,
    hobbies TEXT,
    combat_mechanics TEXT,
    backstory TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    x REAL DEFAULT 0.0,
    y REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS event_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_event_id INTEGER NOT NULL,
    target_event_id INTEGER NOT NULL,
    link_type TEXT CHECK(link_type IN ('sequence', 'influence')) DEFAULT 'sequence',
    description TEXT,
    FOREIGN KEY (source_event_id) REFERENCES events(id) ON DELETE CASCADE,
    FOREIGN KEY (target_event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS character_event_impacts (
    character_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    impact_note TEXT,
    PRIMARY KEY (character_id, event_id),
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS timeline_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    color TEXT DEFAULT '#7d5fff'
);

CREATE TABLE IF NOT EXISTS form_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    fields_json TEXT NOT NULL,
    builtin INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS character_custom_values (
    character_id INTEGER NOT NULL,
    field_key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (character_id, field_key),
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS project_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_links_source ON event_links(source_event_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON event_links(target_event_id);
CREATE INDEX IF NOT EXISTS idx_impacts_character ON character_event_impacts(character_id);
CREATE INDEX IF NOT EXISTS idx_periods_time ON timeline_periods(start_time, end_time);
CREATE INDEX IF NOT EXISTS idx_custom_values_character ON character_custom_values(character_id);
"""

# Колонки, добавленные в events после первой версии схемы (миграция).
EVENT_EXTRA_COLUMNS: dict[str, str] = {
    "time_start": "REAL",
    "time_end": "REAL",
}

DEFAULT_EPOCH_DATE = "2000-01-01"


class DatabaseManager:
    """Единственная точка доступа к текущему файлу проекта."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path: Optional[str] = None
        self._conn: Optional[sqlite3.Connection] = None
        if path:
            self.open(path)

    # ------------------------------------------------------------ state ---
    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    @property
    def connection(self) -> Optional[sqlite3.Connection]:
        return self._conn

    @property
    def file_name(self) -> str:
        return os.path.basename(self._path) if self._path else "—"

    # ------------------------------------------------------- lifecycle ---
    def _connect(self, path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.isolation_level = None  # ручные BEGIN/COMMIT для атомарности
        return conn

    def open(self, path: str) -> bool:
        """Открывает существующий проект; если файла нет — создаёт новый."""
        self.close()
        path = os.path.abspath(path)
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        conn = self._connect(path)
        self._conn = conn
        self._path = path
        self.ensure_schema()
        return True

    def create(self, path: str) -> bool:
        """Создаёт пустой проект (существующий файл перезаписывается)."""
        self.close()
        path = os.path.abspath(path)
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        if os.path.exists(path):
            os.remove(path)
        self._conn = self._connect(path)
        self._path = path
        self.ensure_schema()
        return True

    def ensure_schema(self) -> None:
        if self._conn is None:
            return
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._seed_defaults()
        self._conn.commit()

    def _migrate(self) -> None:
        """Добавляет в events колонки времени, появившиеся позже."""
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(events)")}
        for name, decl in EVENT_EXTRA_COLUMNS.items():
            if name not in columns:
                self._conn.execute(f"ALTER TABLE events ADD COLUMN {name} {decl}")

    def _seed_defaults(self) -> None:
        """Создаёт стартовый шаблон анкеты и служебные настройки."""
        count = self._conn.execute("SELECT COUNT(*) AS c FROM form_templates").fetchone()["c"]
        if count == 0:
            fields = [
                {
                    "key": key,
                    "label": label,
                    "multiline": key not in ("name", "age"),
                    "builtin": True,
                }
                for key, label in queries.CHARACTER_FIELDS
            ]
            self._conn.execute(
                "INSERT INTO form_templates (name, fields_json, builtin) VALUES (?, ?, 1)",
                (
                    queries.DEFAULT_TEMPLATE_NAME,
                    json.dumps(fields, ensure_ascii=False),
                ),
            )
        self._conn.execute(
            "INSERT OR IGNORE INTO project_meta (key, value) VALUES ('timeline_epoch', ?)",
            (DEFAULT_EPOCH_DATE,),
        )

    def save(self) -> None:
        """Принудительная фиксация всех отложенных изменений."""
        if self._conn is not None:
            self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.commit()
            finally:
                self._conn.close()
        self._conn = None

    @staticmethod
    def is_project_file(path: str) -> bool:
        """Проверяет, что файл является корректным проектом Story Craft."""
        if not path or not os.path.isfile(path):
            return False
        if os.path.splitext(path)[1].lower() not in PROJECT_EXTENSIONS:
            return False
        try:
            probe = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                row = probe.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
                ).fetchone()
                return row is not None
            finally:
                probe.close()
        except sqlite3.DatabaseError:
            return False

    def stats(self) -> tuple[int, int, int]:
        """Количество событий, связей и персонажей в текущем проекте."""
        return (
            queries.count_events(self),
            queries.count_links(self),
            queries.count_characters(self),
        )
