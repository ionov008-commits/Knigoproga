"""Утилиты времени для таймлайна (без зависимостей от Qt).

Внутри проекта время хранится как число секунд от «даты отсчёта»
(``timeline_epoch`` в project_meta). Это позволяет работать и с минутами,
и со столетиями, и с вымышленными календарями — достаточно задать дату
отсчёта в настройках таймлайна.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Optional

MINUTE = 60.0
HOUR = 60.0 * MINUTE
DAY = 24.0 * HOUR
WEEK = 7.0 * DAY
MONTH = DAY * 30.436875
YEAR = DAY * 365.2425

# Границы масштаба: от одной минуты до ста лет на всю ширину таймлайна.
MIN_SPAN = MINUTE
MAX_SPAN = 100.0 * YEAR

DEFAULT_EPOCH = _dt.datetime(2000, 1, 1)

# «Красивые» шаги между подписями делений.
TICK_STEPS: tuple[float, ...] = (
    1.0,
    5.0,
    10.0,
    15.0,
    30.0,
    MINUTE,
    2 * MINUTE,
    5 * MINUTE,
    10 * MINUTE,
    15 * MINUTE,
    30 * MINUTE,
    HOUR,
    2 * HOUR,
    3 * HOUR,
    6 * HOUR,
    12 * HOUR,
    DAY,
    2 * DAY,
    7 * DAY,
    14 * DAY,
    MONTH,
    3 * MONTH,
    6 * MONTH,
    YEAR,
    2 * YEAR,
    5 * YEAR,
    10 * YEAR,
    25 * YEAR,
    50 * YEAR,
    100 * YEAR,
)

MONTHS_SHORT = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


# ------------------------------------------------------------------ epoch ---
def parse_epoch(value: Optional[str]) -> _dt.datetime:
    """Разбирает ISO-дату отсчёта; при ошибке возвращает дату по умолчанию."""
    if value:
        try:
            parsed = _dt.datetime.fromisoformat(str(value))
            return parsed.replace(tzinfo=None)
        except (TypeError, ValueError):
            pass
    return DEFAULT_EPOCH


def epoch_to_iso(value: _dt.datetime) -> str:
    return value.strftime("%Y-%m-%d")


def seconds_to_datetime(seconds: float, epoch: Optional[_dt.datetime] = None) -> _dt.datetime:
    epoch = epoch or DEFAULT_EPOCH
    try:
        return epoch + _dt.timedelta(seconds=float(seconds))
    except (OverflowError, ValueError):
        return _dt.datetime.max if seconds > 0 else _dt.datetime.min


def datetime_to_seconds(value: _dt.datetime, epoch: Optional[_dt.datetime] = None) -> float:
    epoch = epoch or DEFAULT_EPOCH
    return (value - epoch).total_seconds()


MIN_DATETIME = _dt.datetime(1, 1, 1, 0, 0, 0)
MAX_DATETIME = _dt.datetime(9999, 12, 31, 23, 59, 59)


def seconds_range(epoch: Optional[_dt.datetime] = None) -> tuple[float, float]:
    """Допустимый диапазон секунд: от года 1 до года 9999."""
    epoch = epoch or DEFAULT_EPOCH
    return datetime_to_seconds(MIN_DATETIME, epoch), datetime_to_seconds(MAX_DATETIME, epoch)


# ------------------------------------------------------------------ ticks ---
def choose_tick_step(seconds_per_pixel: float, min_pixels: float = 90.0) -> float:
    """Наименьший «красивый» шаг, дающий не менее ``min_pixels`` на подпись."""
    target = max(seconds_per_pixel, 1e-9) * max(min_pixels, 1.0)
    for step in TICK_STEPS:
        if step >= target:
            return step
    return TICK_STEPS[-1] * 2


def tick_label(value: _dt.datetime, step: float) -> str:
    """Подпись деления в зависимости от масштаба."""
    if step < MINUTE:
        return value.strftime("%H:%M:%S")
    if step < DAY:
        return value.strftime("%H:%M")
    if step < 25 * DAY:
        return value.strftime("%d.%m")
    if step < 300 * DAY:
        return f"{MONTHS_SHORT[value.month - 1]} {value.year}"
    return str(value.year)


def calendar_ticks(
    view_start: float,
    view_end: float,
    step: float,
    epoch: Optional[_dt.datetime] = None,
    max_ticks: int = 400,
) -> list[tuple[float, str]]:
    """Деления для линейки, привязанные к календарю.

    Для месячных и годовых шагов точки выравниваются по началу месяца/года,
    поэтому подписи не повторяются (например, два «янв 1245» подряд).
    """
    epoch = epoch or DEFAULT_EPOCH
    ticks: list[tuple[float, str]] = []

    if step >= 20 * DAY:
        start_dt = seconds_to_datetime(view_start, epoch)
        if step >= 300 * DAY:
            stride = max(1, int(round(step / YEAR)))
            base_year = epoch.year
            year = start_dt.year - (start_dt.year - base_year) % stride
            year = max(1, year)
            while len(ticks) < max_ticks:
                if year > 9999:
                    break
                moment = datetime_to_seconds(_dt.datetime(year, 1, 1), epoch)
                if moment > view_end + step:
                    break
                ticks.append((moment, str(year)))
                year += stride
        else:
            stride = max(1, int(round(step / MONTH)))
            base_index = epoch.year * 12 + (epoch.month - 1)
            index = start_dt.year * 12 + (start_dt.month - 1)
            index -= (index - base_index) % stride
            while len(ticks) < max_ticks:
                year, month0 = divmod(index, 12)
                month = month0 + 1
                if year < 1:
                    index += stride
                    continue
                if year > 9999:
                    break
                moment = datetime_to_seconds(_dt.datetime(year, month, 1), epoch)
                if moment > view_end + step:
                    break
                ticks.append((moment, f"{MONTHS_SHORT[month - 1]} {year}"))
                index += stride
    else:
        first = math.floor(view_start / step) * step
        moment = first
        while len(ticks) < max_ticks:
            if moment > view_end + step:
                break
            value = seconds_to_datetime(moment, epoch)
            ticks.append((moment, tick_label(value, step)))
            moment += step

    return ticks


def format_moment(seconds: float, epoch: Optional[_dt.datetime] = None) -> str:
    """Полная дата-время для подсказок и полей ввода."""
    value = seconds_to_datetime(seconds, epoch)
    if value.second:
        return value.strftime("%d.%m.%Y %H:%M:%S")
    if value.hour or value.minute:
        return value.strftime("%d.%m.%Y %H:%M")
    return value.strftime("%d.%m.%Y")


def format_duration(seconds: float) -> str:
    """Человекочитаемая длительность: «45 мин», «3 ч», «12 дн», «4 года»."""
    seconds = abs(float(seconds))
    if seconds < MINUTE:
        return f"{int(round(seconds))} с"
    if seconds < HOUR:
        return f"{int(round(seconds / MINUTE))} мин"
    if seconds < DAY:
        return f"{int(round(seconds / HOUR))} ч"
    if seconds < 60 * DAY:
        return f"{int(round(seconds / DAY))} дн"
    if seconds < 3 * YEAR:
        return f"{int(round(seconds / MONTH))} мес"
    return f"{int(round(seconds / YEAR))} лет"


def format_range(start: float, end: float, epoch: Optional[_dt.datetime] = None) -> str:
    return f"{format_moment(start, epoch)} — {format_moment(end, epoch)}"
