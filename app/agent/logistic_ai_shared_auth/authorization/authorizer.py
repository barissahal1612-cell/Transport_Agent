"""Deny-by-default authorizer (Requirements 4.2-4.8).

``authorize`` is a pure decision over (role, permission) and the immutable
:class:`PermissionTable`. On denial a ``authorization_denied`` audit record is
written; failures of the audit logger never change the decision.

``require`` duck-types its ``ctx`` argument (any object with ``username`` and
``role`` attributes), because ``UserContext`` lives in the Streamlit client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..common.audit import AuditLogger
from .permission_table import PermissionTable

DENIED_MESSAGE = "Bu işlem için yetkiniz yok"

_logger = logging.getLogger("logistic_ai.authorization")


class PermissionDenied(Exception):
    """Raised by :meth:`Authorizer.require` when access is denied."""

    def __init__(self, message: str = DENIED_MESSAGE) -> None:
        super().__init__(message)
        self.user_message = message


@dataclass(frozen=True)
class Decision:
    """Outcome of an authorization check."""

    allowed: bool
    username: str
    role: str | None
    permission: str


def _role_name(role: Any) -> str | None:
    if role is None:
        return None
    if isinstance(role, Enum):
        role = role.value
    return role if isinstance(role, str) else None


class Authorizer:
    def __init__(self, table: PermissionTable, audit: AuditLogger | None = None) -> None:
        self._table = table
        self._audit = audit

    def authorize(self, username: str, role: Any, permission: str) -> Decision:
        """Allow only if ``role`` is known and holds ``permission``; otherwise deny and audit."""
        role_name = _role_name(role)
        allowed = (
            role_name is not None
            and isinstance(permission, str)
            and bool(permission)
            and permission in self._table.permissions_for(role_name)
        )
        safe_username = username if isinstance(username, str) else ""
        decision = Decision(
            allowed=allowed,
            username=safe_username,
            role=role_name,
            permission=permission if isinstance(permission, str) else "",
        )
        if not allowed:
            self._audit_denied(decision)
        return decision

    def require(self, ctx: Any, permission: str) -> Decision:
        """Raise :class:`PermissionDenied` unless ``ctx.role`` holds ``permission``.

        A ctx lacking ``username``/``role`` is denied (deny by default).
        """
        username = getattr(ctx, "username", "")
        role = getattr(ctx, "role", None)
        decision = self.authorize(username, role, permission)
        if not decision.allowed:
            raise PermissionDenied(DENIED_MESSAGE)
        return decision

    def _audit_denied(self, decision: Decision) -> None:
        if self._audit is None:
            return
        try:
            self._audit.log_authorization_denied(
                decision.username, decision.role, decision.permission
            )
        except Exception:
            try:
                _logger.error("authorization_denied audit failed")
            except Exception:
                pass
