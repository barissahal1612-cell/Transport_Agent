"""Immutable role -> permission table (Requirements 4.1, 9.3, 9.4).

File format (``config/permissions.json``)::

    {"version": 1, "roles": {"ROLE": {"permissions": ["perm:a", "perm:b"]}}}

Any invalid definition raises :class:`PermissionTableError`; the existing table
is never modified (``with_definition`` returns a new object).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

MAX_NAME_LENGTH = 64
SUPPORTED_VERSION = 1


class PermissionTableError(Exception):
    """Raised when a permission table or definition is invalid or cannot be loaded."""


def _validate_name(value: object, kind: str) -> str:
    if not isinstance(value, str):
        raise PermissionTableError(f"{kind} name must be a string")
    if not value.strip():
        raise PermissionTableError(f"{kind} name must not be empty")
    if len(value) > MAX_NAME_LENGTH:
        raise PermissionTableError(f"{kind} name must not exceed {MAX_NAME_LENGTH} characters")
    return value


def _validate_permissions(permissions: Iterable[str]) -> frozenset[str]:
    if isinstance(permissions, (str, bytes)) or not isinstance(permissions, Iterable):
        raise PermissionTableError("permissions must be a list of names")
    seen: set[str] = set()
    for permission in permissions:
        name = _validate_name(permission, "permission")
        if name in seen:
            raise PermissionTableError(f"duplicate permission in role: {name!r}")
        seen.add(name)
    return frozenset(seen)


class PermissionTable:
    """Immutable mapping of role name to a frozen set of permission names."""

    __slots__ = ("_roles",)

    def __init__(self, roles: Mapping[str, frozenset[str]]) -> None:
        # Internal constructor; inputs must already be validated.
        self._roles: Mapping[str, frozenset[str]] = MappingProxyType(dict(roles))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Sequence[str]]) -> "PermissionTable":
        if not isinstance(data, Mapping):
            raise PermissionTableError("table definition must be a mapping")
        roles: dict[str, frozenset[str]] = {}
        for role, permissions in data.items():
            name = _validate_name(role, "role")
            if name in roles:
                raise PermissionTableError(f"duplicate role: {name!r}")
            roles[name] = _validate_permissions(permissions)
        return cls(roles)

    @classmethod
    def load(cls, path: Path) -> "PermissionTable":
        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise PermissionTableError(f"duplicate key in permissions file: {key!r}")
                result[key] = value
            return result

        try:
            text = Path(path).read_text(encoding="utf-8")
            raw = json.loads(text, object_pairs_hook=reject_duplicates)
        except PermissionTableError:
            raise
        except (OSError, ValueError) as exc:
            raise PermissionTableError(f"cannot load permissions file: {type(exc).__name__}") from exc

        if not isinstance(raw, dict):
            raise PermissionTableError("permissions file must contain a JSON object")
        if raw.get("version") != SUPPORTED_VERSION or isinstance(raw.get("version"), bool):
            raise PermissionTableError("unsupported or missing permissions file version")
        roles = raw.get("roles")
        if not isinstance(roles, dict):
            raise PermissionTableError("'roles' must be an object")

        mapping: dict[str, Sequence[str]] = {}
        for role, definition in roles.items():
            if not isinstance(definition, dict) or "permissions" not in definition:
                raise PermissionTableError(f"role {role!r} must define 'permissions'")
            permissions = definition["permissions"]
            if not isinstance(permissions, list):
                raise PermissionTableError(f"permissions of role {role!r} must be a list")
            mapping[role] = permissions
        return cls.from_mapping(mapping)

    def with_definition(self, role: str, permissions: Iterable[str]) -> "PermissionTable":
        """Return a new table with ``role`` added; ``self`` is never changed."""
        name = _validate_name(role, "role")
        if name in self._roles:
            raise PermissionTableError(f"role already defined: {name!r}")
        validated = _validate_permissions(permissions)
        updated = dict(self._roles)
        updated[name] = validated
        return PermissionTable(updated)

    def permissions_for(self, role: str) -> frozenset[str]:
        """Permissions of ``role``; empty set for unknown roles (deny by default)."""
        return self._roles.get(role, frozenset())

    @property
    def roles(self) -> frozenset[str]:
        return frozenset(self._roles)

    def to_mapping(self) -> dict[str, list[str]]:
        return {role: sorted(perms) for role, perms in self._roles.items()}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PermissionTable):
            return NotImplemented
        return dict(self._roles) == dict(other._roles)

    def __hash__(self) -> int:
        return hash(frozenset(self._roles.items()))

    def __repr__(self) -> str:
        return f"PermissionTable(roles={sorted(self._roles)})"
