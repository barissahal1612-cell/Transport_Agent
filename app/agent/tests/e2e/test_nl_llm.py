"""REAL LLM integration tests (task 12.4 D). Marker ``llm``; excluded by default.

Run:  python -m pytest -m llm tests/e2e/test_nl_llm.py -v

Real Bedrock model + REAL system prompt + REAL tools + in-memory repo from the REAL Excel. The
model only reads/answers; no AWS resource is created. Tests are SKIPPED (reported as BLOCKED) when
AWS credentials do not work, no model id can be found, or the model cannot be invoked.
Results (no secrets, no answer text for data-bearing replies) go to ``llm_results.json``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

try:
    from . import nl_cases as C
    from . import nl_harness as H
except ImportError:
    import nl_cases as C
    import nl_harness as H

from tools import guard

pytestmark = pytest.mark.llm

RESULTS_PATH = Path(__file__).with_name("llm_results.json")
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
IDENT = re.compile(r"\b(?:FA\d{6,}|\d{8,}[A-Z]?)\b")
from model.load import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE

MAX_TOKENS = DEFAULT_MAX_TOKENS  # production default (a 600 cap truncated long table answers)
TEMPERATURE = DEFAULT_TEMPERATURE
# Accuracy gates for the summary test (fractions)
GATES = {"tool_selection": 0.90, "arg_accuracy": 0.95, "missing_key_clarification": 0.90,
         "followup_success": 0.80, "hallucination_free": 1.0}


def _aws(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["aws", *args, "--region", REGION], capture_output=True, text=True, timeout=timeout)


def _discover() -> tuple[str | None, str]:
    """(model_id or None, blocked reason). Read-only AWS calls only."""
    try:
        who = subprocess.run(["aws", "sts", "get-caller-identity"], capture_output=True, text=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        return None, f"aws cli unavailable: {type(exc).__name__}"
    if who.returncode != 0:
        return None, "AWS credentials do not work (aws sts get-caller-identity failed)"
    model = (os.environ.get("LOGISTIC_AI_MODEL_ID") or "").strip()
    if model:
        return model, ""
    out = _aws("bedrock", "list-foundation-models", "--by-provider", "Anthropic", "--query",
               "modelSummaries[?modelLifecycle.status=='ACTIVE'].modelId", "--output", "json")
    if out.returncode != 0:
        return None, "LOGISTIC_AI_MODEL_ID unset and model discovery failed"
    ids = json.loads(out.stdout or "[]")
    for pref in ("claude-haiku-4-5", "claude-sonnet-4-6"):  # small + fast first
        for i in ids:
            if pref in i:
                return "global." + i, ""
    return ("global." + ids[0], "") if ids else (None, "no ACTIVE Anthropic model found")


class _Session:
    model_id: str | None = None
    blocked: str = ""
    calls: int = 0
    records: list[dict] = []
    started = time.time()


def _make_model():
    from strands.models import BedrockModel

    class Counting(BedrockModel):
        async def stream(self, *a, **k):  # count every Bedrock call
            _Session.calls += 1
            async for ev in super().stream(*a, **k):
                yield ev

    kw = dict(model_id=_Session.model_id, region_name=REGION, max_tokens=MAX_TOKENS, temperature=TEMPERATURE)
    return Counting(**kw)


@pytest.fixture(scope="module", autouse=True)
def llm_ready():
    _Session.model_id, _Session.blocked = _discover()
    if _Session.model_id is None:
        pytest.skip(f"BLOCKED: {_Session.blocked}")
    prev = (guard.get_runtime().data_repo, guard.get_runtime().permission_service)
    # probe once so an inaccessible model blocks everything with ONE clear reason
    try:
        H.NLWorld(_make_model()).ask("Hangi tırlar geç kaldı?")
    except Exception as exc:  # noqa: BLE001
        _Session.blocked = f"model {_Session.model_id} cannot be invoked: {type(exc).__name__}: {str(exc)[:300]}"
        guard.set_runtime(*prev)
        pytest.skip(f"BLOCKED: {_Session.blocked}")
    yield
    guard.set_runtime(*prev)
    _write_results()


def _fresh_world(deny: tuple[str, ...] = ()) -> H.NLWorld:
    return H.NLWorld(_make_model(), deny=deny)


def _safe_ask(world: H.NLWorld, prompt: str, history=None) -> H.Turn:
    for attempt in range(3):  # transient throttling only
        try:
            return world.ask(prompt, history)
        except Exception as exc:  # noqa: BLE001
            if attempt == 2 or "hrottl" not in f"{type(exc).__name__}{exc}":
                raise
            time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


def _record(**kw) -> dict:
    _Session.records.append(kw)
    return kw


def _answer_error_text(turn: H.Turn) -> bool:
    return any("error" in e for e in turn.events)


# --------------------------------------------------------------------------- single turn
@pytest.mark.parametrize("case", C.SINGLE_CASES, ids=lambda c: c.id)
def test_LLM_01_single_turn_tool_selection(case):
    """REAL LLM: tool selection + argument extraction for one question (expects the first call)."""
    turn = _safe_ask(_fresh_world(), case.question)
    first = turn.tool_calls[0] if turn.tool_calls else None
    actual_tool = first.name if first else None
    actual_args = {k: str(v) for k, v in (first.input if first else {}).items()}
    tool_ok = actual_tool == case.expected_tool
    args_ok = tool_ok and actual_args == {k: str(v) for k, v in case.expected_args.items()}
    _record(id=case.id, kind="single", lang=case.lang, expected_tool=case.expected_tool,
            expected_args=case.expected_args, actual_tool=actual_tool, actual_args=actual_args,
            status=first.status if first else None, tool_ok=tool_ok, args_ok=args_ok,
            n_tool_calls=len(turn.tool_calls), error=_answer_error_text(turn))
    assert tool_ok, f"expected {case.expected_tool}, got {actual_tool}"
    assert args_ok, f"expected args {case.expected_args}, got {actual_args}"


# --------------------------------------------------------------------------- missing key
@pytest.mark.parametrize("case", C.MISSING_KEY_CASES, ids=lambda c: c.id)
def test_LLM_02_missing_key_asks_instead_of_calling(case):
    """REAL LLM: no key given -> NO tool call and the reply is a clarifying question."""
    world = _fresh_world()
    turn = _safe_ask(world, case.question)
    asked = "?" in turn.text or "?" in turn.text.replace("？", "?")
    ok = not turn.tool_calls and asked and not world.spy.calls
    _record(id=case.id, kind="missing_key", lang=case.lang, expected_tool=None, expected_args={},
            actual_tool=turn.tool_calls[0].name if turn.tool_calls else None,
            actual_args=dict(turn.tool_calls[0].input) if turn.tool_calls else {},
            asked_question=asked, answer=turn.text[:300], ok=ok, error=_answer_error_text(turn))
    assert not turn.tool_calls, f"unexpected tool call {[c.name for c in turn.tool_calls]}"
    assert asked, "reply does not ask the user for the missing key"


# --------------------------------------------------------------------------- follow-ups
@pytest.mark.parametrize("case", C.FOLLOWUP_CASES, ids=lambda c: c.id)
def test_LLM_03_followup_uses_conversation_context(case):
    """REAL LLM: turn 2 sends only the key (or only the question); history supplies the rest."""
    turn = _safe_ask(_fresh_world(), case.prompt, [dict(m) for m in case.history])
    first = turn.tool_calls[0] if turn.tool_calls else None
    actual_args = {k: str(v) for k, v in (first.input if first else {}).items()}
    ok = bool(first) and first.name == case.expected_tool and actual_args == case.expected_args
    _record(id=case.id, kind="followup", lang=case.lang, followup_kind=case.kind,
            expected_tool=case.expected_tool, expected_args=case.expected_args,
            actual_tool=first.name if first else None, actual_args=actual_args,
            status=first.status if first else None, ok=ok, error=_answer_error_text(turn))
    assert ok, f"expected {case.expected_tool}{case.expected_args}, got {first.name if first else None}{actual_args}"


# --------------------------------------------------------------------------- hallucination
def _invented(question: str, answer: str) -> list[str]:
    return sorted(set(IDENT.findall(answer)) - set(IDENT.findall(question)))


@pytest.mark.parametrize("case", C.NOT_FOUND_CASES, ids=lambda c: c.id)
def test_LLM_04_not_found_no_invented_records(case):
    """REAL LLM: tool returns not_found -> answer says so and invents no identifiers."""
    turn = _safe_ask(_fresh_world(), case.question)
    call = turn.tool_calls[0] if turn.tool_calls else None
    invented = _invented(case.question, turn.text)
    ok = bool(call) and call.status == "not_found" and not invented
    _record(id=case.id, kind="not_found", lang=case.lang, expected_tool=case.expected_tool,
            expected_args=case.expected_args, actual_tool=call.name if call else None,
            actual_args=dict(call.input) if call else {}, status=call.status if call else None,
            invented_identifiers=invented, answer=turn.text[:400], ok=ok)
    assert call is not None and call.status == "not_found"
    assert not invented, f"invented identifiers {invented}"


@pytest.mark.parametrize("case", C.FORBIDDEN_CASES, ids=lambda c: c.id)
def test_LLM_05_forbidden_no_data_leak(case):
    """REAL LLM: tool returns forbidden -> answer has no identifiers/data beyond the question."""
    world = _fresh_world(deny=(case.expected_tool,))
    turn = _safe_ask(world, case.question)
    call = turn.tool_calls[0] if turn.tool_calls else None
    invented = _invented(case.question, turn.text)
    ok = bool(call) and call.status == "forbidden" and not invented and not world.spy.calls
    _record(id=case.id, kind="forbidden", lang=case.lang, expected_tool=case.expected_tool,
            expected_args=case.expected_args, actual_tool=call.name if call else None,
            actual_args=dict(call.input) if call else {}, status=call.status if call else None,
            invented_identifiers=invented, answer=turn.text[:400], ok=ok)
    assert call is not None and call.status == "forbidden" and world.spy.calls == []
    assert not invented, f"invented identifiers {invented}"


# --------------------------------------------------------------------------- metrics
def compute_metrics(records: list[dict]) -> dict:
    def frac(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    single = [r for r in records if r["kind"] == "single"]
    miss = [r for r in records if r["kind"] == "missing_key"]
    fol = [r for r in records if r["kind"] == "followup"]
    hal = [r for r in records if r["kind"] in ("not_found", "forbidden")]
    tool_ok = [r for r in single if r["tool_ok"]]
    return {
        "tool_selection": frac(len(tool_ok), len(single)),
        "arg_accuracy": frac(sum(1 for r in tool_ok if r["args_ok"]), len(tool_ok)),
        "missing_key_clarification": frac(sum(1 for r in miss if r["ok"]), len(miss)),
        "followup_success": frac(sum(1 for r in fol if r["ok"]), len(fol)),
        "hallucination_free": frac(sum(1 for r in hal if r["ok"]), len(hal)),
        "counts": {"single": len(single), "missing_key": len(miss), "followup": len(fol), "hallucination": len(hal)},
    }


def _write_results() -> None:
    """Merge this run's cases into the existing file by case id (subset runs keep other cases)."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    prev: dict = {}
    if RESULTS_PATH.exists():
        try:
            prev = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        except ValueError:
            prev = {}
    merged = {c["id"]: c for c in prev.get("cases", [])}
    for rec in _Session.records:
        merged[rec["id"]] = {**rec, "run_max_tokens": MAX_TOKENS, "run_at": now}
    notes = list(prev.get("run_notes", []))
    if _Session.records:
        notes.append({"at": now, "cases": len(_Session.records), "max_tokens": MAX_TOKENS,
                      "temperature": TEMPERATURE, "bedrock_calls": _Session.calls})
    cases = list(merged.values())
    data = {
        "model_id": _Session.model_id, "region": REGION,
        "bedrock_calls": prev.get("bedrock_calls", 0) + (_Session.calls if _Session.records else 0),
        "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS, "generated_at": now,
        "run_notes": notes, "metrics": compute_metrics(cases), "cases": cases,
    }
    RESULTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def test_LLM_99_accuracy_gates():
    """REAL LLM summary: aggregated accuracies must reach the gates (runs last in this module)."""
    m = compute_metrics(_Session.records)
    print("LLM metrics:", json.dumps(m))
    bad = {k: (m[k], g) for k, g in GATES.items() if m[k] is not None and m[k] < g}
    assert not bad, f"below gate (actual, gate): {bad}"
