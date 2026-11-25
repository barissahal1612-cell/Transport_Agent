"""Veri erişim arayüzü (Data_Store). Yalnızca kesin (normalize edilmiş) anahtar eşleşmesi."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

QUESTION1 = "question1"
QUESTION2 = "question2"
QUESTION3 = "question3"
QUESTION4 = "question4"
QUESTION5 = "question5"
SUMMARY_DF = "summary_df"
CRITICAL = "critical"

TABLES: tuple[str, ...] = (
    QUESTION1,
    QUESTION2,
    QUESTION3,
    QUESTION4,
    QUESTION5,
    SUMMARY_DF,
    CRITICAL,
)

# Anahtarlı tablolar -> anahtar kolonu. question4/question5/summary_df anahtarsızdır (yalnızca get_all).
KEY_COLUMNS: dict[str, str] = {
    QUESTION1: "shipment_id",
    QUESTION2: "materialno",
    QUESTION3: "shipment_id",
    CRITICAL: "mip",
}


class UnknownTableError(KeyError):
    """Bilinmeyen tablo adı."""


class KeylessTableError(ValueError):
    """Anahtar kolonu olmayan tabloda get_by_key çağrıldı."""


def require_table(table: str) -> str:
    if table not in TABLES:
        raise UnknownTableError(table)
    return table


@runtime_checkable
class DataRepository(Protocol):
    def get_by_key(self, table: str, key: object) -> list[dict]: ...

    def get_all(self, table: str) -> list[dict]: ...
