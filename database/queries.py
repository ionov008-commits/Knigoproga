"""Выделенный слой SQL-запросов (CRUD для всех сущностей).

Все функции принимают ``db`` — экземпляр :class:`db_manager.DatabaseManager`.
Если проект не открыт, операции чтения возвращают пустые значения,
а операции записи — ``None``. Запросы ничего не знают о UI.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable, Optional

# Поля анкеты персонажа в порядке отображения в форме.
CHARACTER_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "Имя"),
    ("age", "Возраст"),
    ("biometrics", "Внешность / биометрия"),
    ("economic_base", "Экономическая база"),
    ("family_romance", "Семья, романтика"),
    ("weak_sides", "Слабые и мерзкие стороны характера, страхи"),
    ("strong_sides", "Сильные и героические стороны, превозмогания"),
    ("barriers", "Барьеры, совесть"),
    ("internal_conflict", "Внутренний конфликт"),
    ("external_conflict", "Внешний конфликт"),
    ("talents", "Таланты, профессиональные качества"),
    ("hobbies", "Сторонние увлечения, мелкие действия"),
    ("combat_mechanics", "Боевая механика"),
    ("backstory", "Предыстория, ключевые события"),
)

CHARACTER_FIELD_KEYS: tuple[str, ...] = tuple(key for key, _ in CHARACTER_FIELDS)

LINK_TYPES: tuple[tuple[str, str], ...] = (
    ("sequence", "Последовательность (сплошная линия)"),
    ("influence", "Влияние (штрих-пунктир)"),
)

# Шаблоны анкет: ключи встроенных полей (колонок characters).
SINGLE_LINE_BUILTIN: tuple[str, ...] = ("name", "age")
DEFAULT_TEMPLATE_NAME = "Классическая анкета"
PERIOD_COLORS: tuple[str, ...] = (
    "#7d5fff",
    "#4a90d9",
    "#2ecc71",
    "#e6a23c",
    "#d63031",
    "#9b59b6",
    "#16a085",
    "#7f8c8d",
)


# --------------------------------------------------------------- helpers ---
@contextmanager
def _tx(db: Any):
    """Атомарная запись: BEGIN / COMMIT / ROLLBACK."""
    conn = db.connection
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _rows(db: Any, sql: str, params: Iterable[Any] = ()) -> list[dict]:
    if db is None or db.connection is None:
        return []
    cur = db.connection.execute(sql, tuple(params))
    return [dict(row) for row in cur.fetchall()]


def _row(db: Any, sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
    rows = _rows(db, sql, params)
    return rows[0] if rows else None


def _write(db: Any, sql: str, params: Iterable[Any] = ()) -> Optional[int]:
    if db is None or db.connection is None:
        return None
    with _tx(db) as conn:
        cur = conn.execute(sql, tuple(params))
        last_id = cur.lastrowid
    return last_id


# ---------------------------------------------------------------- counts ---
def count_events(db: Any) -> int:
    row = _row(db, "SELECT COUNT(*) AS c FROM events")
    return int(row["c"]) if row else 0


def count_links(db: Any) -> int:
    row = _row(db, "SELECT COUNT(*) AS c FROM event_links")
    return int(row["c"]) if row else 0


def count_characters(db: Any) -> int:
    row = _row(db, "SELECT COUNT(*) AS c FROM characters")
    return int(row["c"]) if row else 0


# ----------------------------------------------------------- characters ---
def get_characters(db: Any) -> list[dict]:
    return _rows(db, "SELECT * FROM characters ORDER BY name COLLATE NOCASE ASC, id ASC")


def get_character_names(db: Any) -> list[tuple[int, str]]:
    rows = _rows(db, "SELECT id, name FROM characters ORDER BY name COLLATE NOCASE ASC, id ASC")
    return [(int(r["id"]), str(r["name"])) for r in rows]


def get_character(db: Any, character_id: int) -> Optional[dict]:
    return _row(db, "SELECT * FROM characters WHERE id = ?", (character_id,))


def create_character(db: Any, name: str = "Новый персонаж", **fields: Any) -> Optional[int]:
    data: dict[str, Any] = {key: fields.get(key) for key in CHARACTER_FIELD_KEYS}
    data["name"] = (name or "Новый персонаж").strip() or "Новый персонаж"
    placeholders = ", ".join("?" for _ in CHARACTER_FIELD_KEYS)
    return _write(
        db,
        f"INSERT INTO characters ({', '.join(CHARACTER_FIELD_KEYS)}) VALUES ({placeholders})",
        [data[key] for key in CHARACTER_FIELD_KEYS],
    )


def update_character(db: Any, character_id: int, data: dict[str, Any]) -> bool:
    values = {key: data.get(key) for key in CHARACTER_FIELD_KEYS if key in data}
    if not values:
        return False
    if "name" in values:
        values["name"] = (values["name"] or "").strip() or "Без имени"
    assignments = ", ".join(f"{key} = ?" for key in values)
    params = list(values.values()) + [character_id]
    _write(db, f"UPDATE characters SET {assignments} WHERE id = ?", params)
    return True


def delete_character(db: Any, character_id: int) -> None:
    """Удаляет персонажа; заметки изменений удаляются каскадно."""
    _write(db, "DELETE FROM characters WHERE id = ?", (character_id,))


# --------------------------------------------------------------- events ---
def get_events(db: Any) -> list[dict]:
    return _rows(db, "SELECT * FROM events ORDER BY id ASC")


def get_event(db: Any, event_id: int) -> Optional[dict]:
    return _row(db, "SELECT * FROM events WHERE id = ?", (event_id,))


def create_event(db: Any, title: str, description: str = "", x: float = 0.0, y: float = 0.0) -> Optional[int]:
    return _write(
        db,
        "INSERT INTO events (title, description, x, y) VALUES (?, ?, ?, ?)",
        (title.strip() or "Без названия", description, float(x), float(y)),
    )


def update_event(
    db: Any,
    event_id: int,
    title: str,
    description: str,
    x: Optional[float] = None,
    y: Optional[float] = None,
) -> None:
    if x is None or y is None:
        _write(
            db,
            "UPDATE events SET title = ?, description = ? WHERE id = ?",
            (title.strip() or "Без названия", description, event_id),
        )
    else:
        _write(
            db,
            "UPDATE events SET title = ?, description = ?, x = ?, y = ? WHERE id = ?",
            (title.strip() or "Без названия", description, float(x), float(y), event_id),
        )


def update_event_position(db: Any, event_id: int, x: float, y: float) -> None:
    _write(db, "UPDATE events SET x = ?, y = ? WHERE id = ?", (float(x), float(y), event_id))


def update_event_positions(db: Any, positions: dict[int, tuple[float, float]]) -> None:
    """Пакетное сохранение координат нод (Ctrl+S)."""
    if db is None or db.connection is None or not positions:
        return
    with _tx(db) as conn:
        conn.executemany(
            "UPDATE events SET x = ?, y = ? WHERE id = ?",
            [(float(x), float(y), int(event_id)) for event_id, (x, y) in positions.items()],
        )


def delete_event(db: Any, event_id: int) -> None:
    """Удаляет событие; связи и заметки персонажей удаляются каскадно."""
    _write(db, "DELETE FROM events WHERE id = ?", (event_id,))


# ---------------------------------------------------------------- links ---
def get_links(db: Any) -> list[dict]:
    return _rows(db, "SELECT * FROM event_links ORDER BY id ASC")


def get_link(db: Any, link_id: int) -> Optional[dict]:
    return _row(db, "SELECT * FROM event_links WHERE id = ?", (link_id,))


def link_exists(db: Any, source_id: int, target_id: int) -> bool:
    return (
        _row(
            db,
            "SELECT id FROM event_links WHERE source_event_id = ? AND target_event_id = ?",
            (source_id, target_id),
        )
        is not None
    )


def create_link(
    db: Any,
    source_id: int,
    target_id: int,
    link_type: str = "sequence",
    description: str = "",
) -> Optional[int]:
    if source_id == target_id:
        return None
    if link_type not in {"sequence", "influence"}:
        link_type = "sequence"
    return _write(
        db,
        "INSERT INTO event_links (source_event_id, target_event_id, link_type, description) "
        "VALUES (?, ?, ?, ?)",
        (source_id, target_id, link_type, description),
    )


def update_link(db: Any, link_id: int, link_type: str, description: str) -> None:
    if link_type not in {"sequence", "influence"}:
        link_type = "sequence"
    _write(
        db,
        "UPDATE event_links SET link_type = ?, description = ? WHERE id = ?",
        (link_type, description, link_id),
    )


def delete_link(db: Any, link_id: int) -> None:
    _write(db, "DELETE FROM event_links WHERE id = ?", (link_id,))


def delete_links_for_event(db: Any, event_id: int) -> None:
    _write(
        db,
        "DELETE FROM event_links WHERE source_event_id = ? OR target_event_id = ?",
        (event_id, event_id),
    )


# -------------------------------------------------------------- impacts ---
def get_event_impacts(db: Any, event_id: int) -> dict[int, str]:
    """{character_id: impact_note} для конкретного события."""
    rows = _rows(
        db,
        "SELECT character_id, impact_note FROM character_event_impacts WHERE event_id = ?",
        (event_id,),
    )
    return {int(r["character_id"]): (r["impact_note"] or "") for r in rows}


def set_event_impacts(db: Any, event_id: int, impacts: dict[int, str]) -> None:
    """Полностью перезаписывает список участников события."""
    if db is None or db.connection is None:
        return
    with _tx(db) as conn:
        conn.execute("DELETE FROM character_event_impacts WHERE event_id = ?", (event_id,))
        conn.executemany(
            "INSERT INTO character_event_impacts (character_id, event_id, impact_note) VALUES (?, ?, ?)",
            [(int(cid), int(event_id), note or "") for cid, note in impacts.items()],
        )


def set_character_impact(db: Any, character_id: int, event_id: int, note: str) -> None:
    _write(
        db,
        "INSERT INTO character_event_impacts (character_id, event_id, impact_note) VALUES (?, ?, ?) "
        "ON CONFLICT(character_id, event_id) DO UPDATE SET impact_note = excluded.impact_note",
        (character_id, event_id, note),
    )


def remove_character_impact(db: Any, character_id: int, event_id: int) -> None:
    _write(
        db,
        "DELETE FROM character_event_impacts WHERE character_id = ? AND event_id = ?",
        (character_id, event_id),
    )


def get_character_timeline(db: Any, character_id: int) -> list[dict]:
    """Цепочка событий персонажа, отсортированная по ID события."""
    return _rows(
        db,
        "SELECT e.id AS event_id, e.title, e.description, i.impact_note, i.rowid AS impact_id "
        "FROM character_event_impacts i "
        "JOIN events e ON e.id = i.event_id "
        "WHERE i.character_id = ? "
        "ORDER BY e.id ASC",
        (character_id,),
    )


# ------------------------------------------------------------- метаданные ---
def get_meta(db: Any, key: str, default: Optional[str] = None) -> Optional[str]:
    row = _row(db, "SELECT value FROM project_meta WHERE key = ?", (key,))
    return row["value"] if row else default


def set_meta(db: Any, key: str, value: str) -> None:
    _write(
        db,
        "INSERT INTO project_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def get_timeline_epoch(db: Any) -> str:
    return get_meta(db, "timeline_epoch", "2000-01-01") or "2000-01-01"


# ----------------------------------------------------- таймлайн: периоды ---
def get_periods(db: Any) -> list[dict]:
    return _rows(db, "SELECT * FROM timeline_periods ORDER BY start_time ASC, id ASC")


def get_period(db: Any, period_id: int) -> Optional[dict]:
    return _row(db, "SELECT * FROM timeline_periods WHERE id = ?", (period_id,))


def create_period(
    db: Any,
    title: str,
    start_time: float,
    end_time: float,
    color: Optional[str] = None,
) -> Optional[int]:
    color = color or PERIOD_COLORS[0]
    return _write(
        db,
        "INSERT INTO timeline_periods (title, start_time, end_time, color) VALUES (?, ?, ?, ?)",
        (title.strip() or "Новый период", float(start_time), float(end_time), color),
    )


def update_period(
    db: Any,
    period_id: int,
    title: str,
    start_time: float,
    end_time: float,
    color: Optional[str] = None,
) -> None:
    _write(
        db,
        "UPDATE timeline_periods SET title = ?, start_time = ?, end_time = ?, color = ? WHERE id = ?",
        (
            title.strip() or "Новый период",
            float(start_time),
            float(end_time),
            color or PERIOD_COLORS[0],
            int(period_id),
        ),
    )


def delete_period(db: Any, period_id: int) -> None:
    _write(db, "DELETE FROM timeline_periods WHERE id = ?", (int(period_id),))


# ----------------------------------------------------- таймлайн: события ---
def get_timed_events(db: Any) -> list[dict]:
    """События, размещённые на таймлайне, по возрастанию начала."""
    return _rows(
        db,
        "SELECT * FROM events "
        "WHERE time_start IS NOT NULL AND time_end IS NOT NULL "
        "ORDER BY time_start ASC, id ASC",
    )


def update_event_time(db: Any, event_id: int, start_time: float, end_time: float) -> None:
    _write(
        db,
        "UPDATE events SET time_start = ?, time_end = ? WHERE id = ?",
        (float(start_time), float(end_time), int(event_id)),
    )


def clear_event_time(db: Any, event_id: int) -> None:
    _write(
        db,
        "UPDATE events SET time_start = NULL, time_end = NULL WHERE id = ?",
        (int(event_id),),
    )


# -------------------------------------------------- шаблоны анкет (пресеты) ---
def default_template_fields() -> list[dict]:
    return [
        {
            "key": key,
            "label": label,
            "multiline": key not in SINGLE_LINE_BUILTIN,
            "builtin": True,
        }
        for key, label in CHARACTER_FIELDS
    ]


def _normalize_fields(fields: Iterable[dict]) -> list[dict]:
    """Приводит список полей к безопасному виду; имя всегда присутствует."""
    result: list[dict] = []
    seen: set[str] = set()
    for item in fields or ():
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        label = str(item.get("label") or key).strip() or key
        builtin = bool(item.get("builtin", key in CHARACTER_FIELD_KEYS))
        multiline = bool(item.get("multiline", key not in SINGLE_LINE_BUILTIN))
        if key == "name":
            builtin = True
            multiline = False
        result.append({"key": key, "label": label, "multiline": multiline, "builtin": builtin})
    if not result:
        result = default_template_fields()
    if "name" not in seen:
        result.insert(
            0,
            {"key": "name", "label": "Имя", "multiline": False, "builtin": True},
        )
    return result


def _parse_fields(raw: Any) -> list[dict]:
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        data = []
    if not isinstance(data, list):
        data = []
    return _normalize_fields(data)


def _template_dict(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "fields": _parse_fields(row.get("fields_json")),
        "builtin": bool(row.get("builtin")),
    }


def list_templates(db: Any) -> list[dict]:
    rows = _rows(
        db,
        "SELECT id, name, fields_json, builtin FROM form_templates "
        "ORDER BY builtin DESC, name COLLATE NOCASE ASC, id ASC",
    )
    return [_template_dict(row) for row in rows]


def get_template(db: Any, template_id: int) -> Optional[dict]:
    row = _row(
        db,
        "SELECT id, name, fields_json, builtin FROM form_templates WHERE id = ?",
        (int(template_id),),
    )
    return _template_dict(row) if row else None


def save_template(
    db: Any,
    name: str,
    fields: Iterable[dict],
    template_id: Optional[int] = None,
) -> int:
    """Создаёт или обновляет шаблон. Бросает ValueError при конфликте имени."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Название шаблона не может быть пустым.")
    payload = json.dumps(_normalize_fields(fields), ensure_ascii=False)
    try:
        if template_id:
            _write(
                db,
                "UPDATE form_templates SET name = ?, fields_json = ? WHERE id = ?",
                (name, payload, int(template_id)),
            )
            return int(template_id)
        new_id = _write(
            db,
            "INSERT INTO form_templates (name, fields_json, builtin) VALUES (?, ?, 0)",
            (name, payload),
        )
        return int(new_id or 0)
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"Шаблон с названием «{name}» уже существует.") from exc


def delete_template(db: Any, template_id: int) -> None:
    total = _row(db, "SELECT COUNT(*) AS c FROM form_templates")
    if total and int(total["c"]) <= 1:
        raise ValueError("Нельзя удалить единственный шаблон анкеты.")
    _write(db, "DELETE FROM form_templates WHERE id = ?", (int(template_id),))
    if get_meta(db, "active_template_id") == str(template_id):
        _write(db, "DELETE FROM project_meta WHERE key = 'active_template_id'")


def duplicate_template(db: Any, template_id: int) -> int:
    source = get_template(db, template_id)
    if source is None:
        raise ValueError("Шаблон не найден.")
    existing = {t["name"] for t in list_templates(db)}
    base = f"{source['name']} (копия)"
    name = base
    index = 2
    while name in existing:
        name = f"{base} {index}"
        index += 1
    return save_template(db, name, source["fields"])


def get_active_template(db: Any) -> Optional[dict]:
    raw = get_meta(db, "active_template_id")
    template = None
    if raw and str(raw).isdigit():
        template = get_template(db, int(raw))
    if template is not None:
        return template
    templates = list_templates(db)
    if not templates:
        return None
    set_active_template(db, templates[0]["id"])
    return templates[0]


def set_active_template(db: Any, template_id: int) -> None:
    set_meta(db, "active_template_id", str(int(template_id)))


def get_custom_values(db: Any, character_id: int) -> dict[str, str]:
    rows = _rows(
        db,
        "SELECT field_key, value FROM character_custom_values WHERE character_id = ?",
        (int(character_id),),
    )
    return {str(row["field_key"]): (row["value"] or "") for row in rows}


def set_custom_values(db: Any, character_id: int, values: dict[str, str]) -> None:
    """Сохраняет значения нестандартных полей, не стирая прочие ключи."""
    if db is None or db.connection is None:
        return
    items = [
        (int(character_id), str(key), str(value))
        for key, value in values.items()
        if key not in CHARACTER_FIELD_KEYS
    ]
    if not items:
        return
    with _tx(db) as conn:
        conn.executemany(
            "INSERT INTO character_custom_values (character_id, field_key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(character_id, field_key) DO UPDATE SET value = excluded.value",
            items,
        )
