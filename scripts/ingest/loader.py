"""Data_Store yükleyicisi: operasyonel sheet'ler -> `logistic-ai-kb` öğeleri.

- Yalnızca question1..5, critical, summary_df yüklenir (role_user/permissions/Functions asla).
- JSON kolonları safe_json_loads ile ayrıştırılır; bozuk satır atlanır ve rapora yazılır.
- Orijinal kolonlar korunur, JSON kolonları için ``<kolon>_parsed`` eklenir.
- float -> Decimal (DynamoDB). Yazma yalnızca ``apply=True`` iken, enjekte edilen ``table`` ile yapılır.
- Yazmadan önce sheet kayıtları ``sheet-index`` sorgusuyla silinir (idempotent).
"""
from __future__ import annotations

import math
import uuid
from decimal import Decimal
from typing import Any, Iterable

from logistic_ai_data.dynamo_keys import SHEET_INDEX, kb_pk, kb_sk
from logistic_ai_data.json_safe import safe_json_loads
from logistic_ai_data.key_normalizer import normalize_key

from .report import IngestReport

# sheet -> PK için kullanılan kolon (None: '<sheet>#ALL')
LOAD_SHEETS: dict[str, str | None] = {
    "question1": "shipment_id",
    "question2": "materialno",
    "question3": "shipment_id",
    "question4": None,
    "question5": None,
    "summary_df": None,
    "critical": "mip",
}
JSON_COLUMNS: dict[str, str] = {
    "question1": "question1",
    "question2": "question2",
    "question4": "question4",
    "question5": "question5",
}
NEVER_LOAD = frozenset({"role_user", "permissions", "Functions"})


def to_dynamo(value: Any) -> Any:
    """float -> Decimal (özyinelemeli); NaN/Inf -> None."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else Decimal(str(value))
    if isinstance(value, dict):
        return {str(k): to_dynamo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_dynamo(v) for v in value]
    return value


def _num_equal(a: Any, b: Any) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def _key_equal(a: Any, b: Any) -> bool:
    return normalize_key("" if a is None else a) == normalize_key("" if b is None else b)


def check_question2(row: dict, parsed: Any) -> list[str]:
    """question2 JSON'unun kolonlarla tutarlılığı; uyuşmazlık türlerini döner."""
    if not isinstance(parsed, dict):
        return ["q2_json_not_object"]
    kinds: list[str] = []
    if not _key_equal(parsed.get("Malzeme no"), row.get("materialno")):
        kinds.append("q2_materialno_mismatch")
    entries = parsed.get("Seferle")
    match = None
    if isinstance(entries, list):
        for e in entries:
            if isinstance(e, dict) and _key_equal(e.get("seferno"), row.get("shipment_id")):
                match = e
                break
    if match is None:
        kinds.append("q2_shipment_not_in_json")
    else:
        if not _num_equal(match.get("mikta"), row.get("quantity")):
            kinds.append("q2_quantity_mismatch")
        if str(match.get("Eta Zamanı")) != str(row.get("tofas_etadate")):
            kinds.append("q2_eta_mismatch")
    return kinds


def build_items(
    sheets: dict[str, list[dict]], load_id: str, report: IngestReport
) -> dict[str, list[dict]]:
    """Sheet satırlarından DynamoDB öğeleri üretir. AWS çağrısı yapmaz."""
    out: dict[str, list[dict]] = {}
    for sheet, key_col in LOAD_SHEETS.items():
        if sheet not in sheets:
            continue
        rows = sheets[sheet]
        report.counts(sheet).read = len(rows)
        items: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for idx, row in enumerate(rows):
            xl_row = idx + 2
            data: dict[str, Any] = dict(row)
            jcol = JSON_COLUMNS.get(sheet)
            if jcol is not None:
                parsed, err = safe_json_loads(row.get(jcol))
                if err is not None:
                    report.skip(sheet, xl_row, err, jcol)
                    continue
                data[f"{jcol}_parsed"] = parsed
                if sheet == "question2":
                    for kind in check_question2(row, parsed):
                        report.warn(sheet, xl_row, kind, jcol)
            key_val = row.get(key_col) if key_col else None
            if key_col and (key_val is None or not normalize_key(key_val)):
                report.skip(sheet, xl_row, "missing_key", key_col)
                continue
            try:
                pk = kb_pk(sheet, key_val if key_col else None)
                sk = kb_sk(sheet, row, idx)
            except ValueError:
                report.skip(sheet, xl_row, "invalid_key")
                continue
            if (pk, sk) in seen:
                report.skip(sheet, xl_row, "duplicate_key")
                continue
            seen.add((pk, sk))
            items.append({"PK": pk, "SK": sk, "sheet": sheet, "data": to_dynamo(data), "load_id": load_id})
        out[sheet] = items
        report.counts(sheet).loaded = len(items)
    return out


def _existing_keys(table: Any, sheet: str) -> Iterable[dict]:
    from boto3.dynamodb.conditions import Key  # yalnızca --apply yolunda

    kwargs: dict[str, Any] = {
        "IndexName": SHEET_INDEX,
        "KeyConditionExpression": Key("sheet").eq(sheet),
        "ProjectionExpression": "PK, SK",
    }
    while True:
        resp = table.query(**kwargs)
        for it in resp.get("Items", []):
            yield {"PK": it["PK"], "SK": it["SK"]}
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return
        kwargs["ExclusiveStartKey"] = lek


def write_items(table: Any, items_by_sheet: dict[str, list[dict]], report: IngestReport) -> None:
    """Her sheet için önce mevcut kayıtları siler, sonra yazar. ``table`` enjekte edilir."""
    for sheet, items in items_by_sheet.items():
        old = list(_existing_keys(table, sheet))
        with table.batch_writer() as bw:
            for k in old:
                bw.delete_item(Key=k)
            for it in items:
                bw.put_item(Item=it)
        report.counts(sheet).deleted = len(old)


def load_workbook_data(
    wb: Any, *, apply: bool = False, table: Any = None, load_id: str | None = None
) -> IngestReport:
    """WorkbookData -> rapor. ``apply`` ve ``table`` yoksa hiçbir yazma/AWS çağrısı yapılmaz."""
    report = IngestReport(applied=apply, load_id=load_id or uuid.uuid4().hex)
    for issue in wb.report.issues:
        if issue.sheet in LOAD_SHEETS:
            report.warn(issue.sheet, issue.row, issue.kind, issue.column)
    operational = {n: r for n, r in wb.sheets.items() if n not in NEVER_LOAD}
    items = build_items(operational, report.load_id, report)
    if apply:
        if table is None:
            raise ValueError("--apply için table gerekli")
        write_items(table, items, report)
    return report
