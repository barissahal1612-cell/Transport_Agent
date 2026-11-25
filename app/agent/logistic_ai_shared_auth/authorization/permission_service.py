"""Dynamic, deny-by-default permission checks (Requirements 3.1, 3.3-3.9, 5.10).

Decision order: (1) user missing/inactive -> deny; (2) auth tables -> deny;
(3) user-level record; (4) role-level record; (5) default deny.
Results are cached for ``ttl_seconds`` (30 s; requirement 3.7 allows <= 60 s).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

from ..auth.users import UserRepository
from ..common.audit import AuditLogger
from ..common.clock import Clock, SystemClock
from .authorizer import DENIED_MESSAGE, Decision, PermissionDenied
from .permission_store import (
    PermissionRepository,
    resource_key,
    role_subject,
    user_subject,
)
from .resources import AUTH_TABLES, FUNCTION, TABLE, is_known_resource

DEFAULT_TTL_SECONDS = 30.0
_logger = logging.getLogger("logistic_ai.authorization")


class PermissionService:
    def __init__(
        self,
        users: UserRepository,
        permissions: PermissionRepository,
        audit: AuditLogger | None = None,
        clock: Clock | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._users = users
        self._permissions = permissions
        self._audit = audit
        self._clock = clock or SystemClock()
        self._ttl = ttl_seconds
        self._cache: dict[tuple[str, str, str], tuple[bool, str, str | None, float]] = {}
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    def check(self, userid: str, resource_type: str, resource: str) -> Decision:
        permission = f"{resource_type}:{resource}"
        key = (str(userid), str(resource_type), str(resource))
        now = self._clock.timestamp()
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None and hit[3] > now:
            allowed, username, role, _ = hit
        else:
            allowed, username, role = self._evaluate(*key)
            with self._lock:
                self._cache[key] = (allowed, username, role, now + self._ttl)
        decision = Decision(allowed=allowed, username=username, role=role, permission=permission)
        if not allowed:
            self._audit_denied(userid, decision)
        return decision

    def require_tool(self, userid: str, function: str, tables: Sequence[str]) -> None:
        """Require FUNCTION and every TABLE permission; raise PermissionDenied otherwise."""
        checks = [(FUNCTION, function)] + [(TABLE, t) for t in tables]
        denied = False
        for rtype, name in checks:
            if not self.check(userid, rtype, name).allowed:
                denied = True
        if denied:
            raise PermissionDenied(DENIED_MESSAGE)

    def _evaluate(self, userid: str, rtype: str, resource: str) -> tuple[bool, str, str | None]:
        try:
            user = self._users.get_by_userid(userid) if userid else None
        except Exception:
            _logger.error("permission user lookup failed")
            return False, "", None
        if user is None or not user.active:
            return False, user.username if user else "", user.role if user else None
        username, role = user.username, user.role
        if resource in AUTH_TABLES or not is_known_resource(rtype, resource):
            return False, username, role
        rkey = resource_key(rtype, resource)
        try:
            for subject in (user_subject(user.userid), role_subject(user.role)):
                value = self._permissions.get(subject, rkey)
                if value is not None:
                    return bool(value), username, role
        except Exception:
            _logger.error("permission lookup failed")
        return False, username, role

    def _audit_denied(self, userid: str, decision: Decision) -> None:
        if self._audit is None:
            return
        try:
            self._audit.log_authorization_denied(
                decision.username or str(userid), decision.role, decision.permission
            )
        except Exception:
            try:
                _logger.error("authorization_denied audit failed")
            except Exception:
                pass
