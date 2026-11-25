"""E2E: session / chat-history isolation between users (task 12.2). No AWS, real Excel auth sheets.

Each user has an own ``st.session_state`` store (a dict, as in the manager tests) and SessionManager.
The real ``home_screen._history/_ask_agent`` run against a fake AgentCore transport (FakeBackend).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_isolation_helpers as H  # noqa: E402

import jwt  # noqa: E402

from logistic_ai.session.agentcore_client import AgentCoreClient, AgentCoreUnauthorized  # noqa: E402
from logistic_ai.session.manager import (  # noqa: E402
    KEY_CHAT_HISTORY,
    KEY_CHAT_SESSION_ID,
    SESSION_KEYS,
    SessionInvalid,
    SessionManager,
)
from logistic_ai.session.user_context import NotAuthenticated, UserContextProvider  # noqa: E402
from logistic_ai.ui import home_screen  # noqa: E402
from logistic_ai_shared_auth.auth.session_token import SessionTokenService  # noqa: E402
from logistic_ai_shared_auth.auth.user_auth_service import UserAuthService  # noqa: E402
from logistic_ai_shared_auth.auth.users import InMemoryUserRepository  # noqa: E402
from logistic_ai_shared_auth.authorization.admin_service import AdminService  # noqa: E402
from logistic_ai_shared_auth.authorization.authorizer import PermissionDenied  # noqa: E402
from logistic_ai_shared_auth.authorization.permission_service import PermissionService  # noqa: E402
from logistic_ai_shared_auth.authorization.permission_store import InMemoryPermissionRepository  # noqa: E402
from logistic_ai_shared_auth.common.clock import FixedClock  # noqa: E402

T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


class World:
    """Shared backend side + one (store, manager) pair per browser session."""

    def __init__(self, data):
        subset, self.creds, self.extras = data
        self.clock = FixedClock(T0)
        self.audit = H.RecordingAudit()
        self.users, self.perms = InMemoryUserRepository(), InMemoryPermissionRepository()
        H.seed(subset, self.users, self.perms)
        self.tokens = SessionTokenService(H.FixedSecret(), self.clock)
        self.auth = UserAuthService(self.users, H.fast_hasher(), self.tokens, self.audit, self.clock)
        self.backend = H.FakeBackend(self.tokens, self.users)
        self.client = AgentCoreClient("arn:aws:bedrock-agentcore:eu-west-1:000000000000:runtime/x", "eu-west-1",
                                      http=self.backend)
        self.admin = AdminService(self.users, self.perms,
                                  PermissionService(self.users, self.perms, self.audit, self.clock),
                                  clock=self.clock)

    def browser(self):
        store: dict = {}
        mgr = SessionManager(store, self.auth, H.Settings(), self.clock, self.audit)
        return store, mgr

    def login(self, cred, store=None, mgr=None):
        if store is None:
            store, mgr = self.browser()
        mgr.establish(self.auth.authenticate(cred.username, cred.password))
        return store, mgr

    def chat(self, monkeypatch, store, mgr, prompt):
        """Run the real home-screen send path for the browser session owning ``store``."""
        monkeypatch.setattr(home_screen.st, "session_state", store)
        deps = SimpleNamespace(session=mgr, agent_client=self.client)
        answer = home_screen._ask_agent(deps, prompt)
        hist = home_screen._history()
        hist.append({"role": "user", "content": prompt})
        hist.append({"role": "assistant", "content": answer})
        return answer


@pytest.fixture(scope="module")
def data():
    return H.load_subset()


@pytest.fixture
def world(data):
    return World(data)


def test_SESS_01_four_concurrent_sessions_hold_separate_identities(world):
    """SESS-01 four users (one per role) in four stores: distinct tokens, own userid/role only."""
    sessions = {r: world.login(world.creds[r]) for r in H.ROLES}
    tokens = {r: s[0]["session_token"] for r, s in sessions.items()}
    assert len(set(tokens.values())) == 4
    for role, (store, mgr) in sessions.items():
        c = world.creds[role]
        view = mgr.require_valid_session()
        assert (view.userid, view.username, view.role) == (c.userid, c.username, role)
        assert store["session_token"] == tokens[role]
        assert world.tokens.verify(store["session_token"]).userid == c.userid
        assert c.password not in repr(store)
        assert UserContextProvider(mgr).current().role == role
    assert len({id(s[0]) for s in sessions.values()}) == 4


def test_SESS_02_chat_history_is_per_store(world, monkeypatch):
    """SESS-02 chat history and runtime session ids stay in the owner's store; backend keeps per-user history."""
    a, b = world.creds["SUPPLIER"], world.creds["TRANSPORT_OFFICE"]
    sa, ma = world.login(a)
    sb, mb = world.login(b)
    world.chat(monkeypatch, sa, ma, "secret-question-of-A")
    world.chat(monkeypatch, sb, mb, "question-of-B")
    world.chat(monkeypatch, sa, ma, "second-of-A")
    text_a, text_b = repr(sa[KEY_CHAT_HISTORY]), repr(sb[KEY_CHAT_HISTORY])
    assert "secret-question-of-A" in text_a and "second-of-A" in text_a and "question-of-B" not in text_a
    assert "question-of-B" in text_b and "of-A" not in text_b
    assert len(sa[KEY_CHAT_HISTORY]) == 4 and len(sb[KEY_CHAT_HISTORY]) == 2
    assert sa[KEY_CHAT_SESSION_ID] != sb[KEY_CHAT_SESSION_ID]
    assert len(sa[KEY_CHAT_SESSION_ID]) >= 33 and len(sb[KEY_CHAT_SESSION_ID]) >= 33
    # answers were produced for the right verified identity
    assert f"answer-for-{a.userid}:secret-question-of-A" in text_a
    assert f"answer-for-{b.userid}:" in text_b and a.userid not in text_b
    assert world.backend.history_by_userid == {a.userid: ["secret-question-of-A", "second-of-A"],
                                               b.userid: ["question-of-B"]}
    assert world.backend.session_ids.count(sa[KEY_CHAT_SESSION_ID]) == 2
    assert world.backend.session_ids.count(sb[KEY_CHAT_SESSION_ID]) == 1


def test_SESS_03_other_users_token_does_not_expose_history(world, monkeypatch):
    """SESS-03 history is reachable only through the owner's store; tokens/payloads carry no history."""
    a, b = world.creds["SUPPLIER"], world.creds["MATERIAL_RESPONSIBLE"]
    sa, ma = world.login(a)
    sb, mb = world.login(b)
    world.chat(monkeypatch, sa, ma, "private-A")
    world.chat(monkeypatch, sb, mb, "private-B")
    # every payload to the backend has only prompt + token; nothing of the stored history
    assert all(set(p) == {"prompt", "session_token"} for p in world.backend.requests)
    claims = jwt.decode(sa["session_token"], options={"verify_signature": False})
    assert "private-A" not in repr(claims) and set(claims) == {"uid", "usr", "role", "iat", "exp"}
    # a new browser session holding nothing (e.g. someone who only learned A's token) has no history / identity
    empty_store, empty_mgr = world.browser()
    with pytest.raises(SessionInvalid):
        empty_mgr.require_valid_session()
    with pytest.raises(NotAuthenticated):
        UserContextProvider(empty_mgr).current()
    assert KEY_CHAT_HISTORY not in empty_store
    # the client API has no way to fetch history for a token
    assert not [n for n in dir(AgentCoreClient) if "history" in n.lower()]
    assert not [n for n in dir(SessionManager) if "history" in n.lower() and not n.startswith("_")]
    # B's own view never contains A's data, even after A keeps chatting with A's token
    world.chat(monkeypatch, sa, ma, "more-private-A")
    assert "private-A" not in repr(sb) and "more-private-A" not in repr(sb)
    assert "private-B" not in repr(sa)


def test_SESS_04_logout_of_one_user_leaves_other_untouched(world, monkeypatch):
    """SESS-04 logout of A clears only A's store (incl. history) and audits once; B keeps working."""
    a, b = world.creds["SUPPLIER"], world.creds["TRANSPORT_OFFICE"]
    sa, ma = world.login(a)
    sb, mb = world.login(b)
    world.chat(monkeypatch, sa, ma, "hello-A")
    world.chat(monkeypatch, sb, mb, "hello-B")
    snapshot_b = repr(sb)
    ma.logout()
    assert sa == {} and not any(k in sa for k in SESSION_KEYS)
    assert repr(sb) == snapshot_b and mb.is_authenticated()
    assert world.audit.events.count(("logout", a.username)) == 1
    assert ("logout", b.username) not in world.audit.events
    assert "answer-for-" in world.chat(monkeypatch, sb, mb, "still-B")
    with pytest.raises(SessionInvalid):
        ma.require_valid_session()


def test_SESS_05_next_login_in_same_browser_starts_empty(world, monkeypatch):
    """SESS-05 user B logging in after A in the same browser store sees no history of A and a new runtime session."""
    a, b = world.creds["SUPPLIER"], world.creds["MATERIAL_RESPONSIBLE"]
    store, mgr = world.login(a)
    world.chat(monkeypatch, store, mgr, "A-was-here")
    old_sid = store[KEY_CHAT_SESSION_ID]
    old_token = store["session_token"]
    mgr.logout()
    world.login(b, store, mgr)
    assert KEY_CHAT_HISTORY not in store and "A-was-here" not in repr(store)
    assert store["session_token"] != old_token and store["userid"] == b.userid
    monkeypatch.setattr(home_screen.st, "session_state", store)
    assert home_screen._history() == [] and store[KEY_CHAT_SESSION_ID] != old_sid
    # even without logout, establishing a new identity wipes leftovers
    store[KEY_CHAT_HISTORY] = [{"role": "user", "content": "leftover"}]
    mgr.establish(world.auth.authenticate(a.username, a.password))
    assert "leftover" not in repr(store) and store["role"] == "SUPPLIER"


def test_SESS_06_role_claim_tampering_does_not_escalate(world, monkeypatch):
    """SESS-06 forged role claims: unsigned/re-signed payload rejected; validly signed ADMIN claim still acts as SUPPLIER."""
    sup, admin = world.creds["SUPPLIER"], world.creds["ADMIN"]
    store, mgr = world.login(sup)
    good = store["session_token"]
    head, _, sig = good.split(".")
    import base64, json  # noqa: E401

    def b64(o):
        return base64.urlsafe_b64encode(json.dumps(o, separators=(",", ":")).encode()).rstrip(b"=").decode()

    claims = {"uid": sup.userid, "usr": sup.username, "role": "ADMIN", "iat": int(T0.timestamp()),
              "exp": int(T0.timestamp()) + 1800}
    for bad in (f"{head}.{b64(claims)}.{sig}",  # payload changed, old signature
                jwt.encode(claims, "another-secret-0123456789abcdef", algorithm="HS256"),
                f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}."):
        store["session_token"] = bad
        with pytest.raises(AgentCoreUnauthorized):
            list(world.client.invoke(bad, "hi", "s" * 40))
    store["session_token"] = good
    # validly signed token that CLAIMS ADMIN
    forged = world.tokens.issue(sup.userid, sup.username, "ADMIN")
    assert world.tokens.verify(forged).role == "ADMIN"
    assert "".join(world.client.invoke(forged, "hi", "s" * 40)).startswith(f"answer-for-{sup.userid}")
    assert world.backend.role_seen[-1] == "SUPPLIER"  # backend re-read the role from the user store
    # the verified identity cannot use AdminService; the UI/session role stays what the store says
    with pytest.raises(PermissionDenied):
        world.admin.list_users(world.tokens.verify(forged).userid)
    with pytest.raises(PermissionDenied):
        world.admin.set_user_active(sup.userid, admin.userid, False)
    assert world.users.get_by_userid(admin.userid).active is True
    assert mgr.require_valid_session().role == "SUPPLIER" == world.users.get_by_userid(sup.userid).role
    assert world.admin.list_users(admin.userid)  # the real admin can


def test_SESS_07_idle_timeout_only_affects_idle_user(world, monkeypatch):
    """SESS-07 A idle for 30 min is cleared (audit: timeout); B that stayed active keeps its session/history."""
    a, b = world.creds["SUPPLIER"], world.creds["TRANSPORT_OFFICE"]
    sa, ma = world.login(a)
    sb, mb = world.login(b)
    world.chat(monkeypatch, sa, ma, "A-idle")
    world.chat(monkeypatch, sb, mb, "B-active")
    world.clock.advance(20 * 60)
    mb.touch()
    world.clock.advance(10 * 60)
    with pytest.raises(SessionInvalid) as exc:
        ma.require_valid_session()
    assert exc.value.reason == "idle_timeout" and sa == {}
    assert ("timeout", a.username) in world.audit.events
    assert mb.require_valid_session().userid == b.userid
    assert "B-active" in repr(sb[KEY_CHAT_HISTORY])


def test_SESS_08_deactivated_user_loses_backend_access_not_others(world, monkeypatch):
    """SESS-08 admin deactivates A: A's existing token is rejected by the backend, B unaffected."""
    a, b, admin = world.creds["SUPPLIER"], world.creds["TRANSPORT_OFFICE"], world.creds["ADMIN"]
    sa, ma = world.login(a)
    sb, mb = world.login(b)
    world.chat(monkeypatch, sa, ma, "before")
    world.admin.set_user_active(admin.userid, a.userid, False)
    with pytest.raises(AgentCoreUnauthorized):
        list(world.client.invoke(sa["session_token"], "after", "s" * 40))
    assert "answer-for-" in world.chat(monkeypatch, sb, mb, "B-still-ok")
