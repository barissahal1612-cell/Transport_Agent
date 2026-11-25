"""Scripted local end-to-end flow through the SAME code path the Streamlit client uses.

UserAuthService (login) -> AgentCoreClient + LocalHttpTransport -> local ``agentcore dev``,
and AdminService (remove / re-grant a function permission) against the local moto DynamoDB.

Refuses to run unless AWS_ENDPOINT_URL_DYNAMODB and LOGISTIC_AI_LOCAL_AGENT_URL are loopback.
Passwords come from the Excel file at run time and are never printed.

Run from ``streamlit_client/``:
    uv run --with openpyxl python ../scripts/local/e2e_local_flow.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "streamlit_client"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from create_local_tables import local_endpoint_or_none  # noqa: E402

EXCEL = ROOT / "Data" / "Agent_AWS_2026-11-24.xlsx"
QUESTION = "Hangi tırlar geç kaldı?"
CACHE_WAIT_S = 32  # backend PermissionService caches decisions for up to 30 s


def _pick_users() -> dict[str, tuple[str, str]]:
    """First active user of the wanted roles: role -> (username, password)."""
    import openpyxl

    ws = openpyxl.load_workbook(EXCEL, read_only=True)["role_user"]
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))
    ix = {name: header.index(name) for name in ("ROLE", "USERNAME", "Password")}
    out: dict[str, tuple[str, str]] = {}
    for r in rows:
        role = str(r[ix["ROLE"]]).strip()
        if role in ("TRANSPORT_OFFICE", "ADMIN") and role not in out and r[ix["USERNAME"]] and r[ix["Password"]]:
            pw = r[ix["Password"]]
            out[role] = (str(r[ix["USERNAME"]]).strip(), str(pw).strip())
    return out


def _ask(client, session, prompt: str, sid: str) -> str:
    return "".join(client.invoke(session.token, prompt, sid))


def main() -> int:
    if local_endpoint_or_none(os.environ) is None:
        print("REFUSED: AWS_ENDPOINT_URL_DYNAMODB must be loopback", file=sys.stderr)
        return 2
    url = os.environ.get("LOGISTIC_AI_LOCAL_AGENT_URL", "")
    from logistic_ai.config.settings import ConfigError, load_settings

    try:
        settings = load_settings(os.environ)
    except ConfigError as exc:
        print(f"Config error: {exc.missing}", file=sys.stderr)
        return 2
    if not settings.local_agent_url:
        print("REFUSED: LOGISTIC_AI_LOCAL_AGENT_URL not set", file=sys.stderr)
        return 2

    from logistic_ai.config.secrets import build_secret_provider
    from logistic_ai.session.agentcore_client import AgentCoreClient, LocalHttpTransport
    from logistic_ai_shared_auth.auth.passwords import PasswordHasher
    from logistic_ai_shared_auth.auth.session_token import SessionTokenService
    from logistic_ai_shared_auth.auth.user_auth_service import UserAuthService
    from logistic_ai_shared_auth.auth.users import DynamoUserRepository
    from logistic_ai_shared_auth.authorization.admin_service import ROLE, AdminService
    from logistic_ai_shared_auth.authorization.permission_service import PermissionService
    from logistic_ai_shared_auth.authorization.permission_store import DynamoPermissionRepository
    from logistic_ai_shared_auth.authorization.resources import FUNCTION
    from logistic_ai_shared_auth.common.audit import JsonAuditLogger
    from logistic_ai_shared_auth.common.clock import SystemClock

    clock = SystemClock()
    audit = JsonAuditLogger(clock=clock)
    users, perms = DynamoUserRepository(), DynamoPermissionRepository()
    psvc = PermissionService(users, perms, audit, clock)
    admin_svc = AdminService(users, perms, psvc, clock=clock)
    tokens = SessionTokenService(build_secret_provider(os.environ, settings.aws_region), clock)
    auth = UserAuthService(users, PasswordHasher(), tokens, audit, clock)
    client = AgentCoreClient("", settings.aws_region, settings=settings, http=LocalHttpTransport(url))

    creds = _pick_users()
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}".rstrip())

    user = auth.authenticate(*creds["TRANSPORT_OFFICE"])
    admin = auth.authenticate(*creds["ADMIN"])
    check("login TRANSPORT_OFFICE", user.role == "TRANSPORT_OFFICE", f"role={user.role}")
    check("login ADMIN", admin.role == "ADMIN", f"role={admin.role}")

    sid = "local-e2e-session-transport-office-0001"
    a1 = _ask(client, user, QUESTION, sid)
    print("  answer(1, first 300):", a1[:300].replace("\n", " "))
    check("ok: delayed trucks answered", bool(a1.strip()) and "yetkiniz yok" not in a1.lower())

    admin_svc.remove_permission(admin.userid, ROLE, "TRANSPORT_OFFICE", FUNCTION, "get_delayed_truck")
    print(f"  removed FUNCTION#get_delayed_truck from ROLE#TRANSPORT_OFFICE; waiting {CACHE_WAIT_S}s (cache TTL)")
    time.sleep(CACHE_WAIT_S)
    a2 = _ask(client, user, QUESTION, sid + "-b")
    print("  answer(2, first 300):", a2[:300].replace("\n", " "))
    check("forbidden after removal", "yetki" in a2.lower())

    admin_svc.set_permission(admin.userid, ROLE, "TRANSPORT_OFFICE", FUNCTION, "get_delayed_truck", True)
    print(f"  re-granted; waiting {CACHE_WAIT_S}s")
    time.sleep(CACHE_WAIT_S)
    a3 = _ask(client, user, QUESTION, sid + "-c")
    print("  answer(3, first 300):", a3[:300].replace("\n", " "))
    check("ok after re-grant", bool(a3.strip()) and "yetkiniz yok" not in a3.lower())

    auth.logout(user.userid, user.username)
    auth.logout(admin.userid, admin.username)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
