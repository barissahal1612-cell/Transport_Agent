"""Logistics AI Agent_Backend entry point (Phase 1).

Request flow (every request, independent of any Streamlit_Client check):

1. ``parse_payload`` -> validation error is returned without running the agent.
2. The ``Authorization: Bearer`` access token is re-verified with the
   Shared_Auth_Package ``TokenVerifier`` (``expected_token_use="access"``).
3. The role is derived only from the verified ``cognito:groups`` claim; no
   payload field (including ``actorId``) is ever a role source.
4. ``Authorizer.authorize`` (deny by default) checks ``chat:invoke``; a denial
   writes the Requirement 4.5 audit record.
5. Only then the placeholder agent streams the fixed Placeholder_Response.

Requirements: 3.7, 4.5, 4.7, 11.7-11.9, 12.1, 12.2, 12.7, 13.9, 13.10.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from logistic_ai_shared_auth.authorization import (
    Authorizer,
    PermissionTable,
    RoleResolutionError,
    TokenVerificationError,
    TokenVerifier,
    resolve_role,
)
from logistic_ai_shared_auth.authorization.authorizer import DENIED_MESSAGE
from logistic_ai_shared_auth.common.audit import JsonAuditLogger
from logistic_ai_shared_auth.common.errors import safe_error_message
from logistic_ai_shared_auth.common.log_sanitizer import SanitizingFilter
from parse import parse_payload
from placeholder_agent import PlaceholderAgent, build_placeholder_agent

CHAT_PERMISSION = "chat:invoke"
UNAUTHENTICATED_MESSAGE = "Kimlik doğrulama gerekli veya geçersiz"

ENV_USER_POOL_ID = "LOGISTIC_AI_USER_POOL_ID"
ENV_APP_CLIENT_ID = "LOGISTIC_AI_APP_CLIENT_ID"
ENV_REGION = "LOGISTIC_AI_AWS_REGION"
ENV_PERMISSIONS_FILE = "LOGISTIC_AI_PERMISSIONS_FILE"

# Local-development fallback: <project>/config/permissions.json (not packaged by CodeZip).
_DEFAULT_PERMISSIONS_FILE = Path(__file__).resolve().parents[2] / "config" / "permissions.json"

_logger = logging.getLogger("logistic_ai.agent")

# Lazily created on the first request (never at import time).
_agent: PlaceholderAgent | None = None
_security: "_Security | None" = None


@dataclass(frozen=True)
class _Security:
    verifier: TokenVerifier
    authorizer: Authorizer


def _install_log_sanitizer() -> None:
    """Mask tokens/secrets in all handlers of the root and package loggers."""
    sanitizer = SanitizingFilter()
    for name in ("", "logistic_ai", "logistic_ai.audit", "logistic_ai.agent", "logistic_ai.authorization"):
        target = logging.getLogger(name)
        if not any(isinstance(f, SanitizingFilter) for f in target.filters):
            target.addFilter(sanitizer)
        for handler in target.handlers:
            if not any(isinstance(f, SanitizingFilter) for f in handler.filters):
                handler.addFilter(sanitizer)


def _get_agent() -> PlaceholderAgent:
    """Create the placeholder agent on first use (lazy initialization)."""
    global _agent
    if _agent is None:
        _agent = build_placeholder_agent()
    return _agent


def _build_security() -> _Security:
    """Read configuration from environment variables; any gap raises (fail closed)."""
    missing = [
        name
        for name in (ENV_USER_POOL_ID, ENV_APP_CLIENT_ID, ENV_REGION)
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise RuntimeError("missing configuration: " + ", ".join(missing))
    verifier = TokenVerifier(
        user_pool_id=os.environ[ENV_USER_POOL_ID].strip(),
        app_client_id=os.environ[ENV_APP_CLIENT_ID].strip(),
        region=os.environ[ENV_REGION].strip(),
        # The client sends the *access* token as the Bearer token (the AgentCore
        # JWT authorizer validates it via allowedClients / client_id).
        expected_token_use="access",
    )
    permissions_path = Path(os.environ.get(ENV_PERMISSIONS_FILE) or _DEFAULT_PERMISSIONS_FILE)
    table = PermissionTable.load(permissions_path)
    return _Security(verifier=verifier, authorizer=Authorizer(table, JsonAuditLogger()))


def _get_security() -> _Security:
    global _security
    if _security is None:
        _install_log_sanitizer()
        _security = _build_security()
    return _security


def _bearer_token(context: Any) -> str | None:
    """Extract the raw Bearer token from the forwarded ``Authorization`` header."""
    headers = getattr(context, "request_headers", None)
    if not isinstance(headers, dict):
        return None
    for name, value in headers.items():
        if isinstance(name, str) and name.lower() == "authorization" and isinstance(value, str):
            scheme, _, token = value.strip().partition(" ")
            if scheme.lower() == "bearer" and token.strip():
                return token.strip()
    return None


def _text_event(text: str) -> dict[str, Any]:
    return {"event": {"contentBlockDelta": {"delta": {"text": text}}}}


def _error_event(code: str, message: str) -> dict[str, Any]:
    return {"error": code, "message": message}


def _authorize(context: Any) -> tuple[bool, dict[str, Any] | None]:
    """Verify the token, derive the role from verified claims and authorize chat."""
    security = _get_security()
    token = _bearer_token(context)
    if token is None:
        return False, _error_event("unauthenticated", UNAUTHENTICATED_MESSAGE)
    try:
        claims = security.verifier.verify(token)
    except TokenVerificationError:
        return False, _error_event("unauthenticated", UNAUTHENTICATED_MESSAGE)
    try:
        role = resolve_role(claims.groups)
    except RoleResolutionError as exc:
        # No single valid role: deny by default and audit the denial.
        security.authorizer.authorize(claims.username, None, CHAT_PERMISSION)
        return False, _error_event("forbidden", exc.user_message)
    decision = security.authorizer.authorize(claims.username, role, CHAT_PERMISSION)
    if not decision.allowed:
        return False, _error_event("forbidden", DENIED_MESSAGE)
    return True, None


def create_app() -> BedrockAgentCoreApp:
    app = BedrockAgentCoreApp()

    @app.entrypoint
    async def invoke(payload: Any, context: Any) -> AsyncIterator[dict[str, Any]]:
        try:
            prompt, _actor_id, parse_error = parse_payload(payload)
            if parse_error is not None:
                yield _error_event("validation_error", parse_error)
                return
            allowed, error = _authorize(context)
            if not allowed:
                yield error or _error_event("forbidden", DENIED_MESSAGE)
                return
            async for chunk in _get_agent().stream(prompt):
                yield _text_event(chunk)
        except Exception as exc:  # noqa: BLE001 - never leak technical details
            yield _error_event("internal_error", safe_error_message(exc))

    return app


app = create_app()

if __name__ == "__main__":
    app.run()
