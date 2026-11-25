"""Session manager, login attempt, AgentCore client and router composition (no AWS)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from logistic_ai_shared_auth.auth.errors import AuthError, AuthErrorKind
from logistic_ai_shared_auth.auth.passwords import PasswordHasher
from logistic_ai_shared_auth.auth.session_token import SessionTokenService
from logistic_ai_shared_auth.auth.user_auth_service import UserAuthService
from logistic_ai_shared_auth.auth.users import InMemoryUserRepository, UserRecord
from logistic_ai_shared_auth.common.clock import FixedClock

from logistic_ai.config.settings import ConfigError, load_settings
from logistic_ai.session.agentcore_client import (
    AgentCoreClient,
    AgentCoreError,
    AgentCoreUnauthorized,
    HttpResponse,
)
from logistic_ai.session.manager import (
    KEY_CHAT_HISTORY,
    SessionInvalid,
    SessionManager,
)
from logistic_ai.ui import login_screen, router


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def log_login(self, username, success):
        self.events.append(("login", username, success))

    def log_logout(self, username):
        self.events.append(("logout", username))

    def log_session_timeout(self, username):
        self.events.append(("timeout", username))

    def log_authorization_denied(self, *a, **k):
        pass


class _Secret:
    def get_secret(self) -> str:
        return "x" * 32


class _Settings:
    idle_timeout_minutes = 30


def _make(role="TRANSPORT_OFFICE"):
    clock = FixedClock(datetime(2025, 1, 1, tzinfo=timezone.utc))
    hasher = PasswordHasher()
    users = InMemoryUserRepository(
        [UserRecord("1", "alice", role, hasher.hash("S3cret-pass!"))]
    )
    audit = _Audit()
    auth = UserAuthService(users, hasher, SessionTokenService(_Secret(), clock), audit, clock)
    store: dict = {}
    mgr = SessionManager(store, auth, _Settings(), clock, audit)
    return mgr, auth, store, audit, clock


def test_login_logout_and_idle_timeout():
    mgr, auth, store, audit, clock = _make()
    mgr.establish(auth.authenticate("alice", "S3cret-pass!"))
    assert set(store) == {"session_token", "userid", "username", "role", "last_activity"}
    assert "S3cret-pass!" not in json.dumps(store, default=str)
    view = mgr.require_valid_session()
    assert (view.userid, view.username, view.role) == ("1", "alice", "TRANSPORT_OFFICE")

    store[KEY_CHAT_HISTORY] = [{"role": "user", "content": "hi"}]
    mgr.logout()
    assert store == {}
    assert ("logout", "alice") in audit.events
    with pytest.raises(SessionInvalid):
        mgr.require_valid_session()

    mgr.establish(auth.authenticate("alice", "S3cret-pass!"))
    clock.advance(30 * 60)
    with pytest.raises(SessionInvalid) as exc:
        mgr.require_valid_session()
    assert exc.value.reason == "idle_timeout" and store == {}


def test_attempt_login_generic_error_and_success():
    mgr, auth, store, _, _ = _make()
    deps = type("D", (), {"auth": auth, "session": mgr})()
    msg = login_screen._attempt_login(deps, "alice", "wrong-password!")
    assert msg == AuthError(AuthErrorKind.INVALID_CREDENTIALS).user_message
    assert store == {}
    assert login_screen._attempt_login(deps, "alice", "S3cret-pass!") is None
    assert store["role"] == "TRANSPORT_OFFICE"


class _FakeTransport:
    def __init__(self, lines, status=200):
        self.resp = HttpResponse(status_code=status, lines=lines)
        self.calls = []

    def invoke(self, runtime_arn, session_id, body, timeout):
        self.calls.append((runtime_arn, session_id, json.loads(body)))
        return self.resp


def _text(t):
    return json.dumps({"event": {"contentBlockDelta": {"delta": {"text": t}}}})


def test_client_payload_and_streaming():
    tr = _FakeTransport([f"data: {_text('Mer')}", f"data: {_text('haba')}"])
    c = AgentCoreClient("arn:x", "eu-west-1", http=tr)
    assert "".join(c.invoke("TOKEN", "selam", "short")) == "Merhaba"
    arn, sid, payload = tr.calls[0]
    assert arn == "arn:x" and len(sid) >= 33
    assert payload == {"prompt": "selam", "session_token": "TOKEN"}


def test_client_unauthenticated_event_and_bad_status():
    ev = json.dumps({"error": "unauthenticated", "message": "m"})
    c = AgentCoreClient("arn:x", "r", http=_FakeTransport([f"data: {ev}"]))
    with pytest.raises(AgentCoreUnauthorized):
        list(c.invoke("t", "p", "s"))
    c = AgentCoreClient("arn:x", "r", http=_FakeTransport([], status=500))
    with pytest.raises(AgentCoreError):
        c.invoke("t", "p", "s")


def test_settings_no_cognito_required():
    s = load_settings({"LOGISTIC_AI_AWS_REGION": "eu-west-1", "LOGISTIC_AI_AGENT_RUNTIME_ARN": "arn:x"})
    assert s.aws_region == "eu-west-1" and s.idle_timeout_minutes == 30
    with pytest.raises(ConfigError):
        load_settings({})


@pytest.mark.parametrize(
    "role,expected",
    [
        ("TRANSPORT_OFFICE", ["dashboard", "chat"]),
        ("MATERIAL_RESPONSIBLE", ["dashboard", "chat"]),
        ("SUPPLIER", ["chat"]),
    ],
)
def test_router_role_composition(monkeypatch, role, expected):
    calls: list[str] = []
    monkeypatch.setattr(router, "_show_dashboard", lambda d: calls.append("dashboard"))
    monkeypatch.setattr(router, "_show_admin_panel", lambda d: calls.append("admin"))
    monkeypatch.setattr(router, "_show_home", lambda d: calls.append("chat"))
    monkeypatch.setattr(router.st, "session_state", {})  # fresh session: first view after login
    monkeypatch.setattr(router.st.sidebar, "radio", lambda *a, **k: router.PAGE_CHAT)
    router._show_role_pages(object(), role)
    assert calls == expected


def test_router_admin_pages(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(router, "_show_dashboard", lambda d: calls.append("dashboard"))
    monkeypatch.setattr(router, "_show_admin_panel", lambda d: calls.append("admin"))
    monkeypatch.setattr(router, "_show_home", lambda d: calls.append("chat"))
    monkeypatch.setattr(router, "_show_admin_header", lambda d: None)
    for page, expected in ((router.PAGE_ADMIN, ["admin"]), (router.PAGE_CHAT, ["chat"])):
        calls.clear()
        monkeypatch.setattr(router.st.sidebar, "radio", lambda *a, _p=page, **k: _p)
        router._show_role_pages(object(), "ADMIN")
        assert calls == expected
