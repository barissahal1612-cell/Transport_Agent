"""Max-token handling: production defaults and graceful error on truncated model output."""
import asyncio
from typing import Any

import pytest
from strands.models import Model
from strands.types.exceptions import MaxTokensReachedException

import main
from agent_factory import build_agent
from identity import SessionTokenIdentityResolver
from logistic_ai_shared_auth.auth.session_token import EnvSecretProvider, SessionTokenService
from logistic_ai_shared_auth.auth.users import InMemoryUserRepository, UserRecord
from logistic_ai_shared_auth.common.errors import GENERIC_ERROR_MESSAGE
from model import load


class TruncatingModel(Model):
    """Model whose answer always stops because the token cap was hit."""

    def update_config(self, **model_config: Any) -> None: ...

    def get_config(self) -> Any:
        return {}

    async def structured_output(self, *a: Any, **k: Any):  # pragma: no cover
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        yield {"contentBlockDelta": {"delta": {"text": "| a | b |"}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "max_tokens"}}


def _run(gen) -> list:
    async def go():
        return [e async for e in gen]
    return asyncio.run(go())


def test_max_tokens_reached_gives_turkish_message_without_details():
    users = InMemoryUserRepository([UserRecord("U1", "alice", "TRANSPORT_OFFICE", "h", active=True)])
    tokens = SessionTokenService(EnvSecretProvider(environ={"LOGISTIC_AI_SESSION_SECRET": "x" * 32}))
    agent = build_agent(model=TruncatingModel())
    services = main._Services(SessionTokenIdentityResolver(tokens), users, lambda messages=None: agent)
    out = _run(main.handle_request({"prompt": "hi", "session_token": tokens.issue("U1", "alice", "x")}, None, services))
    # partial text may already have been streamed; the stream must end with ONE safe error event
    errors = [e for e in out if "error" in e]
    assert errors == [{"error": "response_too_long", "message": main.RESPONSE_TOO_LONG_MESSAGE}]
    assert out[-1] is errors[0]
    assert "MaxTokens" not in errors[0]["message"] and "max_tokens" not in errors[0]["message"]
    assert errors[0]["message"] != GENERIC_ERROR_MESSAGE


def test_max_tokens_default_and_env(monkeypatch):
    monkeypatch.delenv(load.MAX_TOKENS_ENV, raising=False)
    assert load.get_max_tokens() == 4096
    monkeypatch.setenv(load.MAX_TOKENS_ENV, "8000")
    assert load.get_max_tokens() == 8000
    for bad in ("abc", "0", "-5", ""):
        monkeypatch.setenv(load.MAX_TOKENS_ENV, bad)
        assert load.get_max_tokens() == 4096


def test_load_model_sets_max_tokens_and_low_temperature(monkeypatch):
    monkeypatch.setenv(load.MODEL_ID_ENV, "global.anthropic.claude-test")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv(load.MAX_TOKENS_ENV, raising=False)
    cfg = load.load_model().get_config()
    assert cfg["max_tokens"] == 4096
    assert cfg["temperature"] <= 0.2
