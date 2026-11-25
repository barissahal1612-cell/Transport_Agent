"""Session-token signing secret provider (same convention as ``app/agent/identity.py``).

``LOGISTIC_AI_SESSION_SECRET_ID`` selects a Secrets Manager secret; otherwise the
``LOGISTIC_AI_SESSION_SECRET`` environment variable is used. Nothing is read
until the first token is issued or verified.
"""
from __future__ import annotations

from typing import Mapping

from logistic_ai_shared_auth.auth.session_token import (
    DEFAULT_SECRET_ENV,
    EnvSecretProvider,
    SecretProvider,
    SecretsManagerSecretProvider,
)

ENV_SECRET_ID = "LOGISTIC_AI_SESSION_SECRET_ID"
ENV_SECRET = DEFAULT_SECRET_ENV


def build_secret_provider(
    environ: Mapping[str, str], region: str | None = None
) -> SecretProvider:
    secret_id = (environ.get(ENV_SECRET_ID) or "").strip()
    if secret_id:
        return SecretsManagerSecretProvider(secret_id, region_name=region)
    return EnvSecretProvider(ENV_SECRET, environ=environ)
