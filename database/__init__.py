"""Слой данных: соединение с проектом и SQL-запросы."""

from database.db_manager import DatabaseManager
from database import queries

__all__ = ["DatabaseManager", "queries"]
