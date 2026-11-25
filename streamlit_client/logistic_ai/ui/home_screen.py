"""Chat screen (Req 2.6, 2.8, 2.10).

Exactly one chat history area (empty on first open) and one message input.
Messages are sent to the Agent_Backend through ``AgentCoreClient`` together
with the session's Session_Token.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import streamlit as st
from logistic_ai_shared_auth.common.errors import GENERIC_ERROR_MESSAGE

from logistic_ai.session.agentcore_client import AgentCoreError, AgentCoreUnauthorized
from logistic_ai.session.manager import (
    KEY_CHAT_HISTORY,
    SESSION_ENDED_MESSAGE,
    SessionInvalid,
)
from logistic_ai.ui.deps import AppDeps

_LOGGER = logging.getLogger("logistic_ai.ui.home")

LOGOUT_LABEL = "Çıkış"
NEW_CHAT_LABEL = "Yeni sohbet"
CHAT_INPUT_PLACEHOLDER = "Mesajınızı yazın"
EMPTY_RESPONSE_MESSAGE = "Yanıt alınamadı."

KEY_CHAT_SESSION_ID = "chat_runtime_session_id"
KEY_SESSION_ENDED_MESSAGE = "session_ended_message"


def _history() -> list[dict[str, str]]:
    """Chat history lives in the server-side session state (cleared on logout)."""
    state: Any = st.session_state
    if KEY_CHAT_HISTORY not in state:
        state[KEY_CHAT_HISTORY] = []
        # A new history means a new conversation: use a fresh runtime session id.
        state[KEY_CHAT_SESSION_ID] = f"logistic-ai-{uuid.uuid4().hex}"  # 46 chars (>= 33)
    return state[KEY_CHAT_HISTORY]


def _runtime_session_id() -> str:
    _history()
    return str(st.session_state[KEY_CHAT_SESSION_ID])


def _new_chat() -> list[dict[str, str]]:
    """Start a new conversation: empty history and a fresh runtime session id (no logout)."""
    st.session_state.pop(KEY_CHAT_HISTORY, None)
    return _history()


def _redirect_to_login(message: str | None = None) -> None:
    """Drop chat leftovers and rerun; the router then shows the Login_Screen."""
    st.session_state.pop(KEY_CHAT_SESSION_ID, None)
    st.session_state.pop(KEY_CHAT_HISTORY, None)
    if message:
        st.session_state[KEY_SESSION_ENDED_MESSAGE] = message
    st.rerun()


def _handle_logout(deps: AppDeps) -> None:
    try:
        deps.session.logout()  # clears local data first, then revokes (Req 7.2-7.5)
    except Exception as exc:  # noqa: BLE001 - logout must always end on the login screen
        _LOGGER.error("logout_failed: %s", type(exc).__name__)
    _redirect_to_login()


def _ask_agent(deps: AppDeps, prompt: str, history: list[dict[str, str]] | None = None) -> str:
    """Send ``prompt`` and return the full answer text.

    Raises ``SessionInvalid`` when the backend rejects the Session_Token (no
    refresh: the user signs in again) and ``AgentCoreError`` for
    network/timeouts/unexpected responses.
    """
    deps.session.touch()
    view = deps.session.require_valid_session()
    session_id = _runtime_session_id()
    try:
        chunks = deps.agent_client.invoke(view.session_token, prompt, session_id, history=history)
        return "".join(chunks).strip() or EMPTY_RESPONSE_MESSAGE
    except AgentCoreUnauthorized:
        deps.session.logout()
        raise SessionInvalid("agent_unauthorized") from None


def render_home(deps: AppDeps) -> None:
    """Render the Chatbot_Home_Screen for the authenticated user."""
    try:
        user = deps.user_context.current()
    except Exception:  # noqa: BLE001 - never render content without a valid session
        _redirect_to_login()
        return

    history = _history()

    # Header: full username, role next to it, logout in the visible area.
    name_col, role_col, new_col, logout_col = st.columns([4, 3, 2, 1])
    with name_col:
        st.text(user.username)
    with role_col:
        st.text(user.role)
    with new_col:
        if st.button(NEW_CHAT_LABEL, key="new_chat_button"):
            history = _new_chat()
    with logout_col:
        if st.button(LOGOUT_LABEL, key="logout_button"):
            _handle_logout(deps)
            return

    # Single chat history area, empty on first open (Req 5.4).
    chat_area = st.container()
    with chat_area:
        for message in history:
            with st.chat_message(message["role"]):
                st.text(message["content"])

    # Single message input.
    prompt = st.chat_input(CHAT_INPUT_PLACEHOLDER, key="chat_message_input")
    if prompt is None or not prompt.strip():
        return
    prompt = prompt.strip()

    with chat_area:
        with st.chat_message("user"):
            st.text(prompt)
        try:
            with st.chat_message("assistant"):
                with st.spinner("..."):
                    answer = _ask_agent(deps, prompt, list(history))
                st.text(answer)
        except SessionInvalid as exc:
            _redirect_to_login(getattr(exc, "user_message", SESSION_ENDED_MESSAGE))
            return
        except AgentCoreError:
            st.error(GENERIC_ERROR_MESSAGE)
            history.append({"role": "user", "content": prompt})
            return
        except Exception as exc:  # noqa: BLE001 - generic message only (Req 10.4)
            _LOGGER.error("chat_failed: %s", type(exc).__name__)
            st.error(GENERIC_ERROR_MESSAGE)
            history.append({"role": "user", "content": prompt})
            return

    history.append({"role": "user", "content": prompt})
    history.append({"role": "assistant", "content": answer})
