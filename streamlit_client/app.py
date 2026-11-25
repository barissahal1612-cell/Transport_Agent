"""Streamlit_Client entry point: wires the components and renders the UI.

Heavy, stateless singletons are cached with ``st.cache_resource``. Per-user
state (tokens, identity, activity) lives only in ``st.session_state`` and is
accessed through ``SessionManager``.

Reqs 8.1, 8.4, 8.5, 8.6, 9.1, 9.2, 9.5, 9.7, 13.12.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

import streamlit as st

from logistic_ai_shared_auth.auth.cognito_service import CognitoAuthService
from logistic_ai_shared_auth.authorization.authorizer import Authorizer
from logistic_ai_shared_auth.authorization.permission_table import (
    PermissionTable,
    PermissionTableError,
)
from logistic_ai_shared_auth.authorization.token_verifier import TokenVerifier
from logistic_ai_shared_auth.common.audit import JsonAuditLogger
from logistic_ai_shared_auth.common.clock import SystemClock
from logistic_ai_shared_auth.common.log_sanitizer import SanitizingFilter

from logistic_ai.config.settings import ConfigError, Settings, load_settings
from logistic_ai.session.agentcore_client import AgentCoreClient
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
    auth: CognitoAuthService
    verifier: TokenVerifier
    authorizer: Authorizer
    audit: JsonAuditLogger
    agent_client: AgentCoreClient


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
    _install_log_sanitizer()
    table = PermissionTable.load(settings.permissions_file)  # raises -> no start
    audit = JsonAuditLogger(clock=SystemClock())
    auth = CognitoAuthService(
        user_pool_id=settings.user_pool_id,
        app_client_id=settings.app_client_id,
        region=settings.aws_region,
        endpoint_url=settings.cognito_endpoint_url,
    )
    verifier = TokenVerifier(
        user_pool_id=settings.user_pool_id,
        app_client_id=settings.app_client_id,
        region=settings.aws_region,
        expected_token_use="id",
    )
    authorizer = Authorizer(table, audit)
    agent_client = AgentCoreClient(
        runtime_arn=settings.agent_runtime_arn,
        region=settings.aws_region,
        settings=settings,
    )
    return _Shared(settings, auth, verifier, authorizer, audit, agent_client)


def build_deps() -> AppDeps:
    try:
        settings = load_settings(os.environ)
    except ConfigError as exc:
        # Variable names only, never values (Req 8.4).
        names = ", ".join(exc.missing)
        _fail(f"Eksik veya geçersiz yapılandırma: {names}" if names else str(exc))
        raise  # unreachable; keeps type checkers satisfied
    try:
        shared = _build_shared(settings)
    except (PermissionTableError, OSError):
        _LOGGER.error("permission_table_load_failed")
        _fail("İzin tablosu yüklenemedi.")
        raise
    # Per-user state: only st.session_state, via SessionManager.
    session = SessionManager(
        store=st.session_state,
        auth=shared.auth,
        verifier=shared.verifier,
        settings=settings,
        clock=SystemClock(),
        audit=shared.audit,
    )
    return AppDeps(
        settings=settings,
        auth=shared.auth,
        verifier=shared.verifier,
        session=session,
        user_context=UserContextProvider(session),
        agent_client=shared.agent_client,
        audit=shared.audit,
    )


def main() -> None:
    st.set_page_config(page_title=_PAGE_TITLE)
    router.render(build_deps())


main()
