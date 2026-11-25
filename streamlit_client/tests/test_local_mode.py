"""Local mode: loopback-only LocalHttpTransport and Settings without a runtime ARN."""
from __future__ import annotations

import json

import pytest

from logistic_ai.config.settings import ConfigError, load_settings
from logistic_ai.session.agentcore_client import (
    AgentCoreClient,
    Boto3Transport,
    LocalHttpTransport,
    build_transport,
)

URL = "http://127.0.0.1:8081/invocations"


class _Resp:
    status_code = 200

    def iter_lines(self, decode_unicode=False):
        ev = {"event": {"contentBlockDelta": {"delta": {"text": "merhaba"}}}}
        return iter(["", "data: " + json.dumps(ev)])

    def close(self):
        pass


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return _Resp()


def test_local_transport_posts_same_json_body_and_parses_sse():
    sess = _Session()
    client = AgentCoreClient("", "r", http=LocalHttpTransport(URL, session=sess))
    out = "".join(client.invoke("tok", "selam", "s" * 40, [{"role": "user", "content": "x"}]))
    assert out == "merhaba"
    url, kw = sess.calls[0]
    assert url == URL
    assert json.loads(kw["data"]) == {
        "prompt": "selam", "session_token": "tok", "history": [{"role": "user", "content": "x"}],
    }


@pytest.mark.parametrize("bad", [
    "https://example.com/invocations", "http://10.0.0.5:8081/invocations",
    "http://127.0.0.1.evil.com/invocations", "ftp://127.0.0.1/x", "http://user@127.0.0.1/x", "",
])
def test_local_transport_refuses_non_loopback(bad):
    with pytest.raises(ConfigError):
        LocalHttpTransport(bad)


def test_build_transport_selection():
    assert isinstance(build_transport({"LOGISTIC_AI_LOCAL_AGENT_URL": URL}, "r"), LocalHttpTransport)
    assert isinstance(build_transport({}, "r"), Boto3Transport)


def test_settings_local_mode_does_not_need_runtime_arn():
    s = load_settings({"LOGISTIC_AI_AWS_REGION": "us-east-1", "LOGISTIC_AI_LOCAL_AGENT_URL": URL})
    assert s.local_agent_url == URL and s.agent_runtime_arn == ""


def test_settings_non_local_still_requires_runtime_arn_and_rejects_remote_url():
    with pytest.raises(ConfigError) as e:
        load_settings({"LOGISTIC_AI_AWS_REGION": "us-east-1"})
    assert e.value.missing == ["LOGISTIC_AI_AGENT_RUNTIME_ARN"]
    with pytest.raises(ConfigError):
        load_settings({"LOGISTIC_AI_AWS_REGION": "us-east-1", "LOGISTIC_AI_LOCAL_AGENT_URL": "https://x.example.com/i"})
