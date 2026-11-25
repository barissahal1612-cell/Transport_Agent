"""Helpers for the data-source E2E tests (task 12.1). No AWS access."""
from __future__ import annotations

import glob
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
AGENT_DIR = PROJECT / "app" / "agent"
SCRIPTS_DIR = PROJECT / "scripts"
STREAMLIT_DIR = PROJECT / "streamlit_client"
EXCEL_PATH = PROJECT / "Data" / "Agent_AWS_2026-11-24.xlsx"

# Operational reference date of the data set (not the system clock).
REFERENCE_DATE = "2026-11-24"

EXPECTED_ROWS = {
    "question1": 46, "question2": 122, "question3": 199, "question4": 13, "question5": 9,
    "critical": 131, "summary_df": 5, "role_user": 166, "permissions": 52, "Functions": 6,
}
OPERATIONAL_TABLES = ("question1", "question2", "question3", "question4", "question5", "summary_df", "critical")
JSON_COLUMNS = {"question1": "question1", "question2": "question2", "question4": "question4", "question5": "question5"}
AUTH_SHEETS = ("role_user", "permissions")
FN_TABLE = {
    "get_truck_location": "question1", "get_material_truck_allocation": "question2",
    "get_truck_route_info": "question3", "get_delayed_truck": "question4",
    "get_truck_tobearrived": "question5", "get_critical_part_status": "critical",
}


def _ensure_paths() -> None:
    for p in (AGENT_DIR, SCRIPTS_DIR, STREAMLIT_DIR):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        # openpyxl lives only in scripts/.venv (kept out of the runtime deps on purpose).
        for sp in glob.glob(str(SCRIPTS_DIR / ".venv" / "lib" / "python*" / "site-packages")):
            sys.path.append(sp)


_ensure_paths()


def openpyxl_available() -> bool:
    try:
        import openpyxl  # noqa: F401
        return True
    except ImportError:
        return False


def load_workbook(path: Path = EXCEL_PATH):
    from ingest.excel_reader import read_workbook
    return read_workbook(path)


def build_repo_rows(wb, inject_bad: dict[str, list[int]] | None = None):
    """Mirror scripts/ingest/loader.build_items: data dict per row + '<col>_parsed'.

    Returns (rows_by_table, skipped) where skipped = [(sheet, excel_row, error)].
    """
    from logistic_ai_data.json_safe import safe_json_loads

    rows_by_table: dict[str, list[dict]] = {}
    skipped: list[tuple[str, int, str]] = []
    for table in OPERATIONAL_TABLES:
        out = []
        jcol = JSON_COLUMNS.get(table)
        for idx, row in enumerate(wb.sheets[table]):
            data = dict(row)
            if jcol is not None:
                if inject_bad and idx in inject_bad.get(table, []):
                    data[jcol] = "{not json"
                parsed, err = safe_json_loads(data.get(jcol))
                if err is not None:
                    skipped.append((table, idx + 2, err))
                    continue
                data[f"{jcol}_parsed"] = parsed
            out.append(data)
        rows_by_table[table] = out
    return rows_by_table, skipped


def build_repo(wb, **kw):
    from logistic_ai_data.in_memory import InMemoryDataRepository
    rows, skipped = build_repo_rows(wb, **kw)
    return InMemoryDataRepository(rows), skipped


def build_tool_env(repo, role: str = "TRANSPORT_OFFICE"):
    """Wire the guard runtime with in-memory users/permissions.

    Returns (tools_by_name, tool_context_stub).
    """
    from types import SimpleNamespace

    from agent_factory import build_runtime
    from logistic_ai_shared_auth.auth.users import InMemoryUserRepository, UserRecord
    from logistic_ai_shared_auth.authorization.permission_store import (
        InMemoryPermissionRepository, resource_key, role_subject)
    from tools.logistics_tools import ALL_TOOLS

    users = InMemoryUserRepository([UserRecord("U1", "tester", role, "h", active=True)])
    perms = InMemoryPermissionRepository()
    for fn, tbl in FN_TABLE.items():
        perms.put(role_subject(role), resource_key("FUNCTION", fn), True, "t")
        perms.put(role_subject(role), resource_key("TABLE", tbl), True, "t")
    build_runtime(data_repo=repo, user_repo=users, permission_repo=perms)
    ctx = SimpleNamespace(invocation_state={"userid": "U1"})
    return {t.tool_name: t for t in ALL_TOOLS}, ctx
