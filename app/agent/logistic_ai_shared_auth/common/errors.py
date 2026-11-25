"""Ortak istisna türleri ve kullanıcıya gösterilecek güvenli hata mesajı."""

from __future__ import annotations

import logging

from .clock import Clock, SystemClock

GENERIC_ERROR_MESSAGE = "Beklenmeyen bir hata oluştu. Lütfen daha sonra tekrar deneyin."

_logger = logging.getLogger("logistic_ai.errors")


class LogisticAIError(Exception):
    """Paketin ortak taban istisnası."""


class ConfigError(LogisticAIError):
    """Yapılandırma hatası."""


def safe_error_message(
    exc: BaseException,
    *,
    clock: Clock | None = None,
    logger: logging.Logger | None = None,
) -> str:
    """Sabit genel mesajı döndürür; ayrıntıyı zaman damgasıyla günlüğe yazar."""
    ts = (clock or SystemClock()).now().isoformat()
    try:
        (logger or _logger).error(
            "unexpected_error timestamp=%s type=%s detail=%s",
            ts,
            type(exc).__name__,
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    except Exception:  # günlükleme hatası kullanıcı mesajını etkilemez
        pass
    return GENERIC_ERROR_MESSAGE
