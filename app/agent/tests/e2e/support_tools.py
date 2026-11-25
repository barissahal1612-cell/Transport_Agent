"""Helpers for the tool E2E tests (task 12.3). Local only: no AWS, no LLM.

The expected values are computed from the *raw* worksheet cells with openpyxl directly
(``raw_sheet``), independently of ``scripts/ingest/excel_reader`` which is the code path that
feeds the system under test.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Any

_AGENT_DIR = Path(__file__).resolve().parents[2]
_PROJECT = _AGENT_DIR.parents[1]
for _p in (_AGENT_DIR, _PROJECT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
try:  # openpyxl lives only in the scripts venv; borrow its pure-python site-packages if needed
    import openpyxl  # noqa: F401
except ImportError:  # pragma: no cover
    for _sp in (_PROJECT / "scripts" / ".venv" / "lib").glob("python*/site-packages"):
        sys.path.append(str(_sp))
    import openpyxl  # noqa: F401

from ingest.excel_reader import read_workbook  # noqa: E402
from logistic_ai_data.in_memory import InMemoryDataRepository  # noqa: E402
from logistic_ai_data.json_safe import safe_json_loads  # noqa: E402
from logistic_ai_data.repository import TABLES  # noqa: E402
from logistic_ai_shared_auth.auth.users import InMemoryUserRepository, UserRecord  # noqa: E402
from logistic_ai_shared_auth.authorization.permission_service import PermissionService  # noqa: E402
from logistic_ai_shared_auth.authorization.permission_store import (  # noqa: E402
    InMemoryPermissionRepository,
    resource_key,
    role_subject,
)
from logistic_ai_shared_auth.authorization.resources import FUNCTION, FUNCTIONS, TABLE  # noqa: E402
from logistic_ai_shared_auth.authorization.resources import TABLES as PERM_TABLES  # noqa: E402

EXCEL = _PROJECT / "Data" / "Agent_AWS_2026-11-24.xlsx"
ROLES = ("SUPPLIER", "MATERIAL_RESPONSIBLE", "TRANSPORT_OFFICE", "ADMIN")
JSON_COLUMNS = {"question1": "question1", "question2": "question2", "question4": "question4", "question5": "question5"}
OPERATIONAL = ("question1", "question2", "question3", "question4", "question5", "summary_df", "critical")
KEY_COLS = {"shipment_id", "materialno", "supplier_code", "mip"}
DT_FMT = "%Y-%m-%d %H:%M:%S"
FUNCTION_TABLE = {
    "get_truck_location": "question1",
    "get_material_truck_allocation": "question2",
    "get_truck_route_info": "question3",
    "get_delayed_truck": "question4",
    "get_truck_tobearrived": "question5",
    "get_critical_part_status": "critical",
}


# ---------------------------------------------------------------- independent raw reading
def _raw_key(v: Any) -> str:
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def raw_sheet(name: str) -> list[dict]:
    """Rows straight from the worksheet (openpyxl only). Key columns -> str, datetime -> text."""
    wb = openpyxl.load_workbook(EXCEL, data_only=True, read_only=True)
    try:
        it = wb[name].iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else "" for h in next(it)]
        out = []
        for cells in it:
            if all(c is None for c in cells):
                continue
            row = {}
            for h, c in zip(headers, cells):
                if not h:
                    continue
                if isinstance(c, _dt.datetime):
                    c = c.strftime(DT_FMT)
                elif h in KEY_COLS and c is not None:
                    c = _raw_key(c)
                row[h] = c
            out.append(row)
        return out
    finally:
        wb.close()


_RAW: dict[str, list[dict]] = {}


def raw(name: str) -> list[dict]:
    if name not in _RAW:
        _RAW[name] = raw_sheet(name)
    return _RAW[name]


# ---------------------------------------------------------------- system under test wiring
def build_repo_rows() -> dict[str, list[dict]]:
    """Real workbook through the ingestion reader; '<col>_parsed' added for JSON columns."""
    wb = read_workbook(EXCEL)
    rows: dict[str, list[dict]] = {}
    for sheet in OPERATIONAL:
        out = []
        for r in wb.sheets[sheet]:
            d = dict(r)
            col = JSON_COLUMNS.get(sheet)
            if col:
                parsed, err = safe_json_loads(r.get(col))
                assert err is None, f"bad JSON in {sheet}"
                d[f"{col}_parsed"] = parsed
            out.append(d)
        rows[sheet] = out
    return rows


class SpyRepo:
    """Wraps a repository and counts calls; optional row transform for q3 (order/typing tests)."""

    def __init__(self, inner: Any, transform: Any = None) -> None:
        self.inner = inner
        self.calls: list[tuple] = []
        self.transform = transform

    def get_by_key(self, table: str, key: object) -> list[dict]:
        self.calls.append(("get_by_key", table, key))
        rows = self.inner.get_by_key(table, key)
        return self.transform(table, rows) if self.transform else rows

    def get_all(self, table: str) -> list[dict]:
        self.calls.append(("get_all", table))
        rows = self.inner.get_all(table)
        return self.transform(table, rows) if self.transform else rows


class ExplodingRepo:
    def __init__(self) -> None:
        self.calls = 0

    def get_by_key(self, table: str, key: object):
        self.calls += 1
        raise RuntimeError("secret-detail-do-not-leak")

    def get_all(self, table: str):
        self.calls += 1
        raise RuntimeError("secret-detail-do-not-leak")


def user_id(role: str) -> str:
    return f"U_{role}"


def build_permissions() -> tuple[PermissionService, InMemoryPermissionRepository, InMemoryUserRepository]:
    users = InMemoryUserRepository(
        [UserRecord(userid=user_id(r), username=f"user_{r.lower()}", role=r, password_hash="x") for r in ROLES]
        + [UserRecord(userid="U_INACTIVE", username="inactive", role="SUPPLIER", password_hash="x", active=False)]
    )
    perms = InMemoryPermissionRepository()
    for role in ROLES:
        for f in FUNCTIONS:
            perms.put(role_subject(role), resource_key(FUNCTION, f), True, "test")
        for t in PERM_TABLES:
            perms.put(role_subject(role), resource_key(TABLE, t), True, "test")
    return PermissionService(users, perms), perms, users


class FakeToolContext:
    def __init__(self, userid: Any = None, **extra: Any) -> None:
        self.invocation_state = {} if userid is None else {"userid": userid}
        self.invocation_state.update(extra)


# ---------------------------------------------------------------- output inspection
def walk(obj: Any):
    """Yield (path, key_or_None, value) for every node."""
    stack = [("$", None, obj)]
    while stack:
        path, key, v = stack.pop()
        yield path, key, v
        if isinstance(v, dict):
            stack.extend((f"{path}.{k}", k, x) for k, x in v.items())
        elif isinstance(v, (list, tuple)):
            stack.extend((f"{path}[{i}]", None, x) for i, x in enumerate(v))


_DOT_ZERO = re.compile(r"^\d+\.0$")
FORBIDDEN_KEYS = {"role_user", "permissions", "password", "password_hash", "username", "userid", "role"}


def leak_problems(out: dict, secrets: set[str]) -> list[str]:
    """*_parsed keys, raw JSON columns/strings, auth data, float '.0' artifacts."""
    problems = []
    for path, key, v in walk(out):
        if isinstance(key, str):
            k = key.lower()
            if k.endswith("_parsed"):
                problems.append(f"parsed key {path}")
            if key in JSON_COLUMNS.values() and path.startswith("$.rows["):
                problems.append(f"raw json column {path}")
            if k in FORBIDDEN_KEYS:
                problems.append(f"auth key {path}")
        if isinstance(v, float) and v == int(v):
            problems.append(f"float artifact {path}={v!r}")
        if isinstance(v, str):
            if _DOT_ZERO.match(v):
                problems.append(f".0 string {path}={v!r}")
            if v.lstrip().startswith(("{", "[")):
                problems.append(f"raw json string {path}")
            if v in secrets:
                problems.append(f"auth value {path}")
    return problems


def auth_secrets() -> set[str]:
    """Passwords from role_user (never printed) to detect leaks by exact value."""
    wb = read_workbook(EXCEL)
    return {str(r["Password"]) for r in wb.auth_sheets["role_user"] if r.get("Password")}


# ---------------------------------------------------------------- independent expectations
def expected_q1(shipment: str) -> list[dict]:
    out = []
    for r in raw("question1"):
        if r["shipment_id"] == shipment:
            p = json.loads(r["question1"])
            out.append({"shipment_id": shipment, **{k: p.get(k) for k in ("Arac_Konum", "Tofas_Eta_Tarihi", "Kalan_Stop_Adet")}})
    return out


def expected_q2(material: str) -> list[dict]:
    cols = ("shipment_id", "quantity", "tofas_etadate", "supplier_code", "mip")
    return [{c: r.get(c) for c in cols} for r in raw("question2") if r["materialno"] == material]


def expected_q3(shipment: str) -> list[dict]:
    rows = [dict(r) for r in raw("question3") if r["shipment_id"] == shipment]
    return sorted(rows, key=lambda r: int(r["stop_sequence"]))


def expected_q4() -> list[dict]:
    out = []
    for r in raw("question4"):
        item = {"shipment_id": r["shipment_id"], "delay_minutes": int(round(float(r["delay_time"])))}
        for k, v in json.loads(r["question4"]).items():
            item.setdefault(k, v)
        out.append(item)
    return out


def expected_q5() -> list[dict]:
    return [{k: v for k, v in r.items() if k != "question5"} for r in raw("question5")]


def expected_critical(mip: str) -> list[dict]:
    return [dict(r) for r in raw("critical") if r["mip"] == mip]
