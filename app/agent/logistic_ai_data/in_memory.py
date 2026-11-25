"""Bellek içi DataRepository uygulaması (test ve yerel çalışma için)."""
from __future__ import annotations

from typing import Mapping, Sequence

from .key_normalizer import normalize_key
from .repository import (
    KEY_COLUMNS,
    QUESTION3,
    KeylessTableError,
    require_table,
)


def _stop_order(row: dict) -> int:
    try:
        return int(float(str(row.get("stop_sequence")).strip()))
    except (TypeError, ValueError):
        return 10**9  # geçersiz sıra en sona


class InMemoryDataRepository:
    def __init__(self, rows_by_table: Mapping[str, Sequence[dict]] | None = None) -> None:
        self._rows: dict[str, list[dict]] = {}
        for table, rows in (rows_by_table or {}).items():
            require_table(table)
            self._rows[table] = [dict(r) for r in rows]

    def get_all(self, table: str) -> list[dict]:
        require_table(table)
        return [dict(r) for r in self._rows.get(table, [])]

    def get_by_key(self, table: str, key: object) -> list[dict]:
        require_table(table)
        column = KEY_COLUMNS.get(table)
        if column is None:
            raise KeylessTableError(table)
        wanted = normalize_key(key)
        if not wanted:
            return []
        result = [
            dict(r)
            for r in self._rows.get(table, [])
            if normalize_key(r.get(column)) == wanted
        ]
        if table == QUESTION3:
            result.sort(key=_stop_order)
        return result
