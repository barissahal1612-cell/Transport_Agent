"""Screen router (Req 5.1, 5.6, 5.7, 6.6, 7.6, 7.7, 10.4).

Every Streamlit rerun starts with ``SessionManager.require_valid_session()``.
A valid session with a known role shows the home screen; anything else shows
the login screen without rendering any home-screen content.
"""
from __future__ import annotations

import logging

import streamlit as st
from logistic_ai_shared_auth.authorization.roles import Role
from logistic_ai_shared_auth.common.errors import safe_error_message

from logistic_ai.session.manager import SESSION_ENDED_MESSAGE, SessionInvalid
from logistic_ai.ui.deps import AppDeps

_LOGGER = logging.getLogger("logistic_ai.ui.router")

# Survives reruns until a valid session is seen again (or a login succeeds).
KEY_SESSION_ENDED = "session_ended_message"


def _show_login(deps: AppDeps) -> None:
    from logistic_ai.ui.login_screen import render_login

    message = st.session_state.get(KEY_SESSION_ENDED)
    if message:
        st.error(message)
    render_login(deps)


def _show_home(deps: AppDeps) -> None:
    from logistic_ai.ui.home_screen import render_home

    render_home(deps)


def _session_ended(exc: SessionInvalid) -> str | None:
    # "no_session" is a first visit or an explicit logout: no error message.
    if exc.reason == "no_session":
        return None
    return getattr(exc, "user_message", SESSION_ENDED_MESSAGE) or SESSION_ENDED_MESSAGE


def render(deps: AppDeps) -> None:
    try:
        try:
            view = deps.session.require_valid_session()
        except SessionInvalid as exc:
            message = _session_ended(exc)
            if message:
                st.session_state[KEY_SESSION_ENDED] = message
            _show_login(deps)
            return

        # Ambiguous or unknown role: never show home content (Req 5.6, 5.7).
        if not isinstance(view.role, Role):
            st.session_state[KEY_SESSION_ENDED] = SESSION_ENDED_MESSAGE
            deps.session.logout()
            _show_login(deps)
            return

        st.session_state.pop(KEY_SESSION_ENDED, None)
        try:
            _show_home(deps)
        except SessionInvalid as exc:
            # Session ended mid-run (e.g. refresh after AgentCore 401 failed).
            st.session_state[KEY_SESSION_ENDED] = _session_ended(exc) or SESSION_ENDED_MESSAGE
            st.rerun()
    except SessionInvalid:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak internals to the UI
        if type(exc).__name__ in ("RerunException", "StopException"):
            raise  # Streamlit control-flow exceptions
        _LOGGER.error("ui_unexpected_error type=%s", type(exc).__name__)
        st.error(safe_error_message(exc))
