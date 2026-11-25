"""Admin_Service: user activation and dynamic permission management.

Requirements: 4.2-4.12. The actor is re-verified in the user store (active
ADMIN) on EVERY call. No method assigns the ADMIN role to a user.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..auth.users import ADMIN, ROLES, UserRepository
from ..common.audit import build_audit_record
from ..common.clock import Clock, SystemClock
from .authorizer import PermissionDenied
from .permission_service import PermissionService
from .permission_store import (
    PermissionEntry,
    PermissionRepository,
    resource_key,
    role_subject,
    user_subject,
)
from .resources import AUTH_TABLES, RESOURCE_TYPES, TABLE, is_known_resource

USER = "USER"
ROLE = "ROLE"
SUBJECT_TYPES: tuple[str, ...] = (USER, ROLE)

_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
ADMIN_AUDIT_LOGGER_NAME = "logistic_ai.audit"


class AdminError(ValueError):
    """Invalid admin input (unknown subject/resource, self-deactivation, ...)."""


@dataclass(frozen=True)
class UserView:
    """User listing row. Deliberately has no password hash."""

    userid: str
    username: str
    role: str
    active: bool


@runtime_checkable
class AdminAuditSink(Protocol):
    def log_admin_action(self, record: dict[str, Any]) -> None: ...


class JsonAdminAuditSink:
    """Default sink: one JSON line on the ``logistic_ai.audit`` logger."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(ADMIN_AUDIT_LOGGER_NAME)

    def log_admin_action(self, record: dict[str, Any]) -> None:
        try:
            self._logger.info(json.dumps(record, ensure_ascii=False, default=str))
        except Exception:  # auditing must never break the caller's flow
            logging.getLogger("logistic_ai.audit.errors").error(
                "admin_audit_write_failed event=%s", record.get("event")
            )


class AdminService:
    def __init__(
        self,
        users: UserRepository,
        permissions: PermissionRepository,
        permission_service: PermissionService,
        audit: AdminAuditSink | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._users = users
        self._permissions = permissions
        self._permission_service = permission_service
        self._audit = audit or JsonAdminAuditSink()
        self._clock = clock or SystemClock()

    # ---- public API -------------------------------------------------

    def set_user_active(self, actor: str, target_userid: str, active: bool) -> None:
        admin = self._require_admin(actor, "set_user_active", target_userid)
        target_id = self._valid_id(target_userid, "target_userid")
        target = self._users.get_by_userid(target_id)
        if target is None:
            raise AdminError("Kullanıcı bulunamadı")
        active = bool(active)
        if not active:
            if target.userid == admin.userid:
                raise AdminError("Kendi hesabınızı pasif yapamazsınız")
            if (
                target.role == ADMIN
                and target.active
                and self._users.count_active_admins() <= 1
            ):
                raise AdminError("Son aktif ADMIN pasif yapılamaz")
        old = target.active
        if not self._users.set_active(target.username, active):
            raise AdminError("Kullanıcı bulunamadı")
        self._permission_service.invalidate()
        self._log(admin.userid, "set_user_active", f"USER#{target.userid}", old, active)

    def set_permission(
        self,
        actor: str,
        subject_type: str,
        subject: str,
        resource_type: str,
        resource: str,
        allowed: bool,
    ) -> None:
        admin = self._require_admin(actor, "set_permission", f"{subject_type}#{subject}")
        subj = self._subject_key(subject_type, subject)
        res = self._resource_key(resource_type, resource)
        old = self._permissions.get(subj, res)
        new = bool(allowed)
        self._permissions.put(subj, res, new, admin.userid, self._clock.now().isoformat())
        self._permission_service.invalidate()
        self._log(admin.userid, "set_permission", f"{subj}/{res}", old, new)

    def remove_permission(
        self,
        actor: str,
        subject_type: str,
        subject: str,
        resource_type: str,
        resource: str,
    ) -> None:
        admin = self._require_admin(
            actor, "remove_permission", f"{subject_type}#{subject}"
        )
        subj = self._subject_key(subject_type, subject)
        res = self._resource_key(resource_type, resource)
        old = self._permissions.get(subj, res)
        self._permissions.delete(subj, res)
        self._permission_service.invalidate()
        self._log(admin.userid, "remove_permission", f"{subj}/{res}", old, None)

    def list_users(self, actor: str) -> list[UserView]:
        self._require_admin(actor, "list_users", "*")
        return [
            UserView(u.userid, u.username, u.role, u.active)
            for u in sorted(self._users.list_users(), key=lambda u: u.username)
        ]

    def list_permissions(
        self, actor: str, subject_type: str, subject: str
    ) -> list[PermissionEntry]:
        self._require_admin(actor, "list_permissions", f"{subject_type}#{subject}")
        return self._permissions.list_for_subject(
            self._subject_key(subject_type, subject)
        )

    # ---- helpers ----------------------------------------------------

    def _require_admin(self, actor: Any, action: str, target: str):
        user = None
        if isinstance(actor, str) and actor:
            user = self._users.get_by_userid(actor)
        if user is None or not user.active or user.role != ADMIN:
            self._log(str(actor)[:64], action, str(target)[:128], None, None, outcome="denied")
            raise PermissionDenied()
        return user

    @staticmethod
    def _valid_id(value: Any, name: str) -> str:
        if not isinstance(value, str) or not _ID_RE.match(value):
            raise AdminError(f"Geçersiz {name}")
        return value

    def _subject_key(self, subject_type: str, subject: str) -> str:
        if subject_type == ROLE:
            if subject not in ROLES:
                raise AdminError("Bilinmeyen rol")
            return role_subject(subject)
        if subject_type == USER:
            userid = self._valid_id(subject, "userid")
            if self._users.get_by_userid(userid) is None:
                raise AdminError("Kullanıcı bulunamadı")
            return user_subject(userid)
        raise AdminError("subject_type USER veya ROLE olmalı")

    @staticmethod
    def _resource_key(resource_type: str, resource: str) -> str:
        if resource_type not in RESOURCE_TYPES:
            raise AdminError("Geçersiz kaynak türü")
        if resource_type == TABLE and resource in AUTH_TABLES:
            raise AdminError("Kimlik doğrulama tabloları için izin verilemez")
        if not is_known_resource(resource_type, resource):
            raise AdminError("Bilinmeyen kaynak")
        return resource_key(resource_type, resource)

    def _log(
        self,
        actor: str,
        action: str,
        target: str,
        old: Any,
        new: Any,
        outcome: str = "ok",
    ) -> None:
        record = build_audit_record(
            "admin_action",
            actor,
            clock=self._clock,
            action=action,
            target=target,
            old_value=old,
            new_value=new,
            outcome=outcome,
        )
        try:
            self._audit.log_admin_action(record)
        except Exception:
            logging.getLogger("logistic_ai.audit.errors").error(
                "admin_audit_write_failed action=%s", action
            )
