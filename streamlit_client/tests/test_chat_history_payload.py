"""Chat history is sent with each invoke (task 12.4 A): last 10 messages, 2000 chars each."""
from __future__ import annotations

import json
from types import SimpleNamespace

from logistic_ai.session.agentcore_client import AgentCoreClient, HttpResponse, build_history_payload
from logistic_ai.ui import home_screen


class _Transport:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def invoke(self, runtime_arn, session_id, body, timeout):
        self.bodies.append(json.loads(body))
        return HttpResponse(status_code=200, lines=[])


def _client() -> tuple[AgentCoreClient, _Transport]:
    tr = _Transport()
    return AgentCoreClient("arn:x", "r", http=tr), tr


def test_no_history_keeps_payload_unchanged():
    c, tr = _client()
    list(c.invoke("T", "hi", "s"))
    assert tr.bodies[0] == {"prompt": "hi", "session_token": "T"}


def test_history_is_sent_capped_and_truncated():
    c, tr = _client()
    hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}" + "x" * 3000} for i in range(15)]
    list(c.invoke("T", "now", "s", history=hist))
    sent = tr.bodies[0]["history"]
    assert len(sent) == 10
    assert [m["content"].split("x")[0] for m in sent] == [f"m{i}" for i in range(5, 15)]
    assert all(len(m["content"]) == 2000 for m in sent)
    assert {m["role"] for m in sent} <= {"user", "assistant"}


def test_build_history_payload_drops_bad_items():
    out = build_history_payload([{"role": "system", "content": "x"}, {"role": "user"}, "str", {"role": "user", "content": "ok"}])
    assert out == [{"role": "user", "content": "ok"}]


def test_home_screen_passes_stored_history_before_new_prompt(monkeypatch):
    seen = {}

    class _Client:
        def invoke(self, token, prompt, session_id, history=None):
            seen.update(token=token, prompt=prompt, history=history)
            return iter(["ok"])

    monkeypatch.setattr(home_screen.st, "session_state", {home_screen.KEY_CHAT_HISTORY: [], home_screen.KEY_CHAT_SESSION_ID: "s" * 40})
    deps = SimpleNamespace(
        agent_client=_Client(),
        session=SimpleNamespace(touch=lambda: None, require_valid_session=lambda: SimpleNamespace(session_token="TOK")),
    )
    prior = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]
    assert home_screen._ask_agent(deps, "q2", prior) == "ok"
    assert seen["history"] == prior and seen["prompt"] == "q2"
