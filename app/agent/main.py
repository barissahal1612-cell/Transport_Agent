"""Logistics AI Agent_Backend giriş noktası (Faz 2).

Akış: parse_payload -> Session_Token (payload ``session_token`` veya Bearer başlığı) ->
IdentityResolver -> kullanıcıyı User_Store'dan oku (yok/pasifse reddet; rol depodan) ->
ajanı ``invocation_state={'userid': ...}`` ile akıt. Her şey tembel kurulur.

Requirements: 3.6, 5.12, 8.2, 8.3.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from logistic_ai_shared_auth.common.errors import safe_error_message
from logistic_ai_shared_auth.common.log_sanitizer import SanitizingFilter
from strands.types.exceptions import MaxTokensReachedException

from parse import history_to_strands_messages, parse_history, parse_payload

RESPONSE_TOO_LONG_MESSAGE = "Yanıt çok uzun olduğu için tamamlanamadı. Lütfen sorunuzu daraltarak tekrar deneyin."
UNAUTHENTICATED_MESSAGE = "Kimlik doğrulama gerekli veya geçersiz"
FORBIDDEN_MESSAGE = "Bu işlem için yetkiniz yok"

_logger = logging.getLogger("logistic_ai.agent")


@dataclass
class _Services:
    identity: Any  # IdentityResolver
    users: Any  # UserRepository
    agent_provider: Any  # (messages=None) -> Strands Agent; fresh per request in production


_services: _Services | None = None
_model: Any = None


def _install_log_sanitizer() -> None:
    sanitizer = SanitizingFilter()
    for name in ("", "logistic_ai", "logistic_ai.audit", "logistic_ai.agent", "logistic_ai.authorization"):
        target = logging.getLogger(name)
        if not any(isinstance(f, SanitizingFilter) for f in target.filters):
            target.addFilter(sanitizer)
        for handler in target.handlers:
            if not any(isinstance(f, SanitizingFilter) for f in handler.filters):
                handler.addFilter(sanitizer)


def _get_agent(messages: list[dict[str, Any]] | None = None) -> Any:
    """Build a NEW agent for one request.

    Only the (stateless) model client is cached; an Agent holds conversation state, so a
    cached Agent would mix the histories of different users. ``messages`` are the validated
    prior turns the client sent with this request (no persistent memory).
    """
    global _model
    from agent_factory import build_agent

    if _model is None:
        from model.load import load_model

        _model = load_model()
    return build_agent(model=_model, messages=messages)


def _get_services() -> _Services:
    global _services
    if _services is None:
        _install_log_sanitizer()
        from agent_factory import build_runtime
        from identity import SessionTokenIdentityResolver

        wiring = build_runtime()
        _services = _Services(
            identity=SessionTokenIdentityResolver.from_environment(),
            users=wiring.user_repo,
            agent_provider=_get_agent,
        )
    return _services


def _text_event(text: str) -> dict[str, Any]:
    return {"event": {"contentBlockDelta": {"delta": {"text": text}}}}


def _error_event(code: str, message: str) -> dict[str, Any]:
    return {"error": code, "message": message}


async def handle_request(payload: Any, context: Any, services: _Services | None = None) -> AsyncIterator[dict[str, Any]]:
    """İstek akışı; testlerde ``services`` enjekte edilebilir."""
    from identity import IdentityError

    try:
        prompt, _actor_id, parse_error = parse_payload(payload)
        if parse_error is not None:
            yield _error_event("validation_error", parse_error)
            return
        svc = services or _get_services()
        try:
            session = svc.identity.resolve(context, payload)
        except IdentityError:
            yield _error_event("unauthenticated", UNAUTHENTICATED_MESSAGE)
            return
        user = svc.users.get_by_userid(session.userid)
        if user is None or not user.active:
            yield _error_event("unauthenticated", UNAUTHENTICATED_MESSAGE)
            return
        history = history_to_strands_messages(parse_history(payload))
        agent = svc.agent_provider(history)
        # Rol token'dan değil depodan; araçlar yalnızca userid'i invocation_state'ten okur.
        async for event in agent.stream_async(prompt, invocation_state={"userid": user.userid}):
            if isinstance(event, dict):
                text = event.get("data")
                if isinstance(text, str) and text:
                    yield _text_event(text)
    except MaxTokensReachedException as exc:
        safe_error_message(exc)  # ayrıntı yalnızca günlüğe
        yield _error_event("response_too_long", RESPONSE_TOO_LONG_MESSAGE)
    except Exception as exc:  # noqa: BLE001 - teknik ayrıntı sızdırılmaz
        yield _error_event("internal_error", safe_error_message(exc))


def create_app() -> BedrockAgentCoreApp:
    app = BedrockAgentCoreApp()

    @app.entrypoint
    async def invoke(payload: Any, context: Any) -> AsyncIterator[dict[str, Any]]:
        async for item in handle_request(payload, context):
            yield item

    return app


app = create_app()

if __name__ == "__main__":
    app.run()
