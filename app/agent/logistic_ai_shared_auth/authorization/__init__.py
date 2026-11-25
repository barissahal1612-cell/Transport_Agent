"""Authorization module of the Shared_Auth_Package."""

from .authorizer import Authorizer, Decision, PermissionDenied
from .permission_table import PermissionTable, PermissionTableError
from .roles import (
    Role,
    RoleResolutionError,
    RoleResolutionErrorKind,
    VerifiedIdentity,
    resolve_role,
)
from .token_verifier import (
    Claims,
    JwksSigningKeyProvider,
    SigningKeyProvider,
    TokenVerificationError,
    TokenVerifier,
    resolve_identity,
)

__all__ = [
    "Claims",
    "JwksSigningKeyProvider",
    "SigningKeyProvider",
    "TokenVerificationError",
    "TokenVerifier",
    "resolve_identity",
    "Authorizer",
    "Decision",
    "PermissionDenied",
    "PermissionTable",
    "PermissionTableError",
    "Role",
    "RoleResolutionError",
    "RoleResolutionErrorKind",
    "VerifiedIdentity",
    "resolve_role",
]
