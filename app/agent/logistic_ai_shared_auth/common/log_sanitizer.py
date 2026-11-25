"""Günlük çıktısındaki sırları maskeleyen logging filtresi."""

from __future__ import annotations

import logging
import re
from typing import Iterable

MASK = "***"

_JWT_RE = re.compile(r"\b[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*\b")
_KV_RE = re.compile(
    r"(?i)\b((?:password|passwd|token|access_token|id_token|refresh_token|secret|api[_-]?key)"
    r"\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")


def sanitize(text: str, known_secrets: Iterable[str] = ()) -> str:
    for secret in sorted({s for s in known_secrets if s}, key=len, reverse=True):
        text = text.replace(secret, MASK)
    text = _JWT_RE.sub(MASK, text)
    text = _BEARER_RE.sub(lambda m: m.group(1) + MASK, text)
    text = _KV_RE.sub(lambda m: m.group(1) + MASK, text)
    return text


class SanitizingFilter(logging.Filter):
    def __init__(self, known_secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._known_secrets: set[str] = {s for s in known_secrets if s}

    def add_secret(self, secret: str) -> None:
        if secret:
            self._known_secrets.add(secret)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = sanitize(message, self._known_secrets)
        record.args = None
        if record.exc_info:
            import traceback

            text = "".join(traceback.format_exception(*record.exc_info))
            record.exc_text = sanitize(text, self._known_secrets)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = sanitize(record.exc_text, self._known_secrets)
        return True
