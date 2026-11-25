"""Denetim kaydı üretimi ve yazımı."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Protocol

from .clock import Clock, SystemClock

MAX_USERNAME_LENGTH = 255
MAX_WRITE_ATTEMPTS = 3

FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "token",
        "access_token",
        "id_token",
        "refresh_token",
        "secret",
        "authorization",
    }
)

AUDIT_LOGGER_NAME = "logistic_ai.audit"
_error_logger = logging.getLogger("logistic_ai.audit.errors")


class AuditLogger(Protocol):
    def log_login(self, username: str, success: bool) -> None: ...
    def log_logout(self, username: str) -> None: ...
    def log_session_timeout(self, username: str) -> None: ...
    def log_authorization_denied(
        self, username: str, role: str | None, permission: str
    ) -> None: ...
    def log_lockout(self, username: str) -> None: ...


def _is_forbidden(key: object) -> bool:
    return str(key).strip().lower() in FORBIDDEN_KEYS


def _strip_forbidden(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_forbidden(v) for k, v in value.items() if not _is_forbidden(k)}
    if isinstance(value, (list, tuple)):
        return [_strip_forbidden(v) for v in value]
    return value


def build_audit_record(
    event: str,
    username: str | None,
    *,
    clock: Clock | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Saf denetim kaydı: UTC ISO-8601 zaman damgası, kısaltılmış kullanıcı adı, sırsız alanlar."""
    now = (clock or SystemClock()).now()
    record: dict[str, Any] = {
        "event": event,
        "username": (username or "")[:MAX_USERNAME_LENGTH],
        "timestamp": now.isoformat(),
    }
    for key, value in fields.items():
        if _is_forbidden(key) or key in record:
            continue
        record[key] = _strip_forbidden(value)
    return record


class JsonAuditLogger:
    """Kayıtları JSON olarak `logistic_ai.audit` logger'ına yazar; yazma hatasında 3 deneme."""

    def __init__(
        self,
        clock: Clock | None = None,
        logger: logging.Logger | None = None,
        writer: Callable[[str], None] | None = None,
        error_logger: logging.Logger | None = None,
        max_attempts: int = MAX_WRITE_ATTEMPTS,
    ) -> None:
        self._clock = clock or SystemClock()
        self._logger = logger or logging.getLogger(AUDIT_LOGGER_NAME)
        self._writer = writer or self._logger.info
        self._error_logger = error_logger or _error_logger
        self._max_attempts = max(1, min(max_attempts, MAX_WRITE_ATTEMPTS))

    def _emit(self, record: dict[str, Any]) -> None:
        try:
            line = json.dumps(record, ensure_ascii=False, default=str)
        except Exception:
            line = json.dumps({"event": record.get("event"), "timestamp": record.get("timestamp")})
        for _ in range(self._max_attempts):
            try:
                self._writer(line)
                return
            except Exception:
                continue
        try:
            self._error_logger.error(
                "audit_write_failed event=%s timestamp=%s attempts=%d",
                record.get("event"),
                record.get("timestamp"),
                self._max_attempts,
            )
        except Exception:
            pass

    def log_login(self, username: str, success: bool) -> None:
        self._emit(build_audit_record("login", username, clock=self._clock, success=bool(success)))

    def log_logout(self, username: str) -> None:
        self._emit(build_audit_record("logout", username, clock=self._clock))

    def log_session_timeout(self, username: str) -> None:
        self._emit(
            build_audit_record("session_timeout", username, clock=self._clock, reason="idle_timeout")
        )

    def log_authorization_denied(
        self, username: str, role: str | None, permission: str
    ) -> None:
        self._emit(
            build_audit_record(
                "authorization_denied",
                username,
                clock=self._clock,
                role=role,
                permission=permission,
            )
        )

    def log_lockout(self, username: str) -> None:
        self._emit(
            build_audit_record(
                "account_lockout", username, clock=self._clock, reason="too_many_failures"
            )
        )
