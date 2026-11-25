"""Server-side session management for the ``role_user`` flow (Req 2.1, 2.6, 2.8, 2.10).

Only ``session_token``, ``userid``, ``username``, ``role`` and ``last_activity``
(plus the chat history) live in ``store`` (``st.session_state`` in production,
a plain ``dict`` in tests). The password is never stored and the token is never
logged. There is no refresh logic: when the token is rejected or the idle
timeout elapses the user signs in again. Logout clears everything, including
the chat history, and calls ``UserAuthService.logout`` for the audit trail.
"""
from __future__ import annotations

import logging
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from typing import Any, Callable

from logistic_ai_shared_auth.auth.user_auth_service import (
    AuthenticatedSession,
    UserAuthService,
)
from logistic_ai_shared_auth.common.audit import AuditLogger
from logistic_ai_shared_auth.common.clock import Clock

from logistic_ai.config.settings import Settings

_LOGGER = logging.getLogger("logistic_ai.session")

SESSION_ENDED_MESSAGE = "Oturumunuz sona erdi, lütfen tekrar giriş yapın"

KEY_SESSION_TOKEN = "session_token"
KEY_USERID = "userid"
KEY_USERNAME = "username"
KEY_ROLE = "role"
KEY_LAST_ACTIVITY = "last_activity"
KEY_CHAT_HISTORY = "chat_history"
# Chat/UI leftovers owned by other modules; wiped together with the session.
KEY_CHAT_SESSION_ID = "chat_runtime_session_id"
KEY_ACTIVE_PAGE = "active_page"
KEY_DASHBOARD_SEEN = "dashboard_auto_shown"  # first view after login already happened
SESSION_KEYS: tuple[str, ...] = (
    KEY_SESSION_TOKEN,
    KEY_USERID,
    KEY_USERNAME,
    KEY_ROLE,
    KEY_LAST_ACTIVITY,
    KEY_CHAT_HISTORY,
    KEY_CHAT_SESSION_ID,
    KEY_ACTIVE_PAGE,
    KEY_DASHBOARD_SEEN,
)


class SessionInvalid(Exception):
    """The session is missing, idle-timed-out or was rejected by the backend."""

    def __init__(self, reason: str = "invalid_session") -> None:
        self.reason = reason
        self.user_message = SESSION_ENDED_MESSAGE
        super().__init__(reason)


@dataclass(frozen=True)
class SessionView:
    userid: str
    username: str
    role: str
    session_token: str = field(repr=False)


class SessionManager:
    def __init__(
        self,
        store: MutableMapping[str, Any],
        auth: UserAuthService,
        settings: Settings,
        clock: Clock,
        audit: AuditLogger,
    ) -> None:
        self._store = store
        self._auth = auth
        self._settings = settings
        self._clock = clock
        self._audit = audit

    # -- helpers -----------------------------------------------------------
    def _clear(self) -> None:
        for key in SESSION_KEYS:
            self._store.pop(key, None)

    def _safe_audit(self, call: Callable[[], None]) -> None:
        try:
            call()
        except Exception:  # noqa: BLE001 - audit must never change the outcome
            _LOGGER.error("audit_call_failed")

    def _has_session(self) -> bool:
        return all(
            isinstance(self._store.get(key), str) and bool(self._store.get(key))
            for key in (KEY_SESSION_TOKEN, KEY_USERID, KEY_USERNAME, KEY_ROLE)
        )

    def _idle_seconds(self) -> float:
        return self._settings.idle_timeout_minutes * 60.0

    # -- public API --------------------------------------------------------
    def establish(self, session: AuthenticatedSession) -> None:
        """Store the identity of a successful login (never the password)."""
        self._clear()
        self._store[KEY_SESSION_TOKEN] = session.token
        self._store[KEY_USERID] = session.userid
        self._store[KEY_USERNAME] = session.username
        self._store[KEY_ROLE] = session.role
        self._store[KEY_LAST_ACTIVITY] = self._clock.timestamp()

    def touch(self) -> None:
        if self._has_session():
            self._store[KEY_LAST_ACTIVITY] = self._clock.timestamp()

    def is_authenticated(self) -> bool:
        """Side-effect free check: session data present and not idle."""
        if not self._has_session():
            return False
        idle = self._clock.timestamp() - float(self._store.get(KEY_LAST_ACTIVITY, 0.0))
        return idle < self._idle_seconds()

    def require_valid_session(self) -> SessionView:
        if not self._has_session():
            self._clear()
            raise SessionInvalid("no_session")
        now = self._clock.timestamp()
        if now - float(self._store.get(KEY_LAST_ACTIVITY, 0.0)) >= self._idle_seconds():
            username = str(self._store[KEY_USERNAME])
            self._clear()
            self._safe_audit(lambda: self._audit.log_session_timeout(username))
            raise SessionInvalid("idle_timeout")
        return SessionView(
            userid=self._store[KEY_USERID],
            username=self._store[KEY_USERNAME],
            role=self._store[KEY_ROLE],
            session_token=self._store[KEY_SESSION_TOKEN],
        )

    def logout(self) -> None:
        userid = str(self._store.get(KEY_USERID) or "")
        username = str(self._store.get(KEY_USERNAME) or "")
        self._clear()  # local data first, including the chat history
        if username:
            try:
                self._auth.logout(userid, username)  # audit record only
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("logout_audit_failed: %s", type(exc).__name__)
