"""Login_Screen (Req 1.1-1.7, 2.1, 2.2, 3.5, 3.6, 10.1).

Flow: a submit validates the input, then stores the credentials for exactly one
rerun (``_PENDING``) and sets ``_IN_FLIGHT``. The rerun renders the form with a
disabled button and a spinner, pops the credentials immediately, authenticates
(30 s overall limit) and either establishes the session or stores an error and
reruns. The password is never written to the session manager or any log.
"""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

import streamlit as st
from logistic_ai_shared_auth.auth.errors import AuthError
from logistic_ai_shared_auth.auth.service import (
    PASSWORD_MAX_LENGTH,
    USERNAME_MAX_LENGTH,
    validate_credentials,
)
from logistic_ai_shared_auth.authorization.roles import RoleResolutionError
from logistic_ai_shared_auth.authorization.token_verifier import (
    TokenVerificationError,
    resolve_identity,
)

from logistic_ai.ui.deps import AppDeps

_LOGGER = logging.getLogger("logistic_ai.ui.login")

APP_TITLE = "Logistics AI Assistant"
LOGIN_TIMEOUT_SECONDS = 30.0
LOGIN_FAILED_MESSAGE = "Giriş başarısız oldu, lütfen tekrar deneyin"
TIMEOUT_MESSAGE = "Giriş isteği zaman aşımına uğradı, lütfen tekrar deneyin"

_KEY_USERNAME = "login_username"
_KEY_PASSWORD = "login_password"
_IN_FLIGHT = "login_in_flight"
_PENDING = "login_pending"
_ERROR = "login_error"
_CLEAR_PASSWORD = "login_clear_password"

_FIELD_MESSAGES = {
    ("username",): "Kullanıcı adı boş veya geçersiz",
    ("password",): "Şifre boş veya geçersiz",
    ("username", "password"): "Kullanıcı adı ve şifre boş veya geçersiz",
}


def _safe_audit_login(deps: AppDeps, username: str, success: bool) -> None:
    try:
        deps.audit.log_login(username, success)
    except Exception:  # noqa: BLE001 - audit must never change the outcome
        _LOGGER.error("audit_call_failed")


def _authenticate(deps: AppDeps, username: str, password: str) -> tuple[Any, Any]:
    result = deps.auth.authenticate(username, password)
    identity = resolve_identity(result.tokens.id_token, deps.verifier)
    return result, identity


def _attempt_login(deps: AppDeps, username: str, password: str) -> str | None:
    """Return an error message, or ``None`` after the session was established."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        result, identity = executor.submit(
            _authenticate, deps, username, password
        ).result(timeout=LOGIN_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        _LOGGER.warning("login_timeout")
        _safe_audit_login(deps, username, False)
        return TIMEOUT_MESSAGE
    except AuthError as exc:
        _safe_audit_login(deps, username, False)
        return exc.user_message
    except RoleResolutionError as exc:  # Req 3.5, 3.6: no session is created
        _safe_audit_login(deps, username, False)
        return exc.user_message
    except TokenVerificationError:
        _safe_audit_login(deps, username, False)
        return LOGIN_FAILED_MESSAGE
    except Exception as exc:  # noqa: BLE001 - never leak technical detail
        _LOGGER.error("login_unexpected_error type=%s", type(exc).__name__)
        _safe_audit_login(deps, username, False)
        return LOGIN_FAILED_MESSAGE
    finally:
        executor.shutdown(wait=False)

    deps.session.establish(result.tokens, identity)
    _safe_audit_login(deps, identity.username, True)
    return None


def render_login(deps: AppDeps) -> None:
    state = st.session_state

    # Clear the password after a failed attempt, before the widget exists (Req 1.6).
    if state.pop(_CLEAR_PASSWORD, False):
        state[_KEY_PASSWORD] = ""

    st.title(APP_TITLE)

    pending = state.pop(_PENDING, None)
    in_flight = bool(state.get(_IN_FLIGHT, False)) and pending is not None
    if not in_flight:
        state[_IN_FLIGHT] = False

    error = state.pop(_ERROR, None)
    error_slot = st.empty()
    if error:
        error_slot.error(error)

    with st.form("login_form", border=False):
        username = st.text_input(
            "Kullanıcı adı", max_chars=USERNAME_MAX_LENGTH, key=_KEY_USERNAME
        )
        password = st.text_input(
            "Şifre",
            type="password",
            max_chars=PASSWORD_MAX_LENGTH,
            key=_KEY_PASSWORD,
        )
        submitted = st.form_submit_button("Giriş yap", disabled=in_flight)

    if in_flight:
        creds_user, creds_password = pending
        with st.spinner("Giriş yapılıyor..."):
            message = _attempt_login(deps, creds_user, creds_password)
        del creds_password
        state[_IN_FLIGHT] = False
        if message is None:
            state[_CLEAR_PASSWORD] = True
            st.rerun()
        state[_ERROR] = message
        state[_CLEAR_PASSWORD] = True
        st.rerun()
        return

    if submitted:
        invalid = validate_credentials(username, password)
        if invalid:
            key = tuple(f for f in ("username", "password") if f in invalid)
            error_slot.error(_FIELD_MESSAGES[key])
            return
        state[_PENDING] = (username, password)
        state[_IN_FLIGHT] = True
        st.rerun()
