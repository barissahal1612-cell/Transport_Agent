"""E2E tool tests (task 12.3): real @tool functions + real Excel, no LLM, no AWS.

Check ids are in the test names (T-<group>-<nn>) so the report table can be generated from -v output.
"""
from __future__ import annotations

import json

import pytest

try:
    from . import support_tools as st
except ImportError:  # no package: tests/e2e is on sys.path (rootdir/prepend mode)
    import support_tools as st

from logistic_ai_data.in_memory import InMemoryDataRepository
from logistic_ai_shared_auth.authorization.permission_store import resource_key, role_subject, user_subject
from logistic_ai_shared_auth.authorization.resources import FUNCTION, TABLE
from tools import guard
from tools import logistics_tools as lt

TOOLS = {
    "get_truck_location": lt.get_truck_location,
    "get_material_truck_allocation": lt.get_material_truck_allocation,
    "get_truck_route_info": lt.get_truck_route_info,
    "get_delayed_truck": lt.get_delayed_truck,
    "get_truck_tobearrived": lt.get_truck_tobearrived,
    "get_critical_part_status": lt.get_critical_part_status,
}
KEYED = ["get_truck_location", "get_material_truck_allocation", "get_truck_route_info", "get_critical_part_status"]
KEYLESS = ["get_delayed_truck", "get_truck_tobearrived"]
SAMPLE_KEY = {  # a real key per keyed tool, from the raw sheet
    "get_truck_location": lambda: st.raw("question1")[0]["shipment_id"],
    "get_material_truck_allocation": lambda: st.raw("question2")[0]["materialno"],
    "get_truck_route_info": lambda: st.raw("question3")[0]["shipment_id"],
    "get_critical_part_status": lambda: st.raw("critical")[0]["mip"],
}
ADMIN = st.user_id("ADMIN")
TRANSPORT = st.user_id("TRANSPORT_OFFICE")


@pytest.fixture(scope="module")
def repo_rows():
    return st.build_repo_rows()


@pytest.fixture(scope="module")
def secrets():
    return st.auth_secrets()


@pytest.fixture()
def env(repo_rows):
    """(spy repo, permission service, permission repo); wired into tools.guard for the test."""
    spy = st.SpyRepo(InMemoryDataRepository(repo_rows))
    svc, perms, users = st.build_permissions()
    prev = (guard.get_runtime().data_repo, guard.get_runtime().permission_service)
    guard.set_runtime(spy, svc)
    yield spy, svc, perms
    guard.set_runtime(*prev)


def call(name: str, userid, *args, **extra):
    ctx = st.FakeToolContext(userid, **extra)
    return TOOLS[name](*args, tool_context=ctx)


def key_of(name: str) -> str:
    return SAMPLE_KEY[name]()


# ------------------------------------------------------------------ T-OK: correct parameter
def test_T_OK_01_q1_every_shipment_matches_raw_json(env):
    spy, _, _ = env
    for r in st.raw("question1"):
        out = call("get_truck_location", ADMIN, r["shipment_id"])
        assert out["status"] == "ok" and out["count"] == 1
        assert out["rows"] == st.expected_q1(r["shipment_id"]), r["shipment_id"]


def test_T_OK_02_q2_every_material_matches_raw_rows(env):
    mats = sorted({r["materialno"] for r in st.raw("question2")})
    assert len(mats) > 100
    for m in mats:
        out = call("get_material_truck_allocation", ADMIN, m)
        exp = st.expected_q2(m)
        assert out["status"] == "ok" and out["count"] == len(exp), m
        assert sorted(out["rows"], key=json.dumps) == sorted(exp, key=json.dumps), m


def test_T_OK_03_q3_every_shipment_matches_raw_rows_in_stop_order(env):
    ships = sorted({r["shipment_id"] for r in st.raw("question3")})
    assert len(ships) == 46
    for s in ships:
        out = call("get_truck_route_info", ADMIN, s)
        assert out["status"] == "ok"
        assert out["rows"] == st.expected_q3(s), s


def test_T_OK_04_critical_every_mip_matches_raw_rows(env):
    mips = sorted({r["mip"] for r in st.raw("critical")})
    assert len(mips) >= 5
    for m in mips:
        out = call("get_critical_part_status", ADMIN, m)
        exp = st.expected_critical(m)
        assert out["status"] == "ok" and out["count"] == len(exp), m
        assert sorted(out["rows"], key=json.dumps) == sorted(exp, key=json.dumps), m


def test_T_OK_05_keyless_delayed_returns_whole_table_13_rows(env):
    out = call("get_delayed_truck", ADMIN)
    assert out["status"] == "ok" and out["count"] == 13 == len(st.raw("question4"))
    assert out["rows"] == st.expected_q4()


def test_T_OK_06_keyless_tobearrived_returns_whole_table_9_rows(env):
    out = call("get_truck_tobearrived", ADMIN)
    assert out["status"] == "ok" and out["count"] == 9 == len(st.raw("question5"))
    assert out["rows"] == st.expected_q5()


@pytest.mark.parametrize("role", st.ROLES)
def test_T_OK_07_all_six_tools_work_for_each_role(env, role):
    uid = st.user_id(role)
    for name in KEYED:
        assert call(name, uid, key_of(name))["status"] == "ok", (role, name)
    for name in KEYLESS:
        assert call(name, uid)["status"] == "ok", (role, name)


def test_T_OK_08_delay_is_whole_minutes_equal_to_raw_delay_time(env):
    out = call("get_delayed_truck", ADMIN)
    raw = {r["shipment_id"]: r["delay_time"] for r in st.raw("question4")}
    assert {r["shipment_id"]: r["delay_minutes"] for r in out["rows"]} == {k: int(round(float(v))) for k, v in raw.items()}
    assert all(type(r["delay_minutes"]) is int for r in out["rows"])


# ------------------------------------------------------------------ T-WRONG / T-MISS / T-NF
@pytest.mark.parametrize("name", KEYED)
def test_T_WRONG_01_unknown_key_is_not_found_without_data(env, name):
    out = call(name, ADMIN, "XX999")
    assert out["status"] == "not_found" and out["key"] == "XX999"
    assert "rows" not in out


@pytest.mark.parametrize("name", KEYED)
@pytest.mark.parametrize("bad", [None, "", "   ", "\t\n"])
def test_T_MISS_01_missing_key_asks_for_parameter_and_skips_repo(env, name, bad):
    spy, _, _ = env
    out = call(name, ADMIN, bad)
    assert out["status"] == "missing_parameter"
    assert out["parameter"] == {"get_truck_location": "shipment_id", "get_material_truck_allocation": "materialno",
                                "get_truck_route_info": "shipment_id", "get_critical_part_status": "mip"}[name]
    assert spy.calls == []


@pytest.mark.parametrize("name,key", [
    ("get_truck_location", "FA9999999999"),
    ("get_material_truck_allocation", "99999999999Z"),
    ("get_truck_route_info", "MA0000000000"),
    ("get_critical_part_status", "99999"),
])
def test_T_NF_01_well_formed_but_absent_key_is_not_found(env, name, key):
    out = call(name, ADMIN, key)
    assert out["status"] == "not_found"
    assert out["message"] == guard.NOT_FOUND_MESSAGE


def test_T_NF_02_partial_or_substring_keys_do_not_match(env):
    ship = key_of("get_truck_location")
    assert call("get_truck_location", ADMIN, ship[:-1])["status"] == "not_found"
    assert call("get_truck_location", ADMIN, ship[1:])["status"] == "not_found"
    assert call("get_critical_part_status", ADMIN, "4")["status"] == "not_found"


# ------------------------------------------------------------------ T-MULTI: many records
def _pick_multi_material():
    counts = {}
    for r in st.raw("question2"):
        counts[r["materialno"]] = counts.get(r["materialno"], 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])


def test_T_MULTI_01_material_in_several_shipments_returns_every_shipment(env):
    mat, n = _pick_multi_material()
    assert n >= 3
    out = call("get_material_truck_allocation", ADMIN, mat)
    assert out["count"] == n == len(out["rows"])
    exp_ships = sorted(r["shipment_id"] for r in st.raw("question2") if r["materialno"] == mat)
    assert sorted(r["shipment_id"] for r in out["rows"]) == exp_ships
    assert len(set(exp_ships)) >= 2


def test_T_MULTI_02_shipment_with_ten_or_more_stops_all_returned(env):
    counts = {}
    for r in st.raw("question3"):
        counts[r["shipment_id"]] = counts.get(r["shipment_id"], 0) + 1
    ship, n = max(counts.items(), key=lambda kv: kv[1])
    assert n >= 10, "dataset must contain a shipment with >=10 stops"
    out = call("get_truck_route_info", ADMIN, ship)
    assert out["count"] == n
    assert [r["stop_sequence"] for r in out["rows"]] == list(range(1, n + 1))


def test_T_MULTI_03_mip_with_many_critical_rows(env):
    counts = {}
    for r in st.raw("critical"):
        counts[r["mip"]] = counts.get(r["mip"], 0) + 1
    mip, n = max(counts.items(), key=lambda kv: kv[1])
    assert n >= 40
    out = call("get_critical_part_status", ADMIN, mip)
    assert out["count"] == n == len(out["rows"])
    assert {r["mip"] for r in out["rows"]} == {mip}


def test_T_MULTI_04_row_counts_per_key_equal_raw_group_counts(env):
    for tool, sheet, col in [("get_material_truck_allocation", "question2", "materialno"),
                             ("get_truck_route_info", "question3", "shipment_id"),
                             ("get_critical_part_status", "critical", "mip")]:
        keys = {r[col] for r in st.raw(sheet)}
        total = 0
        for k in keys:
            n = call(tool, ADMIN, k)["count"]
            assert n == sum(1 for r in st.raw(sheet) if r[col] == k), (tool, k)
            total += n
        assert total == len(st.raw(sheet))


# ------------------------------------------------------------------ T-SORT: question3 numeric order
@pytest.mark.parametrize("scramble", ["reversed", "string_sorted", "stringified_seq"])
def test_T_SORT_01_stop_sequence_sorted_numerically_even_if_repo_returns_other_order(repo_rows, scramble):
    counts = {}
    for r in st.raw("question3"):
        counts[r["shipment_id"]] = counts.get(r["shipment_id"], 0) + 1
    ship, n = max(counts.items(), key=lambda kv: kv[1])
    assert n >= 10

    def transform(table, rows):
        if table != "question3":
            return rows
        if scramble == "reversed":
            return list(reversed(rows))
        if scramble == "string_sorted":  # the classic bug order: 1,10,2,3...
            return sorted(rows, key=lambda r: str(r["stop_sequence"]))
        return [{**r, "stop_sequence": str(r["stop_sequence"])} for r in reversed(rows)]

    spy = st.SpyRepo(InMemoryDataRepository(repo_rows), transform)
    svc, _, _ = st.build_permissions()
    prev = (guard.get_runtime().data_repo, guard.get_runtime().permission_service)
    guard.set_runtime(spy, svc)
    try:
        out = call("get_truck_route_info", ADMIN, ship)
    finally:
        guard.set_runtime(*prev)
    assert [int(r["stop_sequence"]) for r in out["rows"]] == list(range(1, n + 1))
    if scramble == "string_sorted":
        assert [int(r["stop_sequence"]) for r in spy.inner.get_by_key("question3", ship)] == list(range(1, n + 1))


def test_T_SORT_02_string_sort_would_differ_for_the_ten_stop_shipment():
    """Guards the test data itself: a string sort of 1..10 is not the numeric order."""
    assert sorted(map(str, range(1, 11))) != list(map(str, range(1, 11)))


# ------------------------------------------------------------------ T-KEY: key fidelity
def test_T_KEY_01_leading_zero_and_trailing_letter_preserved(env):
    mats = [r["materialno"] for r in st.raw("question2") if r["materialno"].startswith("0") and r["materialno"][-1].isalpha()]
    assert mats
    mat = mats[0]
    out = call("get_material_truck_allocation", ADMIN, mat)
    assert out["status"] == "ok"
    # variants that drop the zero or the letter must not match
    assert call("get_material_truck_allocation", ADMIN, mat.lstrip("0"))["status"] == "not_found"
    assert call("get_material_truck_allocation", ADMIN, mat[:-1])["status"] == "not_found"


def test_T_KEY_02_supplier_code_and_mip_are_strings_in_output(env):
    out = call("get_material_truck_allocation", ADMIN, st.raw("question2")[0]["materialno"])
    assert all(isinstance(r["supplier_code"], str) and isinstance(r["mip"], str) for r in out["rows"])
    exp = {(r["shipment_id"], r["supplier_code"], r["mip"]) for r in st.expected_q2(st.raw("question2")[0]["materialno"])}
    assert {(r["shipment_id"], r["supplier_code"], r["mip"]) for r in out["rows"]} == exp
    crit = call("get_critical_part_status", ADMIN, "47")
    assert all(isinstance(r["mip"], str) and r["mip"] == "47" for r in crit["rows"])


def test_T_KEY_03_numeric_mip_lookup_has_no_dot_zero_artifact(env):
    assert call("get_critical_part_status", ADMIN, 47.0)["count"] == call("get_critical_part_status", ADMIN, "47")["count"]
    assert call("get_critical_part_status", ADMIN, "47.0")["status"] == "not_found"
    assert call("get_critical_part_status", ADMIN, "047")["status"] == "not_found"


@pytest.mark.parametrize("variant", ["lower", "padded", "lower_padded", "tabs"])
def test_T_KEY_04_case_and_whitespace_insensitive_match(env, variant):
    f = {"lower": str.lower, "padded": lambda s: f"  {s} ", "lower_padded": lambda s: f" {s.lower()}\t",
         "tabs": lambda s: f"\t{s}\n"}[variant]
    for name in ("get_truck_location", "get_material_truck_allocation", "get_truck_route_info"):
        k = key_of(name)
        base = call(name, ADMIN, k)
        got = call(name, ADMIN, f(k))
        assert got["status"] == "ok" and got["rows"] == base["rows"], (name, variant)


def test_T_KEY_05_not_found_echoes_trimmed_key_only(env):
    out = call("get_truck_location", ADMIN, "  xx999 ")
    assert out["status"] == "not_found" and out["key"] == "xx999"


def test_T_KEY_06_trailing_letter_materials_distinct_by_letter(env):
    # a material and the same digits with another trailing letter are different keys
    mat = "07358034660E"
    assert call("get_material_truck_allocation", ADMIN, mat)["status"] == "ok"
    assert call("get_material_truck_allocation", ADMIN, mat[:-1] + "F")["status"] == "not_found"


# ------------------------------------------------------------------ T-AUTHZ: unauthorized
def _all_call_args(name):
    return [] if name in KEYLESS else [key_of(name)]


@pytest.mark.parametrize("name", list(TOOLS))
def test_T_AUTHZ_01_function_permission_removed_is_forbidden_and_repo_untouched(env, name):
    spy, svc, perms = env
    assert call(name, TRANSPORT, *_all_call_args(name))["status"] == "ok"
    spy.calls.clear()
    perms.delete(role_subject("TRANSPORT_OFFICE"), resource_key(FUNCTION, name))
    svc.invalidate()
    out = call(name, TRANSPORT, *_all_call_args(name))
    assert out == {"status": "forbidden", "message": guard.FORBIDDEN_MESSAGE}
    assert spy.calls == []


@pytest.mark.parametrize("name", list(TOOLS))
def test_T_AUTHZ_02_table_permission_removed_is_forbidden_and_repo_untouched(env, name):
    spy, svc, perms = env
    perms.delete(role_subject("SUPPLIER"), resource_key(TABLE, st.FUNCTION_TABLE[name]))
    svc.invalidate()
    out = call(name, st.user_id("SUPPLIER"), *_all_call_args(name))
    assert out["status"] == "forbidden" and spy.calls == []


def test_T_AUTHZ_03_removal_affects_only_that_function_and_restore_works(env):
    spy, svc, perms = env
    sub = role_subject("MATERIAL_RESPONSIBLE")
    uid = st.user_id("MATERIAL_RESPONSIBLE")
    perms.delete(sub, resource_key(FUNCTION, "get_delayed_truck"))
    svc.invalidate()
    assert call("get_delayed_truck", uid)["status"] == "forbidden"
    assert call("get_truck_tobearrived", uid)["status"] == "ok"
    perms.put(sub, resource_key(FUNCTION, "get_delayed_truck"), True, "test")
    svc.invalidate()
    assert call("get_delayed_truck", uid)["status"] == "ok"


def test_T_AUTHZ_04_user_level_deny_overrides_role_allow(env):
    spy, svc, perms = env
    perms.put(user_subject(TRANSPORT), resource_key(FUNCTION, "get_truck_location"), False, "test")
    svc.invalidate()
    spy.calls.clear()
    assert call("get_truck_location", TRANSPORT, key_of("get_truck_location"))["status"] == "forbidden"
    assert spy.calls == []
    assert call("get_truck_location", ADMIN, key_of("get_truck_location"))["status"] == "ok"


@pytest.mark.parametrize("uid", ["U_INACTIVE", "NO_SUCH_USER", "", "   ", None])
def test_T_AUTHZ_05_inactive_unknown_or_missing_identity_is_forbidden(env, uid):
    spy, _, _ = env
    out = call("get_delayed_truck", uid)
    assert out["status"] == "forbidden" and spy.calls == []


def test_T_AUTHZ_06_userid_is_taken_only_from_invocation_state_not_from_parameters(env):
    spy, _, _ = env
    # an allowed id smuggled in another invocation_state field or as the tool key is ignored
    ctx = st.FakeToolContext(None, user="U_ADMIN", username="user_admin", role="ADMIN")
    out = lt.get_delayed_truck(tool_context=ctx)
    assert out["status"] == "forbidden" and spy.calls == []
    out = lt.get_truck_location(ADMIN, tool_context=st.FakeToolContext("U_INACTIVE"))
    assert out["status"] == "forbidden" and spy.calls == []


def test_T_AUTHZ_07_all_permissions_removed_for_a_role_blocks_all_six_tools(env):
    spy, svc, perms = env
    for e in perms.list_for_subject(role_subject("SUPPLIER")):
        perms.delete(e.subject, e.resource)
    svc.invalidate()
    for name in TOOLS:
        assert call(name, st.user_id("SUPPLIER"), *_all_call_args(name))["status"] == "forbidden"
    assert spy.calls == []


def test_T_AUTHZ_08_missing_param_is_reported_before_data_access_for_authorised_user(env):
    spy, _, _ = env
    assert call("get_truck_location", ADMIN, "")["status"] == "missing_parameter"
    assert spy.calls == []


# ------------------------------------------------------------------ T-ERR: repository failures
@pytest.mark.parametrize("name", list(TOOLS))
def test_T_ERR_01_repository_exception_gives_error_status_without_detail(name):
    boom = st.ExplodingRepo()
    svc, _, _ = st.build_permissions()
    prev = (guard.get_runtime().data_repo, guard.get_runtime().permission_service)
    guard.set_runtime(boom, svc)
    try:
        out = call(name, ADMIN, *_all_call_args(name))
    finally:
        guard.set_runtime(*prev)
    assert out == {"status": "error", "message": guard.ERROR_MESSAGE}
    assert boom.calls == 1
    assert "secret-detail" not in json.dumps(out)


def test_T_ERR_02_unconfigured_runtime_gives_error_not_exception():
    prev = (guard.get_runtime().data_repo, guard.get_runtime().permission_service)
    guard.set_runtime(None, None)
    try:
        assert call("get_delayed_truck", ADMIN)["status"] == "error"
    finally:
        guard.set_runtime(*prev)


def test_T_ERR_03_malformed_rows_in_repo_give_error_not_exception(repo_rows):
    bad = {"question3": [{"shipment_id": "S1", "stop_sequence": "abc"}]}
    svc, _, _ = st.build_permissions()
    prev = (guard.get_runtime().data_repo, guard.get_runtime().permission_service)
    guard.set_runtime(InMemoryDataRepository(bad), svc)
    try:
        out = call("get_truck_route_info", ADMIN, "S1")
    finally:
        guard.set_runtime(*prev)
    assert out["status"] in ("ok", "error")  # never raises


# ------------------------------------------------------------------ T-LEAK: output hygiene
def _all_outputs():
    outs = []
    for name in TOOLS:
        if name in KEYLESS:
            outs.append(call(name, ADMIN))
        else:
            col = {"get_truck_location": ("question1", "shipment_id"),
                   "get_material_truck_allocation": ("question2", "materialno"),
                   "get_truck_route_info": ("question3", "shipment_id"),
                   "get_critical_part_status": ("critical", "mip")}[name]
            for k in sorted({r[col[1]] for r in st.raw(col[0])}):
                outs.append(call(name, ADMIN, k))
    return outs


def test_T_LEAK_01_no_parsed_raw_json_auth_or_float_artifacts_in_any_output(env, secrets):
    problems = []
    outs = _all_outputs()
    assert len(outs) > 150
    for out in outs:
        assert out["status"] == "ok"
        problems += st.leak_problems(out, secrets)
    assert problems == []


def test_T_LEAK_02_forbidden_not_found_and_error_responses_carry_no_data(env, secrets):
    spy, svc, perms = env
    perms.delete(role_subject("SUPPLIER"), resource_key(FUNCTION, "get_delayed_truck"))
    svc.invalidate()
    for out in (call("get_delayed_truck", st.user_id("SUPPLIER")), call("get_truck_location", ADMIN, "XX999"),
                call("get_truck_location", ADMIN, "")):
        assert set(out) <= {"status", "message", "key", "parameter"}
        assert st.leak_problems(out, secrets) == []


def test_T_LEAK_03_outputs_are_json_serialisable_and_strict_json(env):
    for out in _all_outputs():
        assert json.loads(json.dumps(out, allow_nan=False)) == out


def test_T_LEAK_04_critical_and_tobearrived_columns_equal_the_sheet_columns_minus_json(env):
    crit = call("get_critical_part_status", ADMIN, "47")["rows"][0]
    assert set(crit) == set(st.raw("critical")[0])
    q5 = call("get_truck_tobearrived", ADMIN)["rows"][0]
    assert set(q5) == set(st.raw("question5")[0]) - {"question5"}
    q3 = call("get_truck_route_info", ADMIN, key_of("get_truck_route_info"))["rows"][0]
    assert set(q3) == set(st.raw("question3")[0])


def test_T_LEAK_05_tools_do_not_expose_auth_tables_through_the_repository(env):
    spy, _, _ = env
    for name in TOOLS:
        call(name, ADMIN, *_all_call_args(name))
    assert {c[1] for c in spy.calls} <= {"question1", "question2", "question3", "question4", "question5", "critical"}
    assert {c[1] for c in spy.calls} == set(st.FUNCTION_TABLE.values())


def test_T_LEAK_06_each_tool_reads_exactly_its_own_table_once(env):
    spy, _, _ = env
    for name, table in st.FUNCTION_TABLE.items():
        spy.calls.clear()
        call(name, ADMIN, *_all_call_args(name))
        assert len(spy.calls) == 1 and spy.calls[0][1] == table, name
