"""Role definitions and role resolution from verified ``cognito:groups`` claims.

Requirements: 3.1, 3.5, 3.6, 3.8.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    """The three application roles. Matching is exact and case sensitive."""

    SUPPLIER = "SUPPLIER"
    MATERIAL_RESPONSIBLE = "MATERIAL_RESPONSIBLE"
    TRANSPORT_OFFICE = "TRANSPORT_OFFICE"


class RoleResolutionErrorKind(str, Enum):
    NO_ROLE = "NO_ROLE"
    MULTIPLE_ROLES = "MULTIPLE_ROLES"


_USER_MESSAGES: dict[RoleResolutionErrorKind, str] = {
    RoleResolutionErrorKind.NO_ROLE: "Hesabınıza bir rol atanmamış",
    RoleResolutionErrorKind.MULTIPLE_ROLES: (
        "Hesabınıza birden fazla rol atanmış, lütfen yöneticinizle iletişime geçin"
    ),
}


class RoleResolutionError(Exception):
    """Raised when exactly one valid role cannot be determined."""

    def __init__(self, kind: RoleResolutionErrorKind) -> None:
        self.kind = kind
        self.user_message = _USER_MESSAGES[kind]
        super().__init__(kind.value)


# Convenience aliases so callers can use ``RoleResolutionError.NO_ROLE``-style kinds.
RoleResolutionError.NO_ROLE = RoleResolutionErrorKind.NO_ROLE  # type: ignore[attr-defined]
RoleResolutionError.MULTIPLE_ROLES = RoleResolutionErrorKind.MULTIPLE_ROLES  # type: ignore[attr-defined]


@dataclass(frozen=True)
class VerifiedIdentity:
    username: str
    role: Role
    expires_at: int  # ID_Token ``exp``


def resolve_role(groups: Sequence[str] | None) -> Role:
    """Return the single valid role found in ``groups``.

    Invalid group names (including case variants) and duplicates are ignored.
    Raises ``RoleResolutionError`` with ``NO_ROLE`` if no valid role is present
    and ``MULTIPLE_ROLES`` if more than one distinct valid role is present.
    """
    if not groups or isinstance(groups, (str, bytes)):
        raise RoleResolutionError(RoleResolutionErrorKind.NO_ROLE)

    valid_values = {role.value: role for role in Role}
    found: set[Role] = set()
    for group in groups:
        if isinstance(group, str) and group in valid_values:
            found.add(valid_values[group])

    if not found:
        raise RoleResolutionError(RoleResolutionErrorKind.NO_ROLE)
    if len(found) > 1:
        raise RoleResolutionError(RoleResolutionErrorKind.MULTIPLE_ROLES)
    return next(iter(found))
