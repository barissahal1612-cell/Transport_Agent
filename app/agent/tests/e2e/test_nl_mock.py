"""MOCK-model tests for natural language -> tool pipeline (task 12.4 C). Always run, no AWS.

IMPORTANT: every test here uses ``PerfectLLM``, a scripted model that "routes" using the dataset's
own expected tool. These tests therefore verify the PIPELINE (client history -> parse -> fresh agent
-> tool call -> permission guard -> Excel data -> tool result back to the model -> final text), NOT
the intelligence of a real LLM. Real-LLM behaviour is measured in ``test_nl_llm.py`` (marker ``llm``).
"""
from __future__ import annotations

import pytest

try:
    from . import nl_cases as C
    from . import nl_harness as H
    from . import support_tools as st
except ImportError:
    import nl_cases as C
    import nl_harness as H
    import support_tools as st

from prompts.system_prompt import get_system_prompt
from tools import guard

KEY_TABLE = st.FUNCTION_TABLE


@pytest.fixture(autouse=True)
def _restore_runtime():
    prev = (guard.get_runtime().data_repo, guard.get_runtime().permission_service)
    yield
    guard.set_runtime(*prev)


def _plan(tool: str, args: dict) -> dict:
    return {"tool": tool, "args": args}


def _check_data(call: H.ToolCall) -> None:
    """Rows returned by the tool equal values computed independently from the raw Excel."""
    rows, name, args = call.result["rows"], call.name, call.input
    if name == "get_truck_location":
        assert rows == st.expected_q1(args["shipment_id"])
    elif name == "get_material_truck_allocation":
        assert rows == st.expected_q2(args["materialno"])
    elif name == "get_truck_route_info":
        exp = st.expected_q3(args["shipment_id"])
        assert [int(r["stop_sequence"]) for r in rows] == [int(r["stop_sequence"]) for r in exp]
    elif name == "get_delayed_truck":
        assert sorted(r["shipment_id"] for r in rows) == sorted(r["shipment_id"] for r in st.expected_q4())
    elif name == "get_truck_tobearrived":
        assert sorted(r["shipment_id"] for r in rows) == sorted(r["shipment_id"] for r in st.expected_q5())
    elif name == "get_critical_part_status":
        assert len(rows) == len(st.expected_critical(args["mip"]))
    else:  # pragma: no cover
        raise AssertionError(name)


# --------------------------------------------------------------------------- dataset sanity
def test_NLM_00_dataset_size_and_real_keys():
    """MOCK/dataset: >=5 TR and >=5 EN distinct questions per function, all keys real."""
    for fn in C.ALL_FUNCTIONS:
        for lang in ("tr", "en"):
            qs = [c.question for c in C.SINGLE_CASES if c.expected_tool == fn and c.lang == lang]
            assert len(qs) >= 5 and len(set(qs)) == len(qs), (fn, lang)
    assert len(C.SINGLE_CASES) >= 60 and len({c.question for c in C.SINGLE_CASES}) == len(C.SINGLE_CASES)
    real = {
        "shipment_id": {r["shipment_id"] for r in st.raw("question1")} | {r["shipment_id"] for r in st.raw("question3")},
        "materialno": {r["materialno"] for r in st.raw("question2")},
        "mip": {r["mip"] for r in st.raw("critical")},
    }
    for c in C.SINGLE_CASES + C.FOLLOWUP_CASES:
        for k, v in c.expected_args.items():
            assert v in real[k], (c.id, k, v)
    for fn in C.KEYED_TOOLS:
        for lang in ("tr", "en"):
            assert len([m for m in C.MISSING_KEY_CASES if m.needed_tool == fn and m.lang == lang]) >= 2


# --------------------------------------------------------------------------- single turn
@pytest.mark.parametrize("case", C.SINGLE_CASES, ids=lambda c: c.id)
def test_NLM_01_single_turn_routes_and_returns_data(case):
    """MOCK: perfect-LLM routing -> exactly the expected tool + args -> real Excel data -> model."""
    model = H.PerfectLLM(_plan(case.expected_tool, case.expected_args), case.lang)
    world = H.NLWorld(model)
    turn = world.ask(case.question)
    assert [(c.name, c.input) for c in turn.tool_calls] == [(case.expected_tool, case.expected_args)]
    call = turn.tool_calls[0]
    assert call.status == "ok" and call.result["count"] >= 1
    _check_data(call)
    # the tool result was handed back to the model (2nd model call saw it)
    assert len(model.seen) == 2 and model.tool_results_seen == [call.result]
    # the code path only reads the one table (and key) the tool is defined for
    table = KEY_TABLE[case.expected_tool]
    expected_repo_call = (
        [("get_by_key", table, case.expected_args[C.KEY_PARAM[case.expected_tool]])]
        if case.expected_tool in C.KEYED_TOOLS
        else [("get_all", table)]
    )
    assert world.spy.calls == expected_repo_call
    # the user-visible answer is exactly the model's text, nothing injected by the code
    assert turn.text == model.final_text and all("event" in e for e in turn.events)
    # the real system prompt and all six tools were offered to the model
    assert model.system_prompts[0] == get_system_prompt()
    assert set(model.tool_specs[0]) == set(C.ALL_FUNCTIONS)
    assert case.question in str(model.seen[0][-1])


# --------------------------------------------------------------------------- missing key
@pytest.mark.parametrize("case", C.MISSING_KEY_CASES, ids=lambda c: c.id)
def test_NLM_02_missing_key_no_tool_call_and_clarifying_question(case):
    """MOCK: perfect LLM asks for the key; pipeline makes no tool call and no repo access."""
    model = H.PerfectLLM({"needs": C.KEY_PARAM[case.needed_tool]}, case.lang)
    world = H.NLWorld(model)
    turn = world.ask(case.question)
    assert turn.tool_calls == [] and world.spy.calls == []
    assert turn.text == model.final_text and turn.text.rstrip().endswith("?")
    assert len(model.seen) == 1


@pytest.mark.parametrize("tool", C.KEYED_TOOLS)
def test_NLM_03_guard_stops_a_model_that_calls_a_keyed_tool_without_key(tool):
    """MOCK safety net: even a model that wrongly calls a keyed tool with an empty key gets
    ``missing_parameter`` back and the repository is never touched."""
    model = H.PerfectLLM(_plan(tool, {C.KEY_PARAM[tool]: ""}))
    world = H.NLWorld(model)
    turn = world.ask("anything")
    assert [c.status for c in turn.tool_calls] == ["missing_parameter"]
    assert world.spy.calls == []


# --------------------------------------------------------------------------- follow-ups
@pytest.mark.parametrize("case", C.FOLLOWUP_CASES, ids=lambda c: c.id)
def test_NLM_04_followup_history_reaches_model_and_tool_runs(case):
    """MOCK: turn-2 prompt carries only the key (or only the question); the client history reaches
    the model before the new prompt and the context-derived tool runs with the real key."""
    model = H.PerfectLLM(_plan(case.expected_tool, case.expected_args), case.lang)
    world = H.NLWorld(model)
    history = [dict(m) for m in case.history]
    turn = world.ask(case.prompt, history)
    first_call_texts = [b["text"] for m in model.seen[0] for b in m["content"] if "text" in b]
    assert first_call_texts == [m["content"] for m in history] + [case.prompt]
    assert [m["role"] for m in model.seen[0]] == ["user", "assistant", "user"]
    assert [(c.name, c.input) for c in turn.tool_calls] == [(case.expected_tool, case.expected_args)]
    assert turn.tool_calls[0].status == "ok"
    _check_data(turn.tool_calls[0])
    assert turn.text == model.final_text


# --------------------------------------------------------------------------- not_found / forbidden
@pytest.mark.parametrize("case", C.NOT_FOUND_CASES, ids=lambda c: c.id)
def test_NLM_05_not_found_is_surfaced_without_data(case):
    """MOCK: unknown key -> tool says not_found; model gets it; no rows are injected anywhere."""
    model = H.PerfectLLM(_plan(case.expected_tool, case.expected_args), case.lang)
    world = H.NLWorld(model)
    turn = world.ask(case.question)
    call = turn.tool_calls[0]
    assert call.status == "not_found" and "rows" not in call.result
    assert model.tool_results_seen[0]["status"] == "not_found"
    assert turn.text == model.final_text == "Kayıt bulunamadı."
    assert not any(ch.isdigit() for ch in turn.text)  # no identifiers / numbers invented by code


@pytest.mark.parametrize("case", C.FORBIDDEN_CASES, ids=lambda c: c.id)
def test_NLM_06_forbidden_is_surfaced_and_repo_untouched(case):
    """MOCK: permission denied -> tool says forbidden; repository never read; model gets only that."""
    model = H.PerfectLLM(_plan(case.expected_tool, case.expected_args), case.lang)
    world = H.NLWorld(model, deny=(case.expected_tool,))
    turn = world.ask(case.question)
    call = turn.tool_calls[0]
    assert call.status == "forbidden" and set(call.result) == {"status", "message"}
    assert world.spy.calls == []
    assert turn.text == model.final_text == guard.FORBIDDEN_MESSAGE


def test_NLM_07_user_isolation_in_pipeline():
    """MOCK: a second request without history does not see the first request's conversation."""
    case = C.FOLLOWUP_CASES[0]
    m1 = H.PerfectLLM(_plan(case.expected_tool, case.expected_args))
    H.NLWorld(m1).ask(case.prompt, [dict(x) for x in case.history])
    m2 = H.PerfectLLM({"needs": "shipment_id"})
    H.NLWorld(m2).ask("Tır nerede?")
    assert [b["text"] for m in m2.seen[0] for b in m["content"]] == ["Tır nerede?"]
