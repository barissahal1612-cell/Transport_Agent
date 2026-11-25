"""Yerel giriş kilitleme: kullanıcı adı başına ardışık başarısız deneme takibi (Req 2.7)."""
from __future__ import annotations

import threading

from ..common.clock import Clock, SystemClock

DEFAULT_MAX_FAILURES = 5
DEFAULT_LOCKOUT_SECONDS = 15 * 60


def _key(username: str) -> str:
    return (username or "").strip().lower()


class LoginAttemptTracker:
    """Ardışık başarısızlıkları sayar; eşikte kullanıcı adını süreli kilitler."""

    def __init__(
        self,
        clock: Clock | None = None,
        max_failures: int = DEFAULT_MAX_FAILURES,
        lockout_seconds: float = DEFAULT_LOCKOUT_SECONDS,
    ) -> None:
        self._clock: Clock = clock or SystemClock()
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def _expire(self, key: str) -> None:
        until = self._locked_until.get(key)
        if until is not None and self._clock.timestamp() >= until:
            del self._locked_until[key]
            self._failures.pop(key, None)

    def is_locked(self, username: str) -> bool:
        key = _key(username)
        with self._lock:
            self._expire(key)
            return key in self._locked_until

    def record_failure(self, username: str) -> None:
        key = _key(username)
        with self._lock:
            self._expire(key)
            if key in self._locked_until:
                return
            count = self._failures.get(key, 0) + 1
            self._failures[key] = count
            if count >= self._max_failures:
                self._locked_until[key] = self._clock.timestamp() + self._lockout_seconds

    def record_success(self, username: str) -> None:
        key = _key(username)
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def failure_count(self, username: str) -> int:
        key = _key(username)
        with self._lock:
            self._expire(key)
            return self._failures.get(key, 0)
