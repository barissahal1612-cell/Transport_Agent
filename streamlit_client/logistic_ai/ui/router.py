"""Screen router (Req 2.1, 2.8, 7.1, 7.2).

Every Streamlit rerun starts with ``SessionManager.require_valid_session()``.
After login:

* ``TRANSPORT_OFFICE`` / ``MATERIAL_RESPONSIBLE``: Dashboard automatically on the first
  view after login only (then chat); later via the sidebar radio.
* ``SUPPLIER``: chat only (no Dashboard).
* ``ADMIN``: sidebar radio choosing the Admin Panel or the chat.

Anything else (no session, unknown role) shows the login screen.
"""
from __future__ import annotations

import logging

import streamlit as st
from logistic_ai_shared_auth.auth.users import (
    ADMIN,
    MATERIAL_RESPONSIBLE,
    ROLES,
    TRANSPORT_OFFICE,
)
from logistic_ai_shared_auth.common.errors import safe_error_message

from logistic_ai.session.manager import (
    KEY_ACTIVE_PAGE,
    KEY_DASHBOARD_SEEN,
    SESSION_ENDED_MESSAGE,
    SessionInvalid,
)
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


DASHBOARD_ROLES = frozenset({TRANSPORT_OFFICE, MATERIAL_RESPONSIBLE})
PAGE_ADMIN = "Yönetim Paneli"
PAGE_CHAT = "Sohbet"
PAGE_DASHBOARD = "Dashboard"


def _show_home(deps: AppDeps) -> None:
    from logistic_ai.ui.home_screen import render_home

    render_home(deps)


def _show_dashboard(deps: AppDeps) -> None:
    from logistic_ai.ui.dashboard import render_dashboard  # lazy: separate module

    render_dashboard(deps)


def _show_admin_panel(deps: AppDeps) -> None:
    from logistic_ai.ui.admin_panel import render_admin_panel  # lazy: separate module

    render_admin_panel(deps)


def _show_admin_header(deps: AppDeps) -> None:
    """Username, role and logout in the sidebar (the chat header is not shown on the admin page)."""
    from logistic_ai.ui import home_screen

    user = deps.user_context.current()
    st.sidebar.text(user.username)
    st.sidebar.text(user.role)
    if st.sidebar.button(home_screen.LOGOUT_LABEL, key="logout_button"):
        home_screen._handle_logout(deps)


def _show_role_pages(deps: AppDeps, role: str) -> None:
    """Role-based page composition after a successful login."""
    if role == ADMIN:
        page = st.sidebar.radio(
            "Sayfa", [PAGE_ADMIN, PAGE_CHAT], key=KEY_ACTIVE_PAGE
        )
        if page == PAGE_ADMIN:
            _show_admin_header(deps)
            _show_admin_panel(deps)
            return
    elif role in DASHBOARD_ROLES:
        first_view = not st.session_state.get(KEY_DASHBOARD_SEEN, False)
        if first_view:
            st.session_state[KEY_DASHBOARD_SEEN] = True
            st.session_state[KEY_ACTIVE_PAGE] = PAGE_CHAT  # later reruns: chat unless chosen
        page = st.sidebar.radio(
            "Sayfa", [PAGE_CHAT, PAGE_DASHBOARD], key=KEY_ACTIVE_PAGE
        )
        if first_view or page == PAGE_DASHBOARD:
            _show_dashboard(deps)
    _show_home(deps)


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

        # Unknown role: never show any content.
        if view.role not in ROLES:
            st.session_state[KEY_SESSION_ENDED] = SESSION_ENDED_MESSAGE
            deps.session.logout()
            _show_login(deps)
            return

        st.session_state.pop(KEY_SESSION_ENDED, None)
        try:
            _show_role_pages(deps, view.role)
        except SessionInvalid as exc:
            # Session ended mid-run (e.g. the backend rejected the Session_Token).
            st.session_state[KEY_SESSION_ENDED] = _session_ended(exc) or SESSION_ENDED_MESSAGE
            st.rerun()
    except SessionInvalid:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak internals to the UI
        if type(exc).__name__ in ("RerunException", "StopException"):
            raise  # Streamlit control-flow exceptions
        _LOGGER.error("ui_unexpected_error type=%s", type(exc).__name__)
        st.error(safe_error_message(exc))
