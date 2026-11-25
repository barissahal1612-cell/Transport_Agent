"""Streamlit_Client configuration loading (Req 6.8, 6.9, 8.1, 8.4, 8.5).

Values come from environment variables; an optional ``SecretFetcher`` may
supply required values that are missing from the environment. Error messages
contain variable names only, never values.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

ENV_USER_POOL_ID = "LOGISTIC_AI_USER_POOL_ID"
ENV_APP_CLIENT_ID = "LOGISTIC_AI_APP_CLIENT_ID"
ENV_AWS_REGION = "LOGISTIC_AI_AWS_REGION"
ENV_AGENT_RUNTIME_ARN = "LOGISTIC_AI_AGENT_RUNTIME_ARN"
ENV_IDLE_TIMEOUT = "LOGISTIC_AI_IDLE_TIMEOUT_MINUTES"
ENV_PERMISSIONS_FILE = "LOGISTIC_AI_PERMISSIONS_FILE"
ENV_COGNITO_ENDPOINT_URL = "LOGISTIC_AI_COGNITO_ENDPOINT_URL"
# Local mode: chat requests go to a local `agentcore dev` server instead of AgentCore Runtime.
ENV_LOCAL_AGENT_URL = "LOGISTIC_AI_LOCAL_AGENT_URL"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Faz 2 (role_user auth): Cognito pool/client are no longer required. The
# DynamoDB table names (LOGISTIC_AI_USERS_TABLE, ...) are read by the repositories.
REQUIRED_VARIABLES: tuple[str, ...] = (
    ENV_AWS_REGION,
    ENV_AGENT_RUNTIME_ARN,
)

DEFAULT_IDLE_TIMEOUT_MINUTES = 30
MIN_IDLE_TIMEOUT_MINUTES = 1
MAX_IDLE_TIMEOUT_MINUTES = 480
DEFAULT_FETCH_TIMEOUT_S = 10.0
SECRET_STORE_ERROR_MESSAGE = "Secret_Store erişim hatası"


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid.

    ``missing`` holds variable names only, never values.
    """

    def __init__(self, missing: Sequence[str], message: str | None = None) -> None:
        self.missing: list[str] = list(missing)
        super().__init__(
            message
            if message is not None
            else "Eksik veya geçersiz yapılandırma: " + ", ".join(self.missing)
        )


class SecretStoreError(ConfigError):
    """Secret_Store timed out or failed (Req 8.5)."""

    def __init__(self) -> None:
        super().__init__([], SECRET_STORE_ERROR_MESSAGE)


class SecretFetcher(Protocol):
    """Optional abstraction over a secret store (e.g. AWS Secrets Manager)."""

    def fetch(self, names: Sequence[str]) -> Mapping[str, str]:
        """Return values for the requested variable names (missing ones omitted)."""
        ...


def validate_local_agent_url(url: str) -> str:
    """Return ``url`` if it is an http(s) URL on a loopback host, else raise ``ConfigError``."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        host = parsed.hostname
        parsed.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError:
        raise ConfigError([ENV_LOCAL_AGENT_URL]) from None
    if parsed.scheme not in ("http", "https") or host not in LOOPBACK_HOSTS or parsed.username:
        raise ConfigError([ENV_LOCAL_AGENT_URL])
    return url


@dataclass(frozen=True)
class Settings:
    aws_region: str
    agent_runtime_arn: str
    idle_timeout_minutes: int = DEFAULT_IDLE_TIMEOUT_MINUTES
    local_agent_url: str = ""  # non-empty = local mode (loopback only)

    def __repr__(self) -> str:  # avoid dumping configuration values into logs
        return "Settings(...)"


def parse_idle_timeout(raw: str | None) -> int:
    """Return the idle timeout in minutes; 30 unless ``raw`` is an integer in 1..480."""
    if raw is None:
        return DEFAULT_IDLE_TIMEOUT_MINUTES
    text = raw.strip()
    if not text.isascii() or not text.isdigit():
        return DEFAULT_IDLE_TIMEOUT_MINUTES
    value = int(text)
    if MIN_IDLE_TIMEOUT_MINUTES <= value <= MAX_IDLE_TIMEOUT_MINUTES:
        return value
    return DEFAULT_IDLE_TIMEOUT_MINUTES


def _fetch_secrets(
    fetcher: SecretFetcher, names: Sequence[str], timeout_s: float
) -> Mapping[str, str]:
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(fetcher.fetch, list(names))
        try:
            result = future.result(timeout=timeout_s)
        except Exception:  # timeout or any fetch failure; details never surfaced
            raise SecretStoreError() from None
        if not isinstance(result, Mapping):
            raise SecretStoreError()
        return result
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _clean(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def load_settings(
    env: Mapping[str, str],
    secret_fetcher: SecretFetcher | None = None,
    fetch_timeout_s: float = DEFAULT_FETCH_TIMEOUT_S,
) -> Settings:
    """Build ``Settings`` from ``env`` (and ``secret_fetcher`` for absent values).

    Raises ``ConfigError`` naming only the missing/invalid variables, or
    ``SecretStoreError`` if the secret store fails or times out.
    """
    local_url = _clean(env.get(ENV_LOCAL_AGENT_URL))
    if local_url:
        validate_local_agent_url(local_url)
    # Local mode talks to `agentcore dev`, so no runtime ARN is needed.
    required = tuple(n for n in REQUIRED_VARIABLES if not (local_url and n == ENV_AGENT_RUNTIME_ARN))
    values = {name: _clean(env.get(name)) for name in REQUIRED_VARIABLES}

    absent = [n for n in required if not values[n]]
    if absent and secret_fetcher is not None:
        fetched = _fetch_secrets(secret_fetcher, absent, fetch_timeout_s)
        for name in absent:
            values[name] = _clean(fetched.get(name))

    invalid = [n for n in required if not values[n]]

    if invalid:
        raise ConfigError(invalid)

    return Settings(
        aws_region=values[ENV_AWS_REGION],
        agent_runtime_arn=values[ENV_AGENT_RUNTIME_ARN],
        idle_timeout_minutes=parse_idle_timeout(env.get(ENV_IDLE_TIMEOUT)),
        local_agent_url=local_url,
    )
