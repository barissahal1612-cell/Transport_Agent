"""Cognito JWT verification and identity resolution.

``TokenVerifier`` takes explicit ``user_pool_id``, ``app_client_id`` and ``region``
values (no dependency on any Streamlit ``Settings`` object), so it can be used by
both the Streamlit_Client and the Agent_Backend.

Requirements: 3.2, 3.3, 3.4, 3.7, 13.9.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient

from ..common.clock import Clock, SystemClock
from .roles import VerifiedIdentity, resolve_role

_LOGGER = logging.getLogger("logistic_ai.authorization")

_ALGORITHMS = ["RS256"]
_VALID_TOKEN_USES = frozenset({"id", "access"})


class TokenVerificationError(Exception):
    """Raised for any missing, malformed or unverifiable token.

    The message is generic on purpose; the cause is logged without token content.
    """

    def __init__(self, reason: str = "invalid_token") -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Claims:
    """Verified token claims."""

    username: str
    groups: tuple[str, ...]
    expires_at: int
    token_use: str
    subject: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


class SigningKeyProvider(Protocol):
    """Returns the public signing key for a token (selected by its ``kid``)."""

    def get_signing_key(self, token: str) -> Any: ...


class JwksSigningKeyProvider:
    """``PyJWKClient`` based provider with a cached JWKS.

    For an unknown ``kid`` the JWKS is refreshed exactly once before failing.
    """

    def __init__(
        self,
        user_pool_id: str,
        region: str,
        *,
        jwk_client: PyJWKClient | None = None,
        cache_lifespan: int = 3600,
        timeout: int = 5,
    ) -> None:
        if jwk_client is None:
            url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
            jwk_client = PyJWKClient(
                url,
                cache_keys=True,
                cache_jwk_set=True,
                lifespan=cache_lifespan,
                timeout=timeout,
            )
        self._client = jwk_client

    def get_signing_key(self, token: str) -> Any:
        # PyJWKClient.get_signing_key_from_jwt looks the kid up in the cached set and,
        # when it is missing, re-fetches the JWKS once before raising.
        return self._client.get_signing_key_from_jwt(token).key


class TokenVerifier:
    """Verifies Cognito-issued JWTs (signature, ``exp``, ``iss``, audience, ``token_use``).

    ``expected_token_use`` is ``"id"`` (default; audience in ``aud``) or ``"access"``
    (client in ``client_id``, as Cognito access tokens carry no ``aud``).
    """

    def __init__(
        self,
        user_pool_id: str,
        app_client_id: str,
        region: str,
        key_provider: SigningKeyProvider | None = None,
        clock: Clock | None = None,
        expected_token_use: str = "id",
        leeway_seconds: int = 0,
    ) -> None:
        if not user_pool_id or not app_client_id or not region:
            raise ValueError("user_pool_id, app_client_id and region are required")
        if expected_token_use not in _VALID_TOKEN_USES:
            raise ValueError("expected_token_use must be 'id' or 'access'")
        self._app_client_id = app_client_id
        self._issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self._key_provider = key_provider or JwksSigningKeyProvider(user_pool_id, region)
        self._clock = clock or SystemClock()
        self._expected_token_use = expected_token_use
        self._leeway = leeway_seconds

    @property
    def issuer(self) -> str:
        return self._issuer

    def verify(self, token: str) -> Claims:
        """Return verified claims or raise ``TokenVerificationError``."""
        if not isinstance(token, str) or not token.strip():
            raise TokenVerificationError("missing_token")
        token = token.strip()
        try:
            key = self._key_provider.get_signing_key(token)
            payload = jwt.decode(
                token,
                key=key,
                algorithms=_ALGORITHMS,
                issuer=self._issuer,
                # ``exp`` is checked below against the injected clock.
                options={
                    "verify_exp": False,
                    "verify_aud": False,
                    "verify_iss": True,
                    "require": ["exp", "iss"],
                },
            )
        except Exception as exc:  # noqa: BLE001 - any failure means rejection
            _LOGGER.warning("Token verification failed: %s", type(exc).__name__)
            raise TokenVerificationError("invalid_token") from None

        if not isinstance(payload, dict):
            raise TokenVerificationError("invalid_token")

        exp = payload.get("exp")
        if isinstance(exp, bool) or not isinstance(exp, (int, float)):
            raise TokenVerificationError("invalid_token")
        if self._clock.timestamp() >= exp + self._leeway:
            raise TokenVerificationError("expired_token")

        token_use = payload.get("token_use")
        if token_use != self._expected_token_use:
            raise TokenVerificationError("wrong_token_use")

        audience_claim = "aud" if token_use == "id" else "client_id"
        audience = payload.get(audience_claim)
        if isinstance(audience, list):
            audience_ok = self._app_client_id in audience
        else:
            audience_ok = audience == self._app_client_id
        if not audience_ok:
            raise TokenVerificationError("invalid_audience")

        username = (
            payload.get("cognito:username") if token_use == "id" else payload.get("username")
        ) or payload.get("cognito:username") or payload.get("username") or payload.get("sub")
        if not isinstance(username, str) or not username:
            raise TokenVerificationError("invalid_token")

        raw_groups = payload.get("cognito:groups")
        if isinstance(raw_groups, list):
            groups = tuple(g for g in raw_groups if isinstance(g, str))
        else:
            groups = ()

        return Claims(
            username=username,
            groups=groups,
            expires_at=int(exp),
            token_use=token_use,
            subject=str(payload.get("sub", "")),
            raw=dict(payload),
        )


def resolve_identity(token: str, verifier: TokenVerifier) -> VerifiedIdentity:
    """Verify ``token`` and derive the role only from the verified ``cognito:groups`` claim.

    Raises ``TokenVerificationError`` or ``RoleResolutionError``.
    """
    claims = verifier.verify(token)
    role = resolve_role(claims.groups)
    return VerifiedIdentity(username=claims.username, role=role, expires_at=claims.expires_at)
