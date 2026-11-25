"""Streamlit_Client entry point: wires the components and renders the UI.

Heavy, stateless singletons are cached with ``st.cache_resource``. Per-user
state (tokens, identity, activity) lives only in ``st.session_state`` and is
accessed through ``SessionManager``.

Reqs 2.1, 2.6, 2.8, 7.1, 7.2.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

import streamlit as st

from logistic_ai_data import DynamoDataRepository
from logistic_ai_shared_auth.auth.passwords import PasswordHasher
from logistic_ai_shared_auth.auth.session_token import SessionTokenService
from logistic_ai_shared_auth.auth.user_auth_service import UserAuthService
from logistic_ai_shared_auth.auth.users import DynamoUserRepository
from logistic_ai_shared_auth.authorization.admin_service import AdminService
from logistic_ai_shared_auth.authorization.permission_service import PermissionService
from logistic_ai_shared_auth.authorization.permission_store import DynamoPermissionRepository
from logistic_ai_shared_auth.common.audit import JsonAuditLogger
from logistic_ai_shared_auth.common.clock import SystemClock
from logistic_ai_shared_auth.common.log_sanitizer import SanitizingFilter

from logistic_ai.config.secrets import build_secret_provider
from logistic_ai.config.settings import ConfigError, Settings, load_settings
from logistic_ai.session.agentcore_client import AgentCoreClient, build_transport
from logistic_ai.session.manager import SessionManager
from logistic_ai.session.user_context import UserContextProvider
from logistic_ai.ui import router
from logistic_ai.ui.deps import AppDeps

_LOGGER = logging.getLogger("logistic_ai.app")
_PAGE_TITLE = "Logistics AI Assistant"
_STARTUP_FAILED = "Uygulama başlatılamadı."


@dataclass(frozen=True)
class _Shared:
    """Process-wide singletons that hold no per-user state."""

    settings: Settings
    auth: UserAuthService
    audit: JsonAuditLogger
    agent_client: AgentCoreClient
    data_repo: DynamoDataRepository
    permission_service: PermissionService
    admin_service: AdminService


def _in_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:  # noqa: BLE001
        return False


def _fail(message: str) -> None:
    """Report a startup failure without leaking values; exit non-zero.

    Under Streamlit ``st.stop`` halts the script run (the server must stay up);
    when run directly the process exits with status 1.
    """
    print(message, file=sys.stderr)
    if _in_streamlit():
        st.error(_STARTUP_FAILED)
        st.stop()
    sys.exit(1)


def _install_log_sanitizer() -> None:
    """Attach SanitizingFilter to every root handler (Req 8.6)."""
    logging.basicConfig(level=logging.INFO)
    sanitizer = SanitizingFilter()
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, SanitizingFilter) for f in handler.filters):
            handler.addFilter(sanitizer)


@st.cache_resource(show_spinner=False)
def _build_shared(settings: Settings) -> _Shared:
    """Build repositories and services. Table names come from the environment
    (LOGISTIC_AI_USERS_TABLE, LOGISTIC_AI_PERMISSIONS_TABLE, LOGISTIC_AI_KB_TABLE);
    DynamoDB is only contacted when a request is served."""
    _install_log_sanitizer()
    os.environ.setdefault("AWS_DEFAULT_REGION", settings.aws_region)  # boto3 resources
    clock = SystemClock()
    audit = JsonAuditLogger(clock=clock)
    users = DynamoUserRepository()
    permissions = DynamoPermissionRepository()
    data_repo = DynamoDataRepository()
    permission_service = PermissionService(users, permissions, audit, clock)
    admin_service = AdminService(users, permissions, permission_service, clock=clock)
    tokens = SessionTokenService(
        build_secret_provider(os.environ, settings.aws_region), clock
    )
    auth = UserAuthService(users, PasswordHasher(), tokens, audit, clock)
    agent_client = AgentCoreClient(
        runtime_arn=settings.agent_runtime_arn,
        region=settings.aws_region,
        settings=settings,
        http=build_transport(os.environ, settings.aws_region),
    )
    return _Shared(
        settings, auth, audit, agent_client, data_repo, permission_service, admin_service
    )


def build_deps() -> AppDeps:
    try:
        settings = load_settings(os.environ)
    except ConfigError as exc:
        # Variable names only, never values.
        names = ", ".join(exc.missing)
        _fail(f"Eksik veya geçersiz yapılandırma: {names}" if names else str(exc))
        raise  # unreachable; keeps type checkers satisfied
    try:
        shared = _build_shared(settings)
    except Exception as exc:  # noqa: BLE001 - never leak details
        _LOGGER.error("startup_failed type=%s", type(exc).__name__)
        _fail("Uygulama bileşenleri oluşturulamadı.")
        raise
    # Per-user state: only st.session_state, via SessionManager.
    session = SessionManager(
        store=st.session_state,
        auth=shared.auth,
        settings=settings,
        clock=SystemClock(),
        audit=shared.audit,
    )
    return AppDeps(
        settings=settings,
        auth=shared.auth,
        session=session,
        user_context=UserContextProvider(session),
        agent_client=shared.agent_client,
        audit=shared.audit,
        data_repo=shared.data_repo,
        permission_service=shared.permission_service,
        admin_service=shared.admin_service,
    )


def main() -> None:
    st.set_page_config(page_title=_PAGE_TITLE)
    router.render(build_deps())


main()
