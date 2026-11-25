"""Shared harness for the natural-language tests (task 12.4). No AWS calls are made here.

``NLWorld`` wires the REAL pipeline: ``main.handle_request`` -> history parsing -> a fresh
``build_agent`` (real system prompt, real tools) -> permission guard -> in-memory repo built from
the REAL Excel. Only the ``model`` is injected (scripted mock or real Bedrock).
"""
from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass, field
from typing import Any

from strands.models import Model

import main
from agent_factory import build_agent
from identity import SessionTokenIdentityResolver
from logistic_ai_data.in_memory import InMemoryDataRepository
from logistic_ai_shared_auth.auth.session_token import EnvSecretProvider, SessionTokenService
from logistic_ai_shared_auth.authorization.permission_store import resource_key, role_subject
from logistic_ai_shared_auth.authorization.resources import FUNCTION
from parse import parse_history
from tools import guard

try:
    from . import support_tools as st
except ImportError:  # tests/e2e on sys.path
    import support_tools as st

ROLE = "TRANSPORT_OFFICE"
_REPO_ROWS: dict | None = None


def repo_rows() -> dict:
    global _REPO_ROWS
    if _REPO_ROWS is None:
        _REPO_ROWS = st.build_repo_rows()
    return _REPO_ROWS


@dataclass
class ToolCall:
    name: str
    input: dict
    status: str | None = None
    result: Any = None


@dataclass
class Turn:
    events: list
    text: str
    tool_calls: list[ToolCall]
    new_messages: list[dict] = field(default_factory=list)


def result_payload(block: dict) -> Any:
    """Decode a Strands toolResult block into the dict the tool returned."""
    for c in block.get("content", []):
        if "json" in c:
            return c["json"]
        if "text" in c:
            try:
                return json.loads(c["text"])
            except ValueError:
                return {"text": c["text"]}
    return None


def extract_tool_calls(messages: list[dict]) -> list[ToolCall]:
    calls: dict[str, ToolCall] = {}
    order: list[str] = []
    for m in messages:
        for b in m.get("content", []):
            if "toolUse" in b:
                tu = b["toolUse"]
                calls[tu["toolUseId"]] = ToolCall(tu["name"], dict(tu.get("input") or {}))
                order.append(tu["toolUseId"])
            elif "toolResult" in b:
                tr = b["toolResult"]
                call = calls.get(tr["toolUseId"])
                if call is not None:
                    call.result = result_payload(tr)
                    call.status = (call.result or {}).get("status") if isinstance(call.result, dict) else None
    return [calls[i] for i in order]


class NLWorld:
    """Pipeline under test. ``deny`` = function names denied to the test user's role."""

    def __init__(self, model: Any, deny: tuple[str, ...] = ()) -> None:
        self.spy = st.SpyRepo(InMemoryDataRepository(repo_rows()))
        self.perm_service, self.perms, self.users = st.build_permissions()
        for fn in deny:
            self.perms.put(role_subject(ROLE), resource_key(FUNCTION, fn), False, "test")
        guard.set_runtime(self.spy, self.perm_service)
        self.model = model
        self.tokens = SessionTokenService(EnvSecretProvider(environ={"LOGISTIC_AI_SESSION_SECRET": "n" * 32}))
        self.last_agent: Any = None
        self.userid = st.user_id(ROLE)
        self.services = main._Services(SessionTokenIdentityResolver(self.tokens), self.users, self._provider)

    def _provider(self, messages: list | None = None) -> Any:
        self.last_agent = build_agent(model=self.model, messages=messages)
        return self.last_agent

    def ask(self, prompt: str, history: list[dict] | None = None) -> Turn:
        token = self.tokens.issue(self.userid, f"user_{ROLE.lower()}", ROLE)
        payload: dict = {"prompt": prompt, "session_token": token}
        if history is not None:
            payload["history"] = history

        async def go() -> list:
            return [e async for e in main.handle_request(payload, None, self.services)]

        events = asyncio.run(go())
        text = "".join(
            e["event"]["contentBlockDelta"]["delta"]["text"] for e in events if "event" in e
        )
        msgs = self.last_agent.messages if self.last_agent is not None else []
        n_hist = len(parse_history({"history": history})) if history else 0
        new = msgs[n_hist:]  # messages produced by this request (after the injected history)
        return Turn(events, text, extract_tool_calls(new), new)


# ------------------------------------------------------------------------- scripted mock LLM
class PerfectLLM(Model):
    """MOCK model that simulates a *perfect* LLM driven by the dataset's expectation.

    ``plan``: ``{"tool": name, "args": {...}}`` -> first call emits that toolUse; or ``None`` ->
    answers with a clarifying question (no tool call). After a toolResult it answers with a text
    built ONLY from the tool result (status / count / the model's own words), never from data it
    was not given. It records every message list it receives so tests can verify what the
    pipeline fed to the model (history, tool results, system prompt).
    """

    def __init__(self, plan: dict | None, lang: str = "en") -> None:
        self.plan, self.lang = plan, lang
        self.seen: list[list[dict]] = []
        self.system_prompts: list[str | None] = []
        self.tool_specs: list[list[str]] = []
        self.final_text: str | None = None
        self.tool_results_seen: list[Any] = []

    def update_config(self, **model_config: Any) -> None: ...

    def get_config(self) -> Any:
        return {}

    async def structured_output(self, *a: Any, **k: Any):  # pragma: no cover
        raise NotImplementedError
        yield

    def _clarify(self) -> str:
        key = (self.plan or {}).get("needs", "id")
        return (
            f"Lütfen {key} bilgisini paylaşır mısınız?"
            if self.lang == "tr"
            else f"Could you please provide the {key}?"
        )

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.seen.append(copy.deepcopy(list(messages)))
        self.system_prompts.append(system_prompt)
        self.tool_specs.append([t["name"] for t in (tool_specs or [])])
        last = messages[-1]
        results = [b["toolResult"] for b in last.get("content", []) if "toolResult" in b]
        yield {"messageStart": {"role": "assistant"}}
        if results:
            payload = result_payload(results[0])
            self.tool_results_seen.append(payload)
            status = payload.get("status") if isinstance(payload, dict) else None
            if status == "forbidden":
                text = "Bu işlem için yetkiniz yok"
            elif status == "not_found":
                text = "Kayıt bulunamadı."
            elif status == "ok":
                text = f"{payload.get('count')} kayıt bulundu."
            else:
                text = f"İşlem tamamlanamadı ({status})."
            self.final_text = text
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": text}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        elif self.plan and self.plan.get("tool"):
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "tu-1", "name": self.plan["tool"]}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(self.plan.get("args") or {})}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            text = self._clarify()
            self.final_text = text
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": text}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
