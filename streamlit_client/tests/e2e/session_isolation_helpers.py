"""Helpers for the session-isolation E2E tests (task 12.2).

Seeds in-memory repositories from the REAL Excel auth sheets (subset of users, fast Argon2 params).
Real passwords are held in ``Cred`` objects whose repr hides them; nothing is printed or written.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]  # .../Logistic_AI
for _p in (ROOT / "scripts", ROOT / "streamlit_client"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from argon2 import PasswordHasher as _Argon2  # noqa: E402

from ingest.excel_reader import WorkbookData, read_workbook  # noqa: E402
from ingest.seed import _text, seed_workbook  # noqa: E402
from logistic_ai_shared_auth.auth.passwords import PasswordHasher  # noqa: E402

EXCEL = ROOT / "Data" / "Agent_AWS_2026-11-24.xlsx"
ROLES = ("SUPPLIER", "MATERIAL_RESPONSIBLE", "TRANSPORT_OFFICE", "ADMIN")
SECRET = "e2e-session-secret-0123456789abcdef"


def fast_hasher() -> PasswordHasher:
    return PasswordHasher(_Argon2(time_cost=1, memory_cost=8, parallelism=1))


class Cred:
    def __init__(self, role: str, userid: str, username: str, password: str) -> None:
        self.role, self.userid, self.username = role, userid, username
        self._password = password

    @property
    def password(self) -> str:
        return self._password

    def __repr__(self) -> str:
        return f"Cred(role={self.role!r}, username={self.username!r})"

    __str__ = __repr__


def load_subset(extra_suppliers: int = 1) -> tuple[WorkbookData, dict[str, Cred], list[Cred]]:
    wb = read_workbook(EXCEL)
    chosen: list[dict[str, Any]] = []
    by_role: dict[str, Cred] = {}
    extras: list[Cred] = []
    for row in wb.auth_sheets["role_user"]:
        role = _text(row.get("ROLE"))
        cred = Cred(role, _text(row["USERID"]), _text(row["USERNAME"]), _text(row.get("Password")))
        if role in ROLES and role not in by_role:
            by_role[role] = cred
            chosen.append(row)
        elif role == "SUPPLIER" and len(extras) < extra_suppliers:
            extras.append(cred)
            chosen.append(row)
    assert set(by_role) == set(ROLES), "workbook lacks a user for some role"
    subset = WorkbookData(
        sheets={}, columns={},
        auth_sheets={"role_user": chosen, "permissions": wb.auth_sheets["permissions"]},
        report=wb.report,
    )
    return subset, by_role, extras


def seed(subset: WorkbookData, users: Any, perms: Any):
    return seed_workbook(subset, apply=True, user_repo=users, permission_repo=perms, hasher=fast_hasher())


@dataclass
class RecordingAudit:
    events: list[tuple] = field(default_factory=list)

    def log_login(self, username, success):
        self.events.append(("login", username, bool(success)))

    def log_logout(self, username):
        self.events.append(("logout", username))

    def log_session_timeout(self, username):
        self.events.append(("timeout", username))

    def log_authorization_denied(self, username, role, permission):
        self.events.append(("denied", username, role, permission))

    def log_lockout(self, username):
        self.events.append(("lockout", username))


class FixedSecret:
    def get_secret(self) -> str:
        return SECRET


class Settings:
    idle_timeout_minutes = 30


class FakeBackend:
    """Stands in for the AgentCore runtime: verifies the token, keeps history per VERIFIED user,
    and re-reads the role from the user store (never from the token claim)."""

    def __init__(self, tokens: Any, users: Any) -> None:
        self.tokens, self.users = tokens, users
        self.requests: list[dict] = []  # decoded payloads as received
        self.session_ids: list[str] = []
        self.history_by_userid: dict[str, list[str]] = {}
        self.role_seen: list[str] = []

    # HttpTransport protocol of AgentCoreClient
    def invoke(self, runtime_arn: str, session_id: str, body: bytes, timeout: float):
        from logistic_ai.session.agentcore_client import HttpResponse

        payload = json.loads(body)
        self.requests.append(payload)
        self.session_ids.append(session_id)
        try:
            verified = self.tokens.verify(payload["session_token"])
        except Exception:  # noqa: BLE001
            return HttpResponse(status_code=200, lines=["data: " + json.dumps({"error": "unauthenticated", "message": "m"})])
        user = self.users.get_by_userid(verified.userid)
        if user is None or not user.active:
            return HttpResponse(status_code=200, lines=["data: " + json.dumps({"error": "unauthenticated", "message": "m"})])
        self.role_seen.append(user.role)
        self.history_by_userid.setdefault(user.userid, []).append(payload["prompt"])
        text = f"answer-for-{user.userid}:{payload['prompt']}"
        ev = {"event": {"contentBlockDelta": {"delta": {"text": text}}}}
        return HttpResponse(status_code=200, lines=["data: " + json.dumps(ev)])
