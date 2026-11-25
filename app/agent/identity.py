"""Kimlik çözümleme (design.md Açık Karar 1): taşıma katmanından bağımsız ``IdentityResolver``.

Varsayılan uygulama payload'daki ``session_token`` alanını (veya ``Authorization: Bearer``
başlığını) HS256 Session_Token olarak doğrular. Rol token'dan değil User_Store'dan okunur.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Protocol, runtime_checkable

from logistic_ai_shared_auth.auth.session_token import (
    DEFAULT_SECRET_ENV,
    EnvSecretProvider,
    SecretProvider,
    SecretsManagerSecretProvider,
    SessionTokenError,
    SessionTokenService,
    VerifiedSession,
)

ENV_SECRET_ID = "LOGISTIC_AI_SESSION_SECRET_ID"
ENV_SECRET = DEFAULT_SECRET_ENV  # LOGISTIC_AI_SESSION_SECRET
PAYLOAD_TOKEN_FIELD = "session_token"


class IdentityError(Exception):
    """Kimlik doğrulanamadı (ayrıntı kullanıcıya gösterilmez)."""


@runtime_checkable
class IdentityResolver(Protocol):
    def resolve(self, context: Any, payload: Any) -> VerifiedSession: ...


def bearer_token(context: Any) -> str | None:
    headers = getattr(context, "request_headers", None)
    if not isinstance(headers, Mapping):
        return None
    for name, value in headers.items():
        if isinstance(name, str) and name.lower() == "authorization" and isinstance(value, str):
            scheme, _, token = value.strip().partition(" ")
            if scheme.lower() == "bearer" and token.strip():
                return token.strip()
    return None


def extract_token(context: Any, payload: Any) -> str | None:
    if isinstance(payload, dict):
        value = payload.get(PAYLOAD_TOKEN_FIELD)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return bearer_token(context)


def build_secret_provider(environ: Mapping[str, str] | None = None) -> SecretProvider:
    env = environ if environ is not None else os.environ
    secret_id = (env.get(ENV_SECRET_ID) or "").strip()
    if secret_id:
        return SecretsManagerSecretProvider(secret_id)
    return EnvSecretProvider(ENV_SECRET, environ=env)


class SessionTokenIdentityResolver:
    def __init__(self, tokens: SessionTokenService) -> None:
        self._tokens = tokens

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "SessionTokenIdentityResolver":
        return cls(SessionTokenService(build_secret_provider(environ)))

    def resolve(self, context: Any, payload: Any) -> VerifiedSession:
        token = extract_token(context, payload)
        if token is None:
            raise IdentityError("missing token")
        try:
            return self._tokens.verify(token)
        except SessionTokenError as exc:
            raise IdentityError("invalid token") from exc
