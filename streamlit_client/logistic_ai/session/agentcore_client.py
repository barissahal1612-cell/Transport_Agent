"""AgentCore_Runtime HTTPS istemcisi (Bearer JWT; SigV4/boto3 kullanılmaz).

Req 13.5 - 13.8, 10.4.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol
from urllib.parse import quote

from logistic_ai_shared_auth.common.clock import Clock, SystemClock
from logistic_ai_shared_auth.common.errors import GENERIC_ERROR_MESSAGE

_logger = logging.getLogger("logistic_ai.agentcore_client")

REQUEST_TIMEOUT_S = 30.0
MIN_SESSION_ID_LENGTH = 33
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"


class AgentCoreUnauthorized(Exception):
    """Runtime 401/403 döndürdü; çağıran bir kez token yenilemeyi dener (Req 13.7)."""


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
    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> HttpResponse:
        """POST gönderir; ağ/zaman aşımı hatalarında istisna fırlatır."""
        ...


class RequestsTransport:
    """``requests`` tabanlı üretim taşıyıcısı."""

    def post(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> HttpResponse:
        import requests

        resp = requests.post(
            url, headers=dict(headers), data=body, timeout=timeout, stream=True
        )
        return HttpResponse(
            status_code=resp.status_code,
            lines=resp.iter_lines(decode_unicode=True),
            close=resp.close,
        )


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
        self._http: HttpTransport = http or RequestsTransport()
        self._clock = clock or SystemClock()

    @property
    def url(self) -> str:
        return (
            f"https://bedrock-agentcore.{self._region}.amazonaws.com/runtimes/"
            f"{quote(self._runtime_arn, safe='')}/invocations?qualifier=DEFAULT"
        )

    def invoke(
        self, access_token: str, prompt: str, actor_id: str, session_id: str
    ) -> Iterator[str]:
        """Yanıt metin parçalarını üretir. 401/403 → ``AgentCoreUnauthorized``."""
        url = self.url
        if not url.startswith("https://"):
            raise AgentCoreError()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            SESSION_HEADER: normalize_session_id(session_id),
        }
        body = json.dumps({"prompt": prompt, "actorId": actor_id}).encode("utf-8")

        try:
            resp = self._http.post(url, headers, body, REQUEST_TIMEOUT_S)
        except Exception as exc:  # ağ/zaman aşımı: ayrıntı yalnızca günlükte
            self._log_failure("request_failed", type(exc).__name__)
            raise AgentCoreError() from None

        return self._stream(resp)

    def _stream(self, resp: HttpResponse) -> Iterator[str]:
        # Durum denetimi, yineleyici tüketilmeden önce yapılsın diye burada.
        status = resp.status_code
        if status in (401, 403):
            self._close(resp)
            raise AgentCoreUnauthorized()
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
