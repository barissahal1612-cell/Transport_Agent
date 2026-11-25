"""E2E data-source checks against the real Excel (task 12.1). Local only, no AWS.

Check ids DS-01 .. DS-12 are referenced by the test report.
Operational reference date: 2026-11-24 (see support_data.REFERENCE_DATE); delays come from the data,
never from the system clock.
"""
from __future__ import annotations

import ast
import datetime as real_dt
import inspect
import json
import re
import sys
import time as real_time
from pathlib import Path

import pytest

import support_data as sd  # tests/e2e is on sys.path (rootdir/prepend import mode)

pytestmark = pytest.mark.skipif(
    not sd.EXCEL_PATH.exists(), reason=f"Real Excel not found: {sd.EXCEL_PATH} (Data/*.xlsx is not versioned)"
)

EXPECTED_COLUMNS = {
    "question1": ["shipment_id", "question1"],
    "question2": ["tofas_etadate", "supplier_code", "shipment_id", "materialno", "quantity", "mip", "question2"],
    "question3": ["shipment_id", "stop_sequence", "supplier_name", "estimated_arrival", "estimated_departure",
                  "location_explanation", "laststop_explanation", "location_text"],
    "question4": ["shipment_id", "delay_time", "question4"],
    "question5": ["shipment_id", "tofas_etadate", "eta_diff_min", "driver_name", "driver_phone", "question5"],
    "summary_df": ["Durum", "Adet"],
    "critical": ["shipment_id", "Arac_Konum", "Tofas_Eta_Tarihi", "Kalan_Stop_Adet", "Gecikme_Suresi",
                 "supplier_code", "materialno", "quantity", "mip", "KrtiklikZaman", "KritikStatu"],
    "Functions": ["TableName", "Tablo Veri Açıklama", "Fonksiyon", "Keyid", "Keyiid_explanation"],
}
Q1_KEYS = {"Arac_Konum", "Tofas_Eta_Tarihi", "Kalan_Stop_Adet"}
EXPECTED_JSON_KEYS = {
    "question1": Q1_KEYS,
    "question2": {"Malzeme no", "Seferle"},
    "question4": Q1_KEYS | {"Gecikme_Suresi"},
    "question5": {"shipment_id", "tofas_etadate", "eta_diff_min", "driver_name", "driver_phone"},
}
FROZEN_DATES = ("2030-01-01", "2020-01-01")


@pytest.fixture(scope="module")
def wb():
    if not sd.openpyxl_available():
        pytest.skip("openpyxl not importable (only installed in scripts/.venv)")
    return sd.load_workbook()


@pytest.fixture(scope="module")
def repo_rows(wb):
    return sd.build_repo_rows(wb)


@pytest.fixture(scope="module")
def repo(wb):
    return sd.build_repo(wb)[0]


# ---------------------------------------------------------------- DS-01 .. DS-03
def test_ds01_row_counts(wb):
    actual = {n: len(r) for n, r in {**wb.sheets, **wb.auth_sheets}.items()}
    assert actual == sd.EXPECTED_ROWS
    assert wb.report.issues == []


def test_ds02_column_names_preserved(wb):
    for sheet, cols in EXPECTED_COLUMNS.items():
        assert wb.columns[sheet] == cols, sheet
        for row in wb.sheets[sheet]:
            assert list(row.keys()) == cols, sheet
    assert wb.columns["role_user"] and wb.columns["permissions"]


def test_ds03_auth_sheets_never_in_repo(wb, repo):
    from logistic_ai_data.repository import TABLES, UnknownTableError
    assert not set(sd.AUTH_SHEETS) & set(wb.sheets)
    assert not set(sd.AUTH_SHEETS) & set(TABLES)
    for name in sd.AUTH_SHEETS:
        with pytest.raises(UnknownTableError):
            repo.get_all(name)
    # real loader (dry-run) must not load auth sheets/Functions either
    from ingest.loader import LOAD_SHEETS, load_workbook_data
    assert not (set(sd.AUTH_SHEETS) | {"Functions"}) & set(LOAD_SHEETS)
    report = load_workbook_data(wb, apply=False)
    assert not report.applied
    # no password-like column leaked into any repo row
    for table in sd.OPERATIONAL_TABLES:
        for row in repo.get_all(table):
            assert not {k for k in row if "password" in k.lower() or k in ("USERID", "USERNAME")}


# ---------------------------------------------------------------- DS-04 Functions mapping
def test_ds04_functions_sheet_matches_code(wb):
    from logistic_ai_data.repository import KEY_COLUMNS
    from tools.logistics_tools import ALL_TOOLS

    tools = {t.tool_name: t for t in ALL_TOOLS}
    mapping = {}
    for r in wb.sheets["Functions"]:
        fn = r["Fonksiyon"].strip()
        assert fn.endswith("()")
        mapping[fn[:-2]] = (r["TableName"], r["Keyid"])
    assert set(mapping) == set(tools) == set(sd.FN_TABLE)
    for fn, (table, keyid) in mapping.items():
        assert sd.FN_TABLE[fn] == table, fn
        params = [p for p in tools[fn].tool_spec["inputSchema"]["json"].get("properties", {})]
        if keyid is None:
            assert params == [], fn
            assert table not in KEY_COLUMNS, fn
        else:
            assert params == [keyid], fn
            assert KEY_COLUMNS[table] == keyid, fn
    # every key column exists in the sheet columns
    for table, col in KEY_COLUMNS.items():
        assert col in wb.columns[table]


# ---------------------------------------------------------------- DS-05 JSON columns
def test_ds05_json_columns_parse_and_keys(repo_rows):
    rows, skipped = repo_rows
    assert skipped == []
    for table, jcol in sd.JSON_COLUMNS.items():
        for r in rows[table]:
            parsed = r[f"{jcol}_parsed"]
            assert isinstance(parsed, dict), table
            assert EXPECTED_JSON_KEYS[table] <= set(parsed), (table, set(parsed))
    # question2 JSON consistent with columns
    for r in rows["question2"]:
        p = r["question2_parsed"]
        assert p["Malzeme no"] == r["materialno"]
        assert r["shipment_id"] in {e["seferno"] for e in p["Seferle"]}
    # question4 delay_time agrees with JSON 'Gecikme_Suresi'
    for r in rows["question4"]:
        assert f"{int(r['delay_time'])} dk" == r["question4_parsed"]["Gecikme_Suresi"]


# ---------------------------------------------------------------- DS-06 key strings
def test_ds06_keys_are_strings_without_dot_zero(wb):
    key_cols = ("shipment_id", "materialno", "supplier_code", "mip")
    for sheet, rows in wb.sheets.items():
        for r in rows:
            for c in key_cols:
                if c in r and r[c] is not None:
                    assert isinstance(r[c], str), (sheet, c, r[c])
                    assert not re.fullmatch(r"\d+\.0", r[c]), (sheet, c, r[c])
    mats = {r["materialno"] for r in wb.sheets["question2"]}
    assert "07358034660E" in mats
    leading = [m for m in mats if m.startswith("0")]
    assert leading
    sup = [r["supplier_code"] for r in wb.sheets["question2"] + wb.sheets["critical"]]
    assert all(isinstance(s, str) and s for s in sup)
    # a stored key must round-trip through the repo lookup (leading zero preserved)
    from logistic_ai_data.in_memory import InMemoryDataRepository
    rows, _ = sd.build_repo_rows(wb)
    repo = InMemoryDataRepository(rows)
    assert repo.get_by_key("question2", "07358034660E")
    assert repo.get_by_key("question2", "7358034660E") == []
    mip = wb.sheets["critical"][0]["mip"]
    assert repo.get_by_key("critical", mip)
    assert repo.get_by_key("critical", f"{mip}.0") == []


# ---------------------------------------------------------------- DS-07 bad JSON injection
def test_ds07_bad_json_injection_does_not_crash(wb):
    from ingest.loader import build_items
    from ingest.report import IngestReport

    # (a) real loader: corrupt 1 row each in question1/2/4/5
    sheets = {n: [dict(r) for r in rows] for n, rows in wb.sheets.items()}
    for t in sd.JSON_COLUMNS:
        sheets[t][0][sd.JSON_COLUMNS[t]] = "{broken json"
    report = IngestReport(applied=False, load_id="t")
    items = build_items({k: v for k, v in sheets.items() if k in sd.OPERATIONAL_TABLES}, "t", report)
    for t in sd.JSON_COLUMNS:
        assert len(items[t]) == sd.EXPECTED_ROWS[t] - 1, t
        assert report.counts(t).read == sd.EXPECTED_ROWS[t]
    assert json.dumps(report.__dict__, default=str).count("broken json") == 0
    # (b) repo-level + tools do not crash
    repo, skipped = sd.build_repo(wb, inject_bad={t: [0] for t in sd.JSON_COLUMNS})
    assert {s[0] for s in skipped} == set(sd.JSON_COLUMNS)
    assert all(s[2] == "invalid_json" and s[1] == 2 for s in skipped)
    tools, ctx = sd.build_tool_env(repo)
    for name, args in (("get_delayed_truck", {}), ("get_truck_tobearrived", {}),
                       ("get_truck_location", {"shipment_id": wb.sheets["question1"][0]["shipment_id"]}),
                       ("get_material_truck_allocation", {"materialno": "07358034660E"})):
        out = tools[name](tool_context=ctx, **args)
        assert out["status"] in {"ok", "not_found"}, (name, out)
    assert tools["get_truck_location"](shipment_id=wb.sheets["question1"][0]["shipment_id"],
                                       tool_context=ctx)["status"] == "not_found"
    # non-JSON garbage types never raise
    from logistic_ai_data.json_safe import safe_json_loads
    for bad in (None, "", "   ", "{", "[1,", 5, 1.5, b"\xff", object(), "123", "null"):
        assert safe_json_loads(bad)[0] is None


# ---------------------------------------------------------------- clock helpers
def _freeze(monkeypatch, iso_date: str):
    frozen = real_dt.datetime.fromisoformat(iso_date + "T12:00:00+00:00")

    class FrozenDatetime(real_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return frozen.replace(tzinfo=None)

    class FrozenDate(real_dt.date):
        @classmethod
        def today(cls):
            return frozen.date()

    monkeypatch.setattr(real_time, "time", lambda: frozen.timestamp())
    for mod_name in ("tools.logistics_tools", "tools.guard", "logistic_ai.dashboard.kpi",
                     "logistic_ai_shared_auth.common.clock", "logistic_ai_shared_auth.common.audit",
                     "logistic_ai_shared_auth.authorization.permission_service",
                     "logistic_ai_shared_auth.authorization.permission_store"):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        if getattr(mod, "datetime", None) is real_dt.datetime:
            monkeypatch.setattr(mod, "datetime", FrozenDatetime)
        if getattr(mod, "date", None) is real_dt.date:
            monkeypatch.setattr(mod, "date", FrozenDate)
    monkeypatch.setattr(real_dt, "datetime", FrozenDatetime)
    monkeypatch.setattr(real_dt, "date", FrozenDate)
    assert FrozenDatetime.now(real_dt.timezone.utc).year == frozen.year


def _snapshot(wb):
    """Outputs of the clock-sensitive-looking functions + dashboard KPIs."""
    from logistic_ai.dashboard.kpi import load_kpis

    repo = sd.build_repo(wb)[0]
    tools, ctx = sd.build_tool_env(repo)
    crit_mips = sorted({r["mip"] for r in wb.sheets["critical"]})
    snap = {
        "delayed": tools["get_delayed_truck"](tool_context=ctx),
        "tobearrived": tools["get_truck_tobearrived"](tool_context=ctx),
        "critical": {m: tools["get_critical_part_status"](mip=m, tool_context=ctx) for m in crit_mips},
        "kpis": load_kpis(repo),
    }
    return json.dumps(snap, sort_keys=True, default=str)


# ---------------------------------------------------------------- DS-08 reference date
def test_ds08_reference_date_is_data_date(wb):
    ref = sd.REFERENCE_DATE
    assert ref == "2026-11-24"
    assert re.search(r"2026-11-24", sd.EXCEL_PATH.name.replace("_", "-"))
    etas = [r["Tofas_Eta_Tarihi"] for r in wb.sheets["critical"]] + \
           [r["tofas_etadate"] for r in wb.sheets["question5"]]
    assert all(str(e).startswith(ref) for e in etas if e)


# ---------------------------------------------------------------- DS-09 clock independence
def test_ds09_outputs_independent_of_system_clock(wb, monkeypatch):
    results = {}
    for d in FROZEN_DATES:
        with monkeypatch.context() as m:
            _freeze(m, d)
            results[d] = _snapshot(wb)
    assert results["2030-01-01"] == results["2020-01-01"]
    assert results["2030-01-01"] == _snapshot(wb)  # also equal to the real clock
    snap = json.loads(results["2030-01-01"])
    assert snap["delayed"]["status"] == "ok" and snap["delayed"]["count"] == 13
    assert snap["critical"] and all(v["status"] == "ok" for v in snap["critical"].values())


def test_ds09b_delay_values_come_from_data_not_clock(wb, repo, monkeypatch):
    tools, ctx = sd.build_tool_env(repo)
    expected = {r["shipment_id"]: int(round(float(r["delay_time"]))) for r in wb.sheets["question4"]}
    for d in FROZEN_DATES:
        with monkeypatch.context() as m:
            _freeze(m, d)
            out = tools["get_delayed_truck"](tool_context=ctx)
            assert {r["shipment_id"]: r["delay_minutes"] for r in out["rows"]} == expected


# ---------------------------------------------------------------- DS-10 static clock scan
CLOCK_CALLS = {"datetime.now", "datetime.utcnow", "date.today", "time.time", "datetime.datetime.now",
               "datetime.date.today", "datetime.datetime.utcnow", "time.monotonic"}
# Files whose clock use is token expiry / lockout / audit / TTL, not delay derivation.
CLOCK_ALLOWED = {
    "logistic_ai_shared_auth/common/clock.py", "logistic_ai_shared_auth/common/audit.py",
    "logistic_ai_shared_auth/common/errors.py", "logistic_ai_shared_auth/authorization/permission_store.py",
    "logistic_ai_shared_auth/authorization/admin_service.py", "logistic_ai_shared_auth/auth/session_token.py",
    "logistic_ai_shared_auth/auth/lockout.py", "logistic_ai_shared_auth/auth/user_auth_service.py",
    "logistic_ai/session/agentcore_client.py",
}
DELAY_FILES = ("tools/logistics_tools.py", "tools/guard.py", "dashboard/kpi.py", "logistic_ai_data/",
               "ui/dashboard.py", "main.py", "agent_factory.py")


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _clock_calls():
    found = []
    for base in (sd.AGENT_DIR, sd.STREAMLIT_DIR):
        for p in base.rglob("*.py"):
            rel = p.relative_to(base).as_posix()
            if any(x in p.parts for x in (".venv", "tests", "__pycache__", "node_modules", "cdk")):
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Call):
                    name = _dotted(n.func)
                    if name in CLOCK_CALLS or name.endswith((".now", ".utcnow", ".today")) and "clock" not in name.lower():
                        found.append((rel, n.lineno, name))
    return found


def test_ds10_no_clock_used_for_delay_derivation():
    found = _clock_calls()
    offenders = [f for f in found if f[0] not in CLOCK_ALLOWED]
    assert offenders == [], f"clock used outside token/audit/lockout code: {offenders}"
    for rel, _, _ in found:
        assert not any(rel.startswith(d) or rel.endswith(d) for d in DELAY_FILES), rel


# ---------------------------------------------------------------- DS-11 dashboard vs summary_df
def test_ds11_dashboard_kpis_match_summary_df(wb, repo):
    from logistic_ai.dashboard.kpi import load_kpis
    summary = {r["Durum"]: r["Adet"] for r in wb.sheets["summary_df"]}
    k = load_kpis(repo)
    assert (k.total, k.delayed, k.completed, k.in_progress) == (
        summary["Tüm Seferler"], summary["Geciken Seferler"],
        summary["Tamamlanan Seferler"], summary["Devam Eden Seferler"])
    assert k.delay_rate_pct == pytest.approx(k.delayed / k.total * 100)
    assert k.total == len(wb.sheets["question1"]) == 46
    assert k.delayed == len(wb.sheets["question4"]) == 13


# ---------------------------------------------------------------- DS-12 tools on real data
def test_ds12_tools_return_real_rows(wb, repo):
    tools, ctx = sd.build_tool_env(repo)
    sid = wb.sheets["question3"][0]["shipment_id"]
    out = tools["get_truck_route_info"](shipment_id=sid, tool_context=ctx)
    seq = [int(r["stop_sequence"]) for r in out["rows"]]
    assert out["status"] == "ok" and seq == sorted(seq)
    assert seq and len(seq) == sum(1 for r in wb.sheets["question3"] if r["shipment_id"] == sid)
    out = tools["get_material_truck_allocation"](materialno="07358034660E", tool_context=ctx)
    assert out["status"] == "ok" and all(r["supplier_code"] for r in out["rows"])
    assert tools["get_truck_location"](shipment_id="", tool_context=ctx)["status"] == "missing_parameter"
    assert tools["get_truck_location"](shipment_id="NOPE", tool_context=ctx)["status"] == "not_found"
