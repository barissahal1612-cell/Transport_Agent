"""Fake-model wiring test: main.handle_request -> agent -> tool guard. No Bedrock/AWS calls."""
import asyncio
from typing import Any

import pytest
from strands.models import Model

import main
from agent_factory import build_agent, build_runtime
from identity import SessionTokenIdentityResolver, build_secret_provider
from logistic_ai_data.in_memory import InMemoryDataRepository
from logistic_ai_shared_auth.auth.session_token import (
    EnvSecretProvider,
    SecretsManagerSecretProvider,
    SessionTokenService,
)
from logistic_ai_shared_auth.auth.users import InMemoryUserRepository, UserRecord
from logistic_ai_shared_auth.authorization.permission_store import (
    InMemoryPermissionRepository,
    resource_key,
    role_subject,
)

SECRET = "x" * 32
TOOL_NAME = "get_delayed_truck"


class FakeModel(Model):
    """Turn 1: call the tool; turn 2: answer with text."""

    def __init__(self) -> None:
        self.calls = 0

    def update_config(self, **model_config: Any) -> None: ...

    def get_config(self) -> Any:
        return {}

    async def structured_output(self, *a: Any, **k: Any):  # pragma: no cover
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "t1", "name": TOOL_NAME}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": "{}"}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "Merhaba"}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


def _collect(gen) -> list:
    async def run():
        return [e async for e in gen]

    return asyncio.run(run())


@pytest.fixture
def env():
    users = InMemoryUserRepository(
        [
            UserRecord("U1", "alice", "TRANSPORT_OFFICE", "h", active=True),
            UserRecord("U2", "bob", "TRANSPORT_OFFICE", "h", active=False),
        ]
    )
    perms = InMemoryPermissionRepository()
    perms.put(role_subject("TRANSPORT_OFFICE"), resource_key("FUNCTION", TOOL_NAME), True, "t")
    perms.put(role_subject("TRANSPORT_OFFICE"), resource_key("TABLE", "question4"), True, "t")
    wiring = build_runtime(data_repo=InMemoryDataRepository(), user_repo=users, permission_repo=perms)
    model = FakeModel()
    agent = build_agent(model=model)
    tokens = SessionTokenService(EnvSecretProvider(environ={"LOGISTIC_AI_SESSION_SECRET": SECRET}))
    services = main._Services(SessionTokenIdentityResolver(tokens), wiring.user_repo, lambda messages=None: agent)
    return services, tokens, model


def test_streams_text_events_for_active_user(env):
    services, tokens, model = env
    token = tokens.issue("U1", "alice", "ADMIN")  # role claim is ignored
    out = _collect(main.handle_request({"prompt": "hi", "session_token": token}, None, services))
    assert out == [{"event": {"contentBlockDelta": {"delta": {"text": "Merhaba"}}}}]
    assert model.calls == 2
    # Tool ran as the verified user: permitted (not 'forbidden'), repo empty -> not_found.
    assert "not_found" in str(services.agent_provider().messages)


def test_bearer_header_accepted(env):
    services, tokens, _ = env
    ctx = type("C", (), {"request_headers": {"Authorization": "Bearer " + tokens.issue("U1", "alice", "x")}})()
    out = _collect(main.handle_request({"prompt": "hi"}, ctx, services))
    assert out and "event" in out[0]


@pytest.mark.parametrize("payload", [{"prompt": "hi"}, {"prompt": "hi", "session_token": "bad"}])
def test_missing_or_invalid_token_rejected(env, payload):
    out = _collect(main.handle_request(payload, None, env[0]))
    assert out == [{"error": "unauthenticated", "message": main.UNAUTHENTICATED_MESSAGE}]


def test_inactive_and_unknown_user_rejected(env):
    services, tokens, model = env
    for uid in ("U2", "NOPE"):
        token = tokens.issue(uid, "x", "ADMIN")
        out = _collect(main.handle_request({"prompt": "hi", "session_token": token}, None, services))
        assert out[0]["error"] == "unauthenticated"
    assert model.calls == 0


def test_validation_error_and_generic_internal_error(env):
    services, tokens, _ = env
    assert _collect(main.handle_request({"prompt": " "}, None, services))[0]["error"] == "validation_error"

    def boom(messages=None):
        raise RuntimeError("secret detail")

    services.agent_provider = boom
    token = tokens.issue("U1", "alice", "x")
    out = _collect(main.handle_request({"prompt": "hi", "session_token": token}, None, services))
    assert out[0]["error"] == "internal_error" and "secret detail" not in out[0]["message"]


def test_secret_provider_selection():
    assert isinstance(build_secret_provider({"LOGISTIC_AI_SESSION_SECRET_ID": "sid"}), SecretsManagerSecretProvider)
    assert isinstance(build_secret_provider({}), EnvSecretProvider)
