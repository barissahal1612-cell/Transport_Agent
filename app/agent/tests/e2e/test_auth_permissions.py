"""E2E: authentication + dynamic permissions (task 12.2). No AWS; real Excel auth sheets.

Check ids: AUTH-xx (login/token/logout/lockout), PERM-xx (permissions, admin, persistence, tamper).
Passwords come from the workbook at test time and are never printed or stored in any report.
"""
from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth_e2e_helpers as H  # noqa: E402  (also puts scripts/ and app/agent on sys.path)

import jwt  # noqa: E402
import main  # noqa: E402
from strands.models import Model  # noqa: E402

from agent_factory import build_agent, build_runtime  # noqa: E402
from identity import IdentityError, SessionTokenIdentityResolver  # noqa: E402
from logistic_ai_data.in_memory import InMemoryDataRepository  # noqa: E402
from logistic_ai_shared_auth.auth.errors import AuthError, AuthErrorKind  # noqa: E402
from logistic_ai_shared_auth.auth.session_token import SessionTokenError, SessionTokenService  # noqa: E402
from logistic_ai_shared_auth.auth.user_auth_service import UserAuthService  # noqa: E402
from logistic_ai_shared_auth.auth.users import DynamoUserRepository, InMemoryUserRepository  # noqa: E402
from logistic_ai_shared_auth.authorization.admin_service import AdminError, AdminService  # noqa: E402
from logistic_ai_shared_auth.authorization.authorizer import PermissionDenied  # noqa: E402
from logistic_ai_shared_auth.authorization.permission_service import PermissionService  # noqa: E402
from logistic_ai_shared_auth.authorization.permission_store import (  # noqa: E402
    DynamoPermissionRepository,
    InMemoryPermissionRepository,
    resource_key,
    role_subject,
    user_subject,
)
from logistic_ai_shared_auth.authorization.resources import FUNCTIONS, TABLES  # noqa: E402
from logistic_ai_shared_auth.common.clock import FixedClock  # noqa: E402
from tools import guard  # noqa: E402

sys.path.insert(0, str(H.ROOT / "streamlit_client"))
from logistic_ai.session.manager import KEY_CHAT_HISTORY, SESSION_KEYS, SessionManager  # noqa: E402

T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
GENERIC = AuthError(AuthErrorKind.INVALID_CREDENTIALS).user_message
FN = "get_delayed_truck"
TBL = H.FUNCTION_TABLE[FN]
NON_ADMIN = ("SUPPLIER", "MATERIAL_RESPONSIBLE", "TRANSPORT_OFFICE")


class Stack:
    """All services wired over a pair of repositories (one 'process')."""

    def __init__(self, users, perms, clock=None, audit=None):
        self.clock = clock or FixedClock(T0)
        self.audit = audit or H.RecordingAudit()
        self.admin_audit = H.RecordingAdminAudit()
        self.users, self.perms = users, perms
        self.tokens = SessionTokenService(H.FixedSecret(), self.clock)
        self.auth = UserAuthService(users, H.fast_hasher(), self.tokens, self.audit, self.clock)
        self.perm_service = PermissionService(users, perms, self.audit, self.clock)
        self.admin = AdminService(users, perms, self.perm_service, self.admin_audit, self.clock)


class ToolCallModel(Model):
    """Turn 1 calls ``tool_name``; turn 2 answers with text. No Bedrock."""

    def __init__(self, tool_name: str) -> None:
        self.tool_name, self.calls = tool_name, 0

    def update_config(self, **model_config: Any) -> None: ...

    def get_config(self) -> Any:
        return {}

    async def structured_output(self, *a: Any, **k: Any):  # pragma: no cover
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "t1", "name": self.tool_name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "ok"}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


class _Settings:
    idle_timeout_minutes = 30


@pytest.fixture(scope="module")
def data():
    return H.load_workbook_subset()


@pytest.fixture
def mem(data):
    subset, by_role, extras = data
    users, perms = InMemoryUserRepository(), InMemoryPermissionRepository()
    report = H.seed(subset, users, perms)
    assert report.counts("role_user").loaded == len(subset.auth_sheets["role_user"])
    st = Stack(users, perms)
    build_runtime(data_repo=InMemoryDataRepository(), user_repo=users, permission_repo=perms, audit=st.audit)
    # build_runtime made its own PermissionService; tests use st.perm_service via require_tool directly
    return st, by_role, extras


def _tool_ctx(userid: str):
    return type("Ctx", (), {"invocation_state": {"userid": userid}})()


def _guarded(st: Stack, userid: str, fn: str = FN) -> dict:
    """Run the real guard with the Stack's PermissionService and an empty data repo."""
    guard.set_runtime(InMemoryDataRepository(), st.perm_service)
    table = H.FUNCTION_TABLE[fn]
    return guard.guarded_call(
        function_name=fn, table=table, tool_context=_tool_ctx(userid),
        fetch=lambda repo: repo.get_all(table), shape=lambda rows: rows,
    )


def _ask_via_main(st: Stack, token: str, tool: str = FN) -> tuple[list, str]:
    """main.handle_request with a fake model calling ``tool``; returns (events, tool-result text)."""
    guard.set_runtime(InMemoryDataRepository(), st.perm_service)
    agent = build_agent(model=ToolCallModel(tool))
    services = main._Services(SessionTokenIdentityResolver(st.tokens), st.users, lambda messages=None: agent)
    events = H.collect(main.handle_request({"prompt": "hi", "session_token": token}, None, services))
    return events, str(agent.messages)


def _b64(obj: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=").decode()


# =========================================================================== AUTH
@pytest.mark.parametrize("role", H.ROLES)
def test_AUTH_01_successful_login_per_role(mem, role):
    """AUTH-01 login ok per role: session token issued; role verified from the store."""
    st, creds, _ = mem
    c = creds[role]
    s = st.auth.authenticate(c.username, c.password)
    assert s.role == role and s.userid == c.userid and s.username == c.username
    assert isinstance(s.token, str) and s.token.count(".") == 2
    verified = st.tokens.verify(s.token)
    assert (verified.userid, verified.username) == (c.userid, c.username)
    assert st.users.get_by_userid(verified.userid).role == role
    assert ("login", c.username, True) in st.audit.events
    assert c.password not in s.token and c.password not in repr(s)


def test_AUTH_02_passwords_stored_hashed_only(mem):
    """AUTH-02 stored password is an Argon2id hash, never the plaintext."""
    st, creds, _ = mem
    for c in creds.values():
        rec = st.users.get_by_username(c.username)
        assert rec.password_hash.startswith("$argon2id$")
        assert c.password not in rec.password_hash and c.password not in repr(rec)


def test_AUTH_03_wrong_password_identical_to_unknown_user(mem):
    """AUTH-03 wrong password == unknown user (generic error, same kind/message)."""
    st, creds, _ = mem
    c = creds["SUPPLIER"]
    with pytest.raises(AuthError) as wrong:
        st.auth.authenticate(c.username, c.password + "x")
    with pytest.raises(AuthError) as unknown:
        st.auth.authenticate("no-such-user-zz", "whatever-pass")
    assert wrong.value.kind is unknown.value.kind is AuthErrorKind.INVALID_CREDENTIALS
    assert wrong.value.user_message == unknown.value.user_message == GENERIC
    assert str(wrong.value) == str(unknown.value) and c.username not in str(wrong.value)
    assert [e for e in st.audit.events if e[0] == "login"] == [
        ("login", c.username, False), ("login", "no-such-user-zz", False)]


def test_AUTH_04_inactive_user_cannot_login(mem):
    """AUTH-04 inactive user (even with the correct password) gets the same generic error."""
    st, creds, _ = mem
    c = creds["MATERIAL_RESPONSIBLE"]
    assert st.users.set_active(c.username, False)
    with pytest.raises(AuthError) as exc:
        st.auth.authenticate(c.username, c.password)
    assert exc.value.kind is AuthErrorKind.INVALID_CREDENTIALS and exc.value.user_message == GENERIC
    assert ("login", c.username, True) not in st.audit.events


def _tokens_for_invalid(st: Stack, c: H.Cred) -> dict[str, str]:
    good = st.tokens.issue(c.userid, c.username, c.role)
    h, p, s = good.split(".")
    claims = {"uid": c.userid, "usr": c.username, "role": "ADMIN", "iat": int(T0.timestamp()),
              "exp": int(T0.timestamp()) + 1800}
    return {
        "garbage": "not-a-token",
        "empty": "",
        "two-parts": f"{h}.{p}",
        "wrong-signature": jwt.encode(claims, "another-secret-0123456789abcdef", algorithm="HS256"),
        "alg-none": f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}.",
        "alg-none-with-sig": f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}.{s}",
        "other-alg-HS384": jwt.encode(claims, H.SECRET, algorithm="HS384"),
        "payload-tampered": f"{h}.{_b64(claims)}.{s}",
    }


@pytest.mark.parametrize(
    "kind",
    ["garbage", "empty", "two-parts", "wrong-signature", "alg-none", "alg-none-with-sig",
     "other-alg-HS384", "payload-tampered"],
)
def test_AUTH_05_invalid_token_rejected(mem, kind):
    """AUTH-05 invalid token ({kind}) rejected by verify, IdentityResolver and main flow."""
    st, creds, _ = mem
    c = creds["SUPPLIER"]
    token = _tokens_for_invalid(st, c)[kind]
    with pytest.raises(SessionTokenError):
        st.tokens.verify(token)
    with pytest.raises(IdentityError):
        SessionTokenIdentityResolver(st.tokens).resolve(None, {"session_token": token or " "})
    if token:
        events, _ = _ask_via_main(st, token)
        assert events == [{"error": "unauthenticated", "message": main.UNAUTHENTICATED_MESSAGE}]


def test_AUTH_06_expired_token_rejected_after_30_min(mem):
    """AUTH-06 token valid at 29m59s, rejected at 30m (FixedClock) incl. main flow."""
    st, creds, _ = mem
    c = creds["TRANSPORT_OFFICE"]
    token = st.auth.authenticate(c.username, c.password).token
    st.clock.advance(30 * 60 - 1)
    assert st.tokens.verify(token).userid == c.userid
    st.clock.advance(1)
    with pytest.raises(SessionTokenError):
        st.tokens.verify(token)
    events, _ = _ask_via_main(st, token)
    assert events[0]["error"] == "unauthenticated"
    st.clock.advance(60 * 60)
    with pytest.raises(SessionTokenError):
        st.tokens.verify(token)


def test_AUTH_07_logout_audit_and_session_cleared(mem):
    """AUTH-07 logout writes audit call and SessionManager clears every session key."""
    st, creds, _ = mem
    c = creds["SUPPLIER"]
    store: dict = {}
    mgr = SessionManager(store, st.auth, _Settings(), st.clock, st.audit)
    mgr.establish(st.auth.authenticate(c.username, c.password))
    store[KEY_CHAT_HISTORY] = [{"role": "user", "content": "hi"}]
    assert mgr.is_authenticated() and mgr.require_valid_session().role == "SUPPLIER"
    mgr.logout()
    assert not any(k in store for k in SESSION_KEYS) and store == {}
    assert not mgr.is_authenticated()
    assert st.audit.events.count(("logout", c.username)) == 1
    mgr.logout()  # second logout is a harmless no-op
    assert st.audit.events.count(("logout", c.username)) == 1


def test_AUTH_08_lockout_after_5_failures_unlock_after_15_min(mem):
    """AUTH-08 5 wrong passwords lock; correct password refused while locked; ok at +15 min."""
    st, creds, extras = mem
    c, other = creds["SUPPLIER"], creds["ADMIN"]
    for _ in range(4):
        with pytest.raises(AuthError):
            st.auth.authenticate(c.username, c.password + "x")
    assert st.users.get_by_username(c.username).locked_until is None
    with pytest.raises(AuthError):
        st.auth.authenticate(c.username, c.password + "x")  # 5th failure -> locked
    assert st.users.get_by_username(c.username).locked_until is not None
    assert ("lockout", c.username) in st.audit.events
    with pytest.raises(AuthError) as locked:  # correct password but locked: same generic error
        st.auth.authenticate(c.username, c.password)
    assert locked.value.kind is AuthErrorKind.INVALID_CREDENTIALS and locked.value.user_message == GENERIC
    assert st.auth.authenticate(other.username, other.password).role == "ADMIN"  # others unaffected
    st.clock.advance(15 * 60 - 1)
    with pytest.raises(AuthError):
        st.auth.authenticate(c.username, c.password)
    st.clock.advance(1)
    s = st.auth.authenticate(c.username, c.password)
    assert s.userid == c.userid
    rec = st.users.get_by_username(c.username)
    assert rec.failed_count == 0 and rec.locked_until is None


def test_AUTH_09_counter_restarts_after_unlock(mem):
    """AUTH-09 after the lock expires a fresh budget of 5 failures applies; success resets the counter."""
    st, creds, _ = mem
    c = creds["MATERIAL_RESPONSIBLE"]
    for _ in range(5):
        with pytest.raises(AuthError):
            st.auth.authenticate(c.username, c.password + "x")
    st.clock.advance(15 * 60)
    with pytest.raises(AuthError):  # first failure after expiry: not locked yet
        st.auth.authenticate(c.username, c.password + "x")
    assert st.users.get_by_username(c.username).failed_count == 1
    assert st.auth.authenticate(c.username, c.password).userid == c.userid
    assert st.users.get_by_username(c.username).failed_count == 0


# ============================================================ PERMISSIONS: defaults
@pytest.mark.parametrize("role", H.ROLES)
def test_PERM_01_initial_access_to_all_tables_and_functions(mem, role):
    """PERM-01 {role} initially may use all 7 tables and 6 functions (check + require_tool)."""
    st, creds, _ = mem
    uid = creds[role].userid
    assert len(TABLES) == 7 and len(FUNCTIONS) == 6
    for t in TABLES:
        assert st.perm_service.check(uid, "TABLE", t).allowed, t
    for f in FUNCTIONS:
        assert st.perm_service.check(uid, "FUNCTION", f).allowed, f
        st.perm_service.require_tool(uid, f, [H.FUNCTION_TABLE[f]])  # must not raise
        assert _guarded(st, uid, f)["status"] == "not_found"  # allowed; empty data repo


def test_PERM_02_auth_tables_and_unknown_resources_denied(mem):
    """PERM-02 deny-by-default: auth tables / unknown resources are never allowed, even for ADMIN."""
    st, creds, _ = mem
    uid = creds["ADMIN"].userid
    for res in ("role_user", "permissions", "no_such_table"):
        assert not st.perm_service.check(uid, "TABLE", res).allowed
    assert not st.perm_service.check(uid, "FUNCTION", "no_such_function").allowed
    assert not st.perm_service.check("UNKNOWN-ID", "TABLE", "question1").allowed


# ===================================================== PERMISSIONS: admin changes
def test_PERM_03_admin_removes_function_permission_then_regrants(mem):
    """PERM-03 admin removes FUNCTION perm for a role -> PermissionDenied/forbidden; re-grant -> works."""
    st, creds, _ = mem
    admin, sup, mat = creds["ADMIN"], creds["SUPPLIER"], creds["MATERIAL_RESPONSIBLE"]
    assert _guarded(st, sup.userid)["status"] == "not_found"  # populates the permission cache
    st.admin.remove_permission(admin.userid, "ROLE", "SUPPLIER", "FUNCTION", FN)
    with pytest.raises(PermissionDenied):  # immediate: AdminService invalidates the cache
        st.perm_service.require_tool(sup.userid, FN, [TBL])
    assert _guarded(st, sup.userid)["status"] == "forbidden"
    assert _guarded(st, sup.userid, "get_truck_location")["status"] == "not_found"  # other function intact
    assert _guarded(st, mat.userid)["status"] == "not_found"  # other role intact
    assert any(e[0] == "denied" and e[3] == f"FUNCTION:{FN}" for e in st.audit.events)
    st.admin.set_permission(admin.userid, "ROLE", "SUPPLIER", "FUNCTION", FN, True)
    st.perm_service.require_tool(sup.userid, FN, [TBL])
    assert _guarded(st, sup.userid)["status"] == "not_found"
    actions = [(r["action"], r["outcome"]) for r in st.admin_audit.records]
    assert actions == [("remove_permission", "ok"), ("set_permission", "ok")]


def test_PERM_04_explicit_deny_and_table_deny(mem):
    """PERM-04 allowed=False (function) and removed TABLE permission both block the tool."""
    st, creds, _ = mem
    admin, tr = creds["ADMIN"], creds["TRANSPORT_OFFICE"]
    st.admin.set_permission(admin.userid, "ROLE", "TRANSPORT_OFFICE", "FUNCTION", FN, False)
    assert _guarded(st, tr.userid)["status"] == "forbidden"
    st.admin.set_permission(admin.userid, "ROLE", "TRANSPORT_OFFICE", "FUNCTION", FN, True)
    assert _guarded(st, tr.userid)["status"] == "not_found"
    st.admin.remove_permission(admin.userid, "ROLE", "TRANSPORT_OFFICE", "TABLE", TBL)
    assert _guarded(st, tr.userid)["status"] == "forbidden"
    with pytest.raises(AdminError):  # auth tables can never be granted
        st.admin.set_permission(admin.userid, "ROLE", "SUPPLIER", "TABLE", "role_user", True)


def test_PERM_05_user_level_override_affects_only_that_user(mem):
    """PERM-05 USER-level deny blocks one supplier only; removing it restores access."""
    st, creds, extras = mem
    admin, s1, s2 = creds["ADMIN"], creds["SUPPLIER"], extras[0]
    st.admin.set_permission(admin.userid, "USER", s2.userid, "FUNCTION", FN, False)
    assert _guarded(st, s2.userid)["status"] == "forbidden"
    assert _guarded(st, s1.userid)["status"] == "not_found"
    st.admin.remove_permission(admin.userid, "USER", s2.userid, "FUNCTION", FN)
    assert _guarded(st, s2.userid)["status"] == "not_found"



# ============================================================ ADMIN SERVICE guard
ADMIN_CALLS = {
    "set_user_active": lambda a, actor, tgt: a.set_user_active(actor, tgt, False),
    "set_permission": lambda a, actor, tgt: a.set_permission(actor, "ROLE", "SUPPLIER", "FUNCTION", FN, False),
    "remove_permission": lambda a, actor, tgt: a.remove_permission(actor, "ROLE", "SUPPLIER", "FUNCTION", FN),
    "list_users": lambda a, actor, tgt: a.list_users(actor),
    "list_permissions": lambda a, actor, tgt: a.list_permissions(actor, "ROLE", "SUPPLIER"),
}


def _snapshot(st: Stack) -> tuple:
    perms = tuple((e.subject, e.resource, e.allowed) for r in H.ROLES for e in st.perms.list_for_subject(f"ROLE#{r}"))
    users = tuple(sorted((u.userid, u.active) for u in st.users.list_users()))
    return perms, users


@pytest.mark.parametrize("method", list(ADMIN_CALLS))
@pytest.mark.parametrize("role", NON_ADMIN)
def test_PERM_06_non_admin_cannot_use_admin_service(mem, role, method):
    """PERM-06 {role} calling AdminService.{method} -> PermissionDenied, no state change."""
    st, creds, extras = mem
    before = _snapshot(st)
    with pytest.raises(PermissionDenied):
        ADMIN_CALLS[method](st.admin, creds[role].userid, extras[0].userid)
    assert _snapshot(st) == before
    assert st.admin_audit.records[-1]["outcome"] == "denied"


@pytest.mark.parametrize("actor", ["UNKNOWN-ID", "", None])
def test_PERM_07_unknown_actor_and_inactive_admin_denied(mem, actor):
    """PERM-07 unknown/empty actor and a deactivated ADMIN are denied for every admin method."""
    st, creds, extras = mem
    for call in ADMIN_CALLS.values():
        with pytest.raises(PermissionDenied):
            call(st.admin, actor, extras[0].userid)
    st.users.set_active(creds["ADMIN"].username, False)
    for call in ADMIN_CALLS.values():
        with pytest.raises(PermissionDenied):
            call(st.admin, creds["ADMIN"].userid, extras[0].userid)


def test_PERM_08_admin_cannot_deactivate_self_but_can_deactivate_others(mem):
    """PERM-08 ADMIN self-deactivation refused; deactivating another user blocks login; reactivation restores."""
    st, creds, extras = mem
    admin, victim = creds["ADMIN"], extras[0]
    with pytest.raises(AdminError):
        st.admin.set_user_active(admin.userid, admin.userid, False)
    assert st.users.get_by_userid(admin.userid).active is True
    assert st.auth.authenticate(admin.username, admin.password).role == "ADMIN"
    st.admin.set_user_active(admin.userid, victim.userid, False)
    with pytest.raises(AuthError):
        st.auth.authenticate(victim.username, victim.password)
    assert _guarded(st, victim.userid)["status"] == "forbidden"  # inactive -> denied by PermissionService
    st.admin.set_user_active(admin.userid, victim.userid, True)
    assert st.auth.authenticate(victim.username, victim.password).userid == victim.userid
    assert _guarded(st, victim.userid)["status"] == "not_found"
    users = {u.username: u for u in st.admin.list_users(admin.userid)}
    assert all(not hasattr(u, "password_hash") for u in users.values())


# ============================================================ PERSISTENCE (fake DynamoDB)
class _Cluster:
    """Two fake tables shared by successive 'process' instances (restarts)."""

    def __init__(self, data):
        self.users_tbl, self.perms_tbl = H.users_table(), H.permissions_table()
        self.subset, self.creds, self.extras = data
        self.report = H.seed(self.subset, self.users_repo(), self.perms_repo())

    def users_repo(self):
        return DynamoUserRepository(self.users_tbl)

    def perms_repo(self):
        return DynamoPermissionRepository(self.perms_tbl)

    def boot(self, clock=None) -> Stack:
        return Stack(self.users_repo(), self.perms_repo(), clock)


@pytest.fixture
def cluster(data):
    return _Cluster(data)


def test_PERM_09_fake_dynamodb_seeded_from_excel(cluster):
    """PERM-09 seed via Dynamo adapters: all users/permissions stored, hashes only, conditional put works."""
    n_users = len(cluster.subset.auth_sheets["role_user"])
    assert cluster.report.counts("role_user").loaded == n_users
    assert cluster.report.counts("permissions").loaded == 52  # (7 tables + 6 functions) x 4 roles
    assert len(cluster.users_tbl._items) == n_users and len(cluster.perms_tbl._items) == 52
    for c in cluster.creds.values():
        item = cluster.users_tbl.get_item(Key={"USERNAME": c.username})["Item"]
        assert item["password_hash"].startswith("$argon2id$") and c.password not in json.dumps(item, default=str)
    st = cluster.boot()
    # seeding twice must not overwrite (conditional put): all rows are reported as already existing
    again = H.seed(cluster.subset, st.users, st.perms)
    assert again.counts("role_user").loaded == 0 and again.counts("permissions").loaded == 0
    assert st.users.put_user(st.users.get_by_username(cluster.creds["ADMIN"].username)) is False
    assert st.perms.put(role_subject("SUPPLIER"), resource_key("FUNCTION", FN), False, "x", create_only=True) is False
    assert st.perms.get(role_subject("SUPPLIER"), resource_key("FUNCTION", FN)) is True


def test_PERM_10_permission_and_user_changes_survive_restart(cluster):
    """PERM-10 admin changes persist in the table and are seen by fresh service instances (restart)."""
    c = cluster.creds
    victim = cluster.extras[0]
    a = cluster.boot()
    assert _guarded(a, c["SUPPLIER"].userid)["status"] == "not_found"
    token_before = a.auth.authenticate(c["SUPPLIER"].username, c["SUPPLIER"].password).token
    a.admin.remove_permission(c["ADMIN"].userid, "ROLE", "SUPPLIER", "FUNCTION", FN)
    a.admin.set_permission(c["ADMIN"].userid, "ROLE", "TRANSPORT_OFFICE", "FUNCTION", "get_truck_location", False)
    a.admin.set_permission(c["ADMIN"].userid, "USER", c["MATERIAL_RESPONSIBLE"].userid, "TABLE", "question5", False)
    a.admin.set_user_active(c["ADMIN"].userid, victim.userid, False)

    b = cluster.boot()  # "restart": new repos, new PermissionService, empty caches
    assert b.perm_service is not a.perm_service
    with pytest.raises(PermissionDenied):
        b.perm_service.require_tool(c["SUPPLIER"].userid, FN, [TBL])
    assert _guarded(b, c["SUPPLIER"].userid)["status"] == "forbidden"
    assert _guarded(b, c["TRANSPORT_OFFICE"].userid, "get_truck_location")["status"] == "forbidden"
    assert _guarded(b, c["MATERIAL_RESPONSIBLE"].userid, "get_truck_tobearrived")["status"] == "forbidden"
    assert _guarded(b, c["MATERIAL_RESPONSIBLE"].userid, "get_truck_location")["status"] == "not_found"
    with pytest.raises(AuthError):
        b.auth.authenticate(victim.username, victim.password)
    assert b.perms.get(role_subject("SUPPLIER"), resource_key("FUNCTION", FN)) is None
    assert b.perms.get(role_subject("TRANSPORT_OFFICE"), resource_key("FUNCTION", "get_truck_location")) is False
    assert b.perms.get(user_subject(c["MATERIAL_RESPONSIBLE"].userid), resource_key("TABLE", "question5")) is False
    row = cluster.perms_tbl.get_item(Key={"SUBJECT": "ROLE#TRANSPORT_OFFICE", "RESOURCE": "FUNCTION#get_truck_location"})["Item"]
    assert row["updated_by"] == c["ADMIN"].userid and row["allowed"] is False
    assert b.tokens.verify(token_before).userid == c["SUPPLIER"].userid  # stateless token survives restart
    # re-seeding must not undo the admin's decisions
    H.seed(cluster.subset, b.users, b.perms)
    assert b.perms.get(role_subject("TRANSPORT_OFFICE"), resource_key("FUNCTION", "get_truck_location")) is False

    b.admin.set_permission(c["ADMIN"].userid, "ROLE", "SUPPLIER", "FUNCTION", FN, True)
    b.admin.set_user_active(c["ADMIN"].userid, victim.userid, True)
    d = cluster.boot()  # second restart
    d.perm_service.require_tool(c["SUPPLIER"].userid, FN, [TBL])
    assert _guarded(d, c["SUPPLIER"].userid)["status"] == "not_found"
    assert d.auth.authenticate(victim.username, victim.password).userid == victim.userid


def test_PERM_11_login_roles_and_lockout_persist_across_instances(cluster):
    """PERM-11 Dynamo-backed login for 4 roles; lockout state (Decimal) shared across instances; unlock at +15 min."""
    clock = FixedClock(T0)
    a, b = cluster.boot(clock), cluster.boot(clock)
    for role, c in cluster.creds.items():
        s = a.auth.authenticate(c.username, c.password)
        assert s.role == role and b.tokens.verify(s.token).userid == c.userid
    c = cluster.creds["SUPPLIER"]
    for i in range(5):
        with pytest.raises(AuthError):
            (a if i % 2 == 0 else b).auth.authenticate(c.username, c.password + "x")
    with pytest.raises(AuthError):  # instance b sees the lock written by a
        b.auth.authenticate(c.username, c.password)
    clock.advance(15 * 60)
    assert cluster.boot(clock).auth.authenticate(c.username, c.password).userid == c.userid
    assert cluster.users_repo().get_by_username(c.username).failed_count == 0


def test_PERM_12_fake_dynamodb_rejects_floats_like_boto3():
    """PERM-12 fidelity check of the fake: floats rejected, conditional put raises ConditionalCheckFailed."""
    from botocore.exceptions import ClientError

    t = H.permissions_table()
    t.put_item(Item={"SUBJECT": "s", "RESOURCE": "r", "allowed": True}, ConditionExpression="attribute_not_exists(SUBJECT)")
    with pytest.raises(ClientError) as e:
        t.put_item(Item={"SUBJECT": "s", "RESOURCE": "r", "allowed": False}, ConditionExpression="attribute_not_exists(SUBJECT)")
    assert e.value.response["Error"]["Code"] == "ConditionalCheckFailedException"
    with pytest.raises(TypeError):
        t.put_item(Item={"SUBJECT": "s", "RESOURCE": "r2", "x": 1.5})
    assert t.get_item(Key={"SUBJECT": "s", "RESOURCE": "r"})["Item"]["allowed"] is True


# ============================================================ MAIN FLOW / TAMPERING
def test_PERM_13_main_flow_forbidden_after_removal_and_regrant(mem):
    """PERM-13 main.handle_request: tool says forbidden after admin removal, works after re-grant."""
    st, creds, _ = mem
    sup, admin = creds["SUPPLIER"], creds["ADMIN"]
    token = st.auth.authenticate(sup.username, sup.password).token
    events, text = _ask_via_main(st, token)
    assert events and "not_found" in text and "forbidden" not in text
    st.admin.remove_permission(admin.userid, "ROLE", "SUPPLIER", "FUNCTION", FN)
    events, text = _ask_via_main(st, token)
    assert events and "forbidden" in text and "not_found" not in text
    st.admin.set_permission(admin.userid, "ROLE", "SUPPLIER", "FUNCTION", FN, True)
    events, text = _ask_via_main(st, token)
    assert "not_found" in text and "forbidden" not in text


def test_PERM_14_role_claim_in_token_does_not_escalate(mem):
    """PERM-14 a validly signed token whose role claim says ADMIN gives a SUPPLIER no extra rights."""
    st, creds, _ = mem
    sup, admin = creds["SUPPLIER"], creds["ADMIN"]
    forged = st.tokens.issue(sup.userid, sup.username, "ADMIN")  # claim says ADMIN
    assert st.tokens.verify(forged).role == "ADMIN"  # the claim is there ...
    assert st.users.get_by_userid(sup.userid).role == "SUPPLIER"  # ... but the store decides
    st.admin.remove_permission(admin.userid, "ROLE", "SUPPLIER", "FUNCTION", FN)
    _, text = _ask_via_main(st, forged)
    assert "forbidden" in text and "not_found" not in text  # still treated as SUPPLIER
    with pytest.raises(PermissionDenied):  # the verified userid is not an admin
        st.admin.set_permission(st.tokens.verify(forged).userid, "ROLE", "SUPPLIER", "FUNCTION", FN, True)
    with pytest.raises(PermissionDenied):
        st.admin.list_users(st.tokens.verify(forged).userid)
    # same call with the real admin's own token still reaches the tool (role perms untouched)
    _, text_admin = _ask_via_main(st, st.auth.authenticate(admin.username, admin.password).token)
    assert "not_found" in text_admin


def test_PERM_15_token_of_unknown_or_inactive_user_rejected_by_backend(mem):
    """PERM-15 correctly signed tokens for unknown / deactivated users are rejected (no tool call)."""
    st, creds, extras = mem
    admin, victim = creds["ADMIN"], extras[0]
    ghost = st.tokens.issue("NO-SUCH-USER", "ghost", "ADMIN")
    live = st.tokens.issue(victim.userid, victim.username, victim.role)
    st.admin.set_user_active(admin.userid, victim.userid, False)
    for token in (ghost, live):
        events, text = _ask_via_main(st, token)
        assert events == [{"error": "unauthenticated", "message": main.UNAUTHENTICATED_MESSAGE}]
        assert "toolUse" not in text
