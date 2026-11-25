"""Helpers for the dashboard / UI tests (task 12.5). No AWS, no server: Streamlit ``AppTest`` only.

Real Excel (users, permissions, summary_df) -> in-memory repositories; fake AgentCore transport.
Passwords are read from the workbook at test time; they are never printed or asserted by value
in a way that pytest could echo (use ``leaks`` for containment checks).
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .../Logistic_AI
for _p in (HERE, ROOT / "scripts", ROOT / "streamlit_client"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
try:
    import openpyxl  # noqa: F401
except ImportError:  # openpyxl lives only in scripts/.venv
    for _sp in glob.glob(str(ROOT / "scripts" / ".venv" / "lib" / "python*" / "site-packages")):
        sys.path.append(_sp)


def skip_reason() -> str | None:
    """Reason to skip the whole module, or None when the real Excel + openpyxl are usable."""
    try:
        import openpyxl  # noqa: F401,F811
    except ImportError:
        return "openpyxl not importable (neither in this venv nor scripts/.venv)"
    excel = ROOT / "Data" / "Agent_AWS_2026-11-24.xlsx"
    if not excel.exists():
        return f"real Excel not found: {excel.name}"
    return None


def leaks(text: str, secret: str) -> bool:
    """True when ``secret`` occurs in ``text`` (keeps the secret out of assertion output)."""
    return bool(secret) and secret in text


class World:
    """Backend side (users, permissions, data, fake transport) for AppTest scripts."""

    def __init__(self) -> None:
        from datetime import datetime, timezone

        import session_isolation_helpers as H
        from ingest.excel_reader import read_workbook
        from logistic_ai.session.agentcore_client import AgentCoreClient
        from logistic_ai.session.manager import SessionManager
        from logistic_ai.session.user_context import UserContextProvider
        from logistic_ai_data.in_memory import InMemoryDataRepository
        from logistic_ai_shared_auth.auth.session_token import SessionTokenService
        from logistic_ai_shared_auth.auth.user_auth_service import UserAuthService
        from logistic_ai_shared_auth.auth.users import InMemoryUserRepository
        from logistic_ai_shared_auth.authorization.admin_service import AdminService
        from logistic_ai_shared_auth.authorization.permission_service import PermissionService
        from logistic_ai_shared_auth.authorization.permission_store import InMemoryPermissionRepository
        from logistic_ai_shared_auth.common.clock import FixedClock

        self.H = H
        self._SessionManager, self._UCP = SessionManager, UserContextProvider
        subset, self.creds, _extras = H.load_subset()
        self.clock = FixedClock(datetime(2025, 1, 1, tzinfo=timezone.utc))
        self.audit = H.RecordingAudit()
        self.users, self.perms = InMemoryUserRepository(), InMemoryPermissionRepository()
        H.seed(subset, self.users, self.perms)
        self.tokens = SessionTokenService(H.FixedSecret(), self.clock)
        self.auth = UserAuthService(self.users, H.fast_hasher(), self.tokens, self.audit, self.clock)
        self.backend = H.FakeBackend(self.tokens, self.users)
        self.client = AgentCoreClient(
            "arn:aws:bedrock-agentcore:eu-west-1:000000000000:runtime/x", "eu-west-1", http=self.backend
        )
        self.permission_service = PermissionService(self.users, self.perms, self.audit, self.clock)
        self.admin_service = AdminService(
            self.users, self.perms, self.permission_service, clock=self.clock
        )
        wb = read_workbook(ROOT / "Data" / "Agent_AWS_2026-11-24.xlsx")
        self.summary_rows: list[dict] = [dict(r) for r in wb.sheets["summary_df"]]
        self.data_repo = InMemoryDataRepository({"summary_df": self.summary_rows})

    # -- Excel truth ------------------------------------------------------
    def summary(self) -> dict[str, float]:
        """label -> value straight from the Excel summary_df rows."""
        out: dict[str, float] = {}
        for r in self.summary_rows:
            out[str(r["Durum"]).strip()] = float(str(r["Adet"]).replace(",", "."))
        return out

    # -- wiring -------------------------------------------------------------
    def deps(self, store: Any) -> Any:
        from logistic_ai.ui.deps import AppDeps

        session = self._SessionManager(store, self.auth, self.H.Settings(), self.clock, self.audit)
        return AppDeps(
            settings=self.H.Settings(),
            auth=self.auth,
            session=session,
            user_context=self._UCP(session),
            agent_client=self.client,
            audit=self.audit,
            data_repo=self.data_repo,
            permission_service=self.permission_service,
            admin_service=self.admin_service,
        )

    def session_state_for(self, role: str) -> dict[str, Any]:
        """Session keys of an already logged-in user (to pre-seed ``AppTest.session_state``)."""
        store: dict[str, Any] = {}
        mgr = self._SessionManager(store, self.auth, self.H.Settings(), self.clock, self.audit)
        cred = self.creds[role]
        mgr.establish(self.auth.authenticate(cred.username, cred.password))
        return store


# ---- AppTest scripts (run by streamlit.testing; ``world`` is passed through ``args``) -------
def router_script(world) -> None:  # pragma: no cover - executed inside AppTest
    import streamlit as st

    from logistic_ai.ui import router

    router.render(world.deps(st.session_state))


def admin_panel_script(world) -> None:  # pragma: no cover - executed inside AppTest
    import streamlit as st

    from logistic_ai.ui.admin_panel import render_admin_panel

    render_admin_panel(world.deps(st.session_state))


def make_app(world, script=router_script, state: dict | None = None):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(script, args=(world,), default_timeout=30)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    return at


def login(at, cred) -> Any:
    """Fill the login form of the real login screen and submit it."""
    at.run()
    at.text_input(key="login_username").input(cred.username)
    at.text_input(key="login_password").input(cred.password)
    submit = [b for b in at.button if b.label == "Giriş yap"][0]
    submit.click()
    at.run()
    return at


def metrics(at) -> dict[str, str]:
    return {m.label: str(m.value) for m in at.metric}
