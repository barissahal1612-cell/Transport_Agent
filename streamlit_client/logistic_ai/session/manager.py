"""Server-side session management (Req 6.1-6.7, 7.2, 7.3, 7.5, 10.2, 10.3, 13.7).

Tokens and the verified identity live only in ``store`` (``st.session_state``
in production, a plain ``dict`` in tests). The password is never stored and
no token value is ever logged.
"""
from __future__ import annotations

import concurrent.futures
import logging
from collections.abc import MutableMapping
from dataclasses import dataclass, field, replace
from typing import Any, Callable, TypeVar

from logistic_ai_shared_auth.auth.service import AuthService, TokenSet
from logistic_ai_shared_auth.authorization.roles import Role, VerifiedIdentity
from logistic_ai_shared_auth.authorization.token_verifier import (
    TokenVerifier,
    resolve_identity,
)
from logistic_ai_shared_auth.common.audit import AuditLogger
from logistic_ai_shared_auth.common.clock import Clock

from logistic_ai.config.settings import Settings

_LOGGER = logging.getLogger("logistic_ai.session")

REFRESH_THRESHOLD_SECONDS = 300
REFRESH_TIMEOUT_SECONDS = 10.0
REVOKE_TIMEOUT_SECONDS = 10.0

SESSION_ENDED_MESSAGE = "Oturumunuz sona erdi, lütfen tekrar giriş yapın"

KEY_TOKENS = "tokens"
KEY_IDENTITY = "identity"
KEY_LAST_ACTIVITY = "last_activity"
KEY_REFRESH_ATTEMPTED = "refresh_attempted"
KEY_ACCESS_EXPIRES_AT = "access_expires_at"
KEY_CHAT_HISTORY = "chat_history"
SESSION_KEYS: tuple[str, ...] = (
    KEY_TOKENS,
    KEY_IDENTITY,
    KEY_LAST_ACTIVITY,
    KEY_REFRESH_ATTEMPTED,
    KEY_ACCESS_EXPIRES_AT,
    KEY_CHAT_HISTORY,
)

_T = TypeVar("_T")


class SessionInvalid(Exception):
    """The session is missing, expired, idle-timed-out or could not be refreshed."""

    def __init__(self, reason: str = "invalid_session") -> None:
        self.reason = reason
        self.user_message = SESSION_ENDED_MESSAGE
        super().__init__(reason)


@dataclass(frozen=True)
class SessionView:
    username: str
    role: Role
    access_token: str = field(repr=False)


def _call_with_timeout(func: Callable[[], _T], timeout: float) -> _T:
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(func).result(timeout=timeout)
    finally:
        executor.shutdown(wait=False)


class SessionManager:
    def __init__(
        self,
        store: MutableMapping[str, Any],
        auth: AuthService,
        verifier: TokenVerifier,
        settings: Settings,
        clock: Clock,
        audit: AuditLogger,
    ) -> None:
        self._store = store
        self._auth = auth
        self._verifier = verifier
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
        tokens = self._store.get(KEY_TOKENS)
        identity = self._store.get(KEY_IDENTITY)
        return (
            isinstance(tokens, TokenSet)
            and bool(tokens.access_token)
            and isinstance(identity, VerifiedIdentity)
        )

    def _store_tokens(self, tokens: TokenSet) -> None:
        self._store[KEY_TOKENS] = tokens
        self._store[KEY_ACCESS_EXPIRES_AT] = self._clock.timestamp() + max(
            0, int(tokens.expires_in or 0)
        )

    # -- public API --------------------------------------------------------
    def establish(self, tokens: TokenSet, identity: VerifiedIdentity) -> None:
        self._clear()
        self._store_tokens(tokens)
        self._store[KEY_IDENTITY] = identity
        self._store[KEY_LAST_ACTIVITY] = self._clock.timestamp()
        self._store[KEY_REFRESH_ATTEMPTED] = False

    def touch(self) -> None:
        if self._has_session():
            self._store[KEY_LAST_ACTIVITY] = self._clock.timestamp()

    def is_authenticated(self) -> bool:
        """Side-effect free check: session data present and neither expired nor idle."""
        if not self._has_session():
            return False
        now = self._clock.timestamp()
        if now - float(self._store.get(KEY_LAST_ACTIVITY, 0.0)) >= self._idle_seconds():
            return False
        return now < float(self._store.get(KEY_ACCESS_EXPIRES_AT, 0.0))

    def require_valid_session(self) -> SessionView:
        if not self._has_session():
            self._clear()
            raise SessionInvalid("no_session")
        identity: VerifiedIdentity = self._store[KEY_IDENTITY]
        now = self._clock.timestamp()

        last_activity = float(self._store.get(KEY_LAST_ACTIVITY, 0.0))
        if now - last_activity >= self._idle_seconds():
            username = identity.username
            self._clear()
            self._safe_audit(lambda: self._audit.log_session_timeout(username))
            raise SessionInvalid("idle_timeout")

        remaining = float(self._store.get(KEY_ACCESS_EXPIRES_AT, 0.0)) - now
        if remaining <= 0:
            self._clear()
            raise SessionInvalid("access_token_expired")

        if remaining <= REFRESH_THRESHOLD_SECONDS and not self._store.get(
            KEY_REFRESH_ATTEMPTED, False
        ):
            self._refresh()

        tokens: TokenSet = self._store[KEY_TOKENS]
        identity = self._store[KEY_IDENTITY]
        return SessionView(
            username=identity.username, role=identity.role, access_token=tokens.access_token
        )

    def refresh_for_agent_call(self) -> str:
        """Single refresh attempt after AgentCore 401/403; returns the new access token."""
        if not self._has_session():
            self._clear()
            raise SessionInvalid("no_session")
        if self._store.get(KEY_REFRESH_ATTEMPTED, False):
            self._clear()
            raise SessionInvalid("refresh_already_attempted")
        self._refresh()
        return self._store[KEY_TOKENS].access_token

    def logout(self) -> None:
        identity = self._store.get(KEY_IDENTITY)
        tokens = self._store.get(KEY_TOKENS)
        username = identity.username if isinstance(identity, VerifiedIdentity) else ""
        refresh_token = tokens.refresh_token if isinstance(tokens, TokenSet) else None
        # Local data first (Req 7.2, 7.5), then server-side revocation (Req 7.3).
        self._clear()
        if refresh_token:
            try:
                _call_with_timeout(
                    lambda: self._auth.revoke(refresh_token), REVOKE_TIMEOUT_SECONDS
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Token revocation failed: %s", type(exc).__name__)
        if username:
            self._safe_audit(lambda: self._audit.log_logout(username))

    # -- internals ---------------------------------------------------------
    def _idle_seconds(self) -> float:
        return self._settings.idle_timeout_minutes * 60.0

    def _refresh(self) -> None:
        """At most one attempt; any failure wipes the whole session (Req 6.3, 6.4)."""
        self._store[KEY_REFRESH_ATTEMPTED] = True
        tokens: TokenSet = self._store[KEY_TOKENS]
        identity: VerifiedIdentity = self._store[KEY_IDENTITY]
        refresh_token = tokens.refresh_token
        if not refresh_token:
            self._clear()
            raise SessionInvalid("no_refresh_token")
        try:
            new = _call_with_timeout(
                lambda: self._auth.refresh(refresh_token), REFRESH_TIMEOUT_SECONDS
            )
            new_identity = resolve_identity(new.id_token, self._verifier)
        except Exception as exc:  # noqa: BLE001 - fail closed
            _LOGGER.warning("Token refresh failed: %s", type(exc).__name__)
            self._clear()
            raise SessionInvalid("refresh_failed") from None
        if new_identity.role != identity.role or new_identity.username != identity.username:
            self._clear()
            raise SessionInvalid("identity_changed")
        # Cognito does not return a new refresh token on refresh; keep the old one.
        if not new.refresh_token:
            new = replace(new, refresh_token=refresh_token)
        self._store_tokens(new)
        self._store[KEY_IDENTITY] = new_identity
        self._store[KEY_REFRESH_ATTEMPTED] = False
