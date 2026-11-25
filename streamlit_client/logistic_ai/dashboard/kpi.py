"""Pure KPI loading from ``summary_df`` (Req 7.3, 7.5-7.9)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from logistic_ai_data.repository import DataRepository

_LOGGER = logging.getLogger("logistic_ai.dashboard")

SUMMARY_TABLE = "summary_df"
LABEL_COLUMN = "Durum"
VALUE_COLUMN = "Adet"
ROW_TOTAL = "Tüm Seferler"
ROW_DELAYED = "Geciken Seferler"
ROW_COMPLETED = "Tamamlanan Seferler"
ROW_IN_PROGRESS = "Devam Eden Seferler"
ROW_DELAY_RATE = "Gecikme Oranı"
RATE_TOLERANCE = 0.0005


class DashboardDataError(Exception):
    """summary_df unreadable or a KPI row is missing/invalid."""


@dataclass(frozen=True)
class Kpis:
    total: int
    delayed: int
    completed: int
    in_progress: int
    delay_rate_pct: float


def _to_number(value: object) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError("not a number")
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
    return float(value)  # type: ignore[arg-type]


def load_kpis(repo: DataRepository) -> Kpis:
    try:
        rows = repo.get_all(SUMMARY_TABLE)
    except Exception as exc:
        _LOGGER.error("summary_df read failed: %s", type(exc).__name__)
        raise DashboardDataError("summary_df unreadable") from None

    by_label: dict[str, object] = {}
    for row in rows:
        label = row.get(LABEL_COLUMN)
        if isinstance(label, str):
            by_label.setdefault(label.strip(), row.get(VALUE_COLUMN))

    def required(name: str) -> int:
        if name not in by_label:
            _LOGGER.error("summary_df KPI row missing: %s", name)
            raise DashboardDataError(f"missing KPI row: {name}")
        try:
            return int(round(_to_number(by_label[name])))
        except (TypeError, ValueError):
            _LOGGER.error("summary_df KPI value invalid: %s", name)
            raise DashboardDataError(f"invalid KPI value: {name}") from None

    total = required(ROW_TOTAL)
    delayed = required(ROW_DELAYED)
    completed = required(ROW_COMPLETED)
    in_progress = required(ROW_IN_PROGRESS)

    rate = (delayed / total * 100.0) if total > 0 else 0.0

    if ROW_DELAY_RATE in by_label:
        try:
            source = _to_number(by_label[ROW_DELAY_RATE])
        except (TypeError, ValueError):
            source = None
        if source is None or abs(source - rate / 100.0) > RATE_TOLERANCE:
            _LOGGER.warning("summary_df delay rate differs from computed value")
    if completed + in_progress != total:
        _LOGGER.warning("summary_df completed + in_progress != total")

    return Kpis(total, delayed, completed, in_progress, rate)
