"""Excel okuyucu: Data/*.xlsx -> WorkbookData.

- Sheet ve kolon adları korunur.
- Anahtar kolonlar string'e çevrilir (``to_key_string``, '.0' eklenmez).
- datetime -> 'YYYY-MM-DD HH:MM:SS'.
- Formül hücrelerinde önbellekteki hesaplanmış değer okunur; yoksa ReadReport'a hata yazılır.
- Kimlik doğrulama sheet'leri (role_user, permissions) ``auth_sheets`` özniteliğinde ayrı tutulur;
  ``sheets`` (operasyonel) içinde bulunmaz. Değerler (şifre dahil) hiçbir zaman günlüğe yazılmaz.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
from logistic_ai_data.key_normalizer import to_key_string

AUTH_SHEETS: frozenset[str] = frozenset({"role_user", "permissions"})
KEY_COLUMNS: frozenset[str] = frozenset(
    c.lower() for c in ("shipment_id", "materialno", "supplier_code", "mip", "USERID")
)
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

Row = dict[str, Any]


@dataclass(frozen=True)
class ReadIssue:
    """Okuma hatası. Hücre değeri içermez (şifre sızıntısını önlemek için)."""

    sheet: str
    row: int  # Excel satır numarası (1 tabanlı, başlık = 1)
    kind: str  # örn. 'formula_no_cached_value'
    column: str | None = None


@dataclass
class ReadReport:
    issues: list[ReadIssue] = field(default_factory=list)
    rows_read: dict[str, int] = field(default_factory=dict)

    def add(self, sheet: str, row: int, kind: str, column: str | None = None) -> None:
        self.issues.append(ReadIssue(sheet, row, kind, column))

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass
class WorkbookData:
    """Operasyonel sheet'ler ``sheets`` içinde; kimlik sheet'leri yalnızca ``auth_sheets`` içinde."""

    sheets: dict[str, list[Row]]
    columns: dict[str, list[str]]
    auth_sheets: dict[str, list[Row]]
    report: ReadReport

    def __repr__(self) -> str:  # değerleri (şifreler) açığa çıkarmaz
        counts = {n: len(r) for n, r in {**self.sheets, **self.auth_sheets}.items()}
        return f"WorkbookData(row_counts={counts}, issues={len(self.report.issues)})"


def _convert(value: Any, column: str) -> Any:
    if value is None:
        return None
    if column.lower() in KEY_COLUMNS:
        if isinstance(value, _dt.datetime):
            return value.strftime(DATETIME_FORMAT)
        return to_key_string(value)
    if isinstance(value, _dt.datetime):
        return value.strftime(DATETIME_FORMAT)
    if isinstance(value, _dt.date):
        return value.strftime("%Y-%m-%d")
    return value


def read_workbook(path: str | Path) -> WorkbookData:
    """Excel dosyasını okur. Dosya kopyalanmaz; yalnızca verilen yol açılır."""
    path = Path(path)
    # Önbellek değerleri (data_only=True) ve formül tespiti (data_only=False) için iki salt-okunur açılış.
    wb_vals = openpyxl.load_workbook(path, data_only=True, read_only=True)
    wb_forms = openpyxl.load_workbook(path, data_only=False, read_only=True)
    report = ReadReport()
    sheets: dict[str, list[Row]] = {}
    auth: dict[str, list[Row]] = {}
    columns: dict[str, list[str]] = {}
    try:
        for ws_v in wb_vals.worksheets:
            name = ws_v.title
            ws_f = wb_forms[name]
            rows_v = ws_v.iter_rows()
            rows_f = ws_f.iter_rows()
            header_cells = next(rows_v, None)
            next(rows_f, None)
            if header_cells is None:
                continue
            headers = [
                "" if c.value is None else str(c.value).strip() for c in header_cells
            ]
            out: list[Row] = []
            for r_idx, (cells_v, cells_f) in enumerate(zip(rows_v, rows_f), start=2):
                row: Row = {}
                empty = True
                for i, h in enumerate(headers):
                    if not h:
                        continue
                    cv = cells_v[i].value if i < len(cells_v) else None
                    cf = cells_f[i].value if i < len(cells_f) else None
                    if isinstance(cf, str) and cf.startswith("=") and cv is None:
                        report.add(name, r_idx, "formula_no_cached_value", h)
                    if cv is not None:
                        empty = False
                    row[h] = _convert(cv, h)
                if not empty:
                    out.append(row)
            report.rows_read[name] = len(out)
            columns[name] = [h for h in headers if h]
            (auth if name in AUTH_SHEETS else sheets)[name] = out
    finally:
        wb_vals.close()
        wb_forms.close()
    return WorkbookData(sheets=sheets, columns=columns, auth_sheets=auth, report=report)
