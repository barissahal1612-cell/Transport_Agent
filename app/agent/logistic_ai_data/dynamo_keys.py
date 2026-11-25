"""DynamoDB `logistic-ai-kb` anahtar eşlemesinin TEK kaynağı (design.md "Anahtar eşlemesi").

Hem DynamoDataRepository (okuma) hem yükleyici (yazma) bu fonksiyonları kullanır.
Saf fonksiyonlardır; AWS çağrısı yapmaz.
"""
from __future__ import annotations

from typing import Mapping

from .key_normalizer import normalize_key
from .repository import CRITICAL, QUESTION1, QUESTION2, QUESTION3, require_table

KB_TABLE_ENV = "LOGISTIC_AI_KB_TABLE"
DEFAULT_KB_TABLE = "logistic-ai-kb"
SHEET_INDEX = "sheet-index"

KEYLESS_PK_SUFFIX = "ALL"
_WIDTH = 4


def kb_pk(table: str, key_or_none: object | None = None) -> str:
    """PK değeri: '<table>#<normalize_key(key)>' veya anahtarsız tablolar için '<table>#ALL'."""
    require_table(table)
    if key_or_none is None:
        return f"{table}#{KEYLESS_PK_SUFFIX}"
    return f"{table}#{normalize_key(key_or_none)}"


def _pad(value: int) -> str:
    return str(int(value)).zfill(_WIDTH)


def kb_sk(table: str, row: Mapping[str, object], index: int) -> str:
    """SK değeri. `index` satırın sheet içindeki sırasıdır (anahtarsız tablolar için kullanılır)."""
    require_table(table)
    if table == QUESTION1:
        return _pad(0)
    if table == QUESTION2:
        return normalize_key(row.get("shipment_id"))
    if table == QUESTION3:
        raw = normalize_key(row.get("stop_sequence"))
        try:
            return _pad(int(float(raw)))
        except ValueError:
            raise ValueError(f"question3 stop_sequence sayısal olmalı: {raw!r}") from None
    if table == CRITICAL:
        return f"{normalize_key(row.get('shipment_id'))}#{normalize_key(row.get('materialno'))}"
    return _pad(index)
