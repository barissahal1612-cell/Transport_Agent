"""AgentCore_Runtime istemcisi (boto3 ``invoke_agent_runtime``, SigV4; Açık Karar 1 seçenek A).

Yük ``prompt`` ve ``session_token`` içerir. Req 2.6, 2.8, 10.4.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from logistic_ai_shared_auth.common.clock import Clock, SystemClock
from logistic_ai_shared_auth.common.errors import GENERIC_ERROR_MESSAGE

_logger = logging.getLogger("logistic_ai.agentcore_client")

REQUEST_TIMEOUT_S = 30.0
MIN_SESSION_ID_LENGTH = 33
HISTORY_MAX_MESSAGES = 10
HISTORY_MAX_CONTENT_CHARS = 2000
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"


class AgentCoreUnauthorized(Exception):
    """Runtime kimlik doğrulamasını reddetti (Session_Token geçersiz/süresi dolmuş)."""


class AgentCoreError(Exception):
    """Ağ hatası/zaman aşımı/beklenmeyen yanıt; mesaj teknik ayrıntı içermez (Req 13.8, 10.4)."""

    def __init__(self, message: str = GENERIC_ERROR_MESSAGE) -> None:
        super().__init__(message)


@dataclass
class HttpResponse:
    status_code: int
    lines: Iterable[str] = field(default_factory=list)
    close: Any = None  # isteğe bağlı: kaynağı serbest bırakan callable


class HttpTransport(Protocol):
    """Transport seam; tests inject a fake so no AWS call is ever made."""

    def invoke(
        self, runtime_arn: str, session_id: str, body: bytes, timeout: float
    ) -> HttpResponse:
        """Send ``body`` to the runtime; raises on network/timeout errors."""
        ...


class Boto3Transport:
    """Production transport (Open Decision 1, option A).

    ``bedrock-agentcore`` ``InvokeAgentRuntime`` signed with SigV4 using the
    Streamlit_Client's own AWS credentials. The user identity travels as the
    ``session_token`` field of the payload.
    """

    def __init__(self, region: str, client: Any = None) -> None:
        self._region = region
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-agentcore",
                region_name=self._region,
                config=Config(read_timeout=int(REQUEST_TIMEOUT_S), retries={"max_attempts": 1}),
            )
        return self._client

    def invoke(
        self, runtime_arn: str, session_id: str, body: bytes, timeout: float
    ) -> HttpResponse:
        from botocore.exceptions import ClientError

        try:
            result = self._get_client().invoke_agent_runtime(
                agentRuntimeArn=runtime_arn,
                runtimeSessionId=session_id,
                contentType="application/json",
                accept="application/json",
                payload=body,
                qualifier="DEFAULT",
            )
        except ClientError as exc:
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 500))
            return HttpResponse(status_code=status)
        status = int(result.get("ResponseMetadata", {}).get("HTTPStatusCode", 200))
        stream = result.get("response")
        if stream is None:
            return HttpResponse(status_code=status)
        return HttpResponse(
            status_code=status,
            lines=stream.iter_lines(),
            close=getattr(stream, "close", None),
        )


class LocalHttpTransport:
    """Local-mode transport: POST the same JSON body to a local ``agentcore dev`` server.

    Selected when ``LOGISTIC_AI_LOCAL_AGENT_URL`` is set (e.g. ``http://127.0.0.1:8081/invocations``).
    Non-loopback URLs are refused, so no request can leave the machine.
    """

    def __init__(self, url: str, session: Any = None) -> None:
        from logistic_ai.config.settings import validate_local_agent_url

        self._url = validate_local_agent_url(url)
        self._session = session

    def invoke(
        self, runtime_arn: str, session_id: str, body: bytes, timeout: float
    ) -> HttpResponse:
        import requests

        http = self._session or requests
        resp = http.post(
            self._url,
            data=body,
            headers={"Content-Type": "application/json", SESSION_HEADER: session_id},
            stream=True,
            timeout=(5.0, timeout),
        )
        return HttpResponse(
            status_code=int(resp.status_code),
            lines=resp.iter_lines(decode_unicode=True),
            close=getattr(resp, "close", None),
        )


def build_transport(env: Any, region: str) -> HttpTransport:
    """``LocalHttpTransport`` when ``LOGISTIC_AI_LOCAL_AGENT_URL`` is set, else ``Boto3Transport``."""
    from logistic_ai.config.settings import ENV_LOCAL_AGENT_URL

    url = (env.get(ENV_LOCAL_AGENT_URL) or "").strip()
    return LocalHttpTransport(url) if url else Boto3Transport(region)


def normalize_session_id(session_id: str) -> str:
    """En az 33 karakterli oturum kimliği döndürür (kısaysa belirleyici olarak doldurur)."""
    sid = session_id or ""
    if len(sid) >= MIN_SESSION_ID_LENGTH:
        return sid
    pad = hashlib.sha256(sid.encode("utf-8")).hexdigest()
    return (sid + "-" + pad)[: max(MIN_SESSION_ID_LENGTH, len(sid) + 1 + 32)]


def _extract_text(payload: str) -> str:
    """Bir SSE ``data:`` değerinden metni çıkarır."""
    try:
        obj = json.loads(payload)
    except (ValueError, TypeError):
        return payload
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        if obj.get("error") == "unauthenticated":
            raise AgentCoreUnauthorized()
        if isinstance(obj.get("error"), str):
            raise AgentCoreError()
        if isinstance(obj.get("event"), dict):
            obj = obj["event"]
        text = (
            obj.get("contentBlockDelta", {}).get("delta", {}).get("text")
            if isinstance(obj.get("contentBlockDelta"), dict)
            else None
        )
        if isinstance(text, str):
            return text
        for key in ("text", "response", "message"):
            if isinstance(obj.get(key), str):
                return obj[key]
    return ""


def build_history_payload(history: Iterable[Any] | None) -> list[dict[str, str]]:
    """Last ``HISTORY_MAX_MESSAGES`` user/assistant messages, content cut to 2000 chars."""
    out: list[dict[str, str]] = []
    for m in history or []:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
            out.append({"role": m["role"], "content": m["content"][:HISTORY_MAX_CONTENT_CHARS]})
    return out[-HISTORY_MAX_MESSAGES:]


class AgentCoreClient:
    def __init__(
        self,
        runtime_arn: str,
        region: str,
        settings: Any = None,
        http: HttpTransport | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._runtime_arn = runtime_arn
        self._region = region
        self._settings = settings
        self._http: HttpTransport = http or Boto3Transport(region)
        self._clock = clock or SystemClock()

    def invoke(
        self,
        session_token: str,
        prompt: str,
        session_id: str,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        """Yanıt metin parçalarını üretir. Kimlik reddi → ``AgentCoreUnauthorized``.

        ``history``: mevcut oturumun önceki mesajları; yalnızca bu istek için gönderilir.
        """
        payload: dict[str, Any] = {"prompt": prompt, "session_token": session_token}
        hist = build_history_payload(history)
        if hist:
            payload["history"] = hist
        body = json.dumps(payload).encode("utf-8")
        try:
            resp = self._http.invoke(
                self._runtime_arn, normalize_session_id(session_id), body, REQUEST_TIMEOUT_S
            )
        except Exception as exc:  # ağ/zaman aşımı: ayrıntı yalnızca günlükte
            self._log_failure("request_failed", type(exc).__name__)
            raise AgentCoreError() from None

        return self._stream(resp)

    def _stream(self, resp: HttpResponse) -> Iterator[str]:
        # Durum denetimi, yineleyici tüketilmeden önce yapılsın diye burada.
        status = resp.status_code
        # 401/403 here mean the client's own AWS credentials are rejected (SigV4),
        # not the user's session; the user-level rejection arrives as an event.
        if not 200 <= status < 300:
            self._close(resp)
            self._log_failure("unexpected_status", str(status))
            raise AgentCoreError()
        return self._iter_body(resp)

    def _iter_body(self, resp: HttpResponse) -> Iterator[str]:
        try:
            for raw in resp.lines:
                line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
                line = line.strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                text = _extract_text(line)
                if text:
                    yield text
        except (AgentCoreUnauthorized, AgentCoreError):
            raise
        except Exception as exc:
            self._log_failure("stream_failed", type(exc).__name__)
            raise AgentCoreError() from None
        finally:
            self._close(resp)

    @staticmethod
    def _close(resp: HttpResponse) -> None:
        if callable(resp.close):
            try:
                resp.close()
            except Exception:
                pass

    def _log_failure(self, event: str, detail: str) -> None:
        try:
            _logger.error(
                "agentcore_%s timestamp=%s detail=%s",
                event,
                self._clock.now().isoformat(),
                detail,
            )
        except Exception:
            pass
