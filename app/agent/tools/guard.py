"""Tool koruması: kimlik, Key_ID doğrulama, izin kontrolü ve kontrollü hata yanıtları.

Kimlik YALNIZCA ``tool_context.invocation_state["userid"]`` içinden okunur (main.py, Session_Token
doğrulandıktan sonra doldurur); LLM parametrelerinden asla alınmaz. Bağımlılıklar modül düzeyindeki
``ToolRuntime`` üzerinden enjekte edilir; içe aktarma sırasında AWS erişimi yoktur.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from logistic_ai_shared_auth.authorization.authorizer import PermissionDenied

_logger = logging.getLogger("logistic_ai.tools")

FORBIDDEN_MESSAGE = "Bu işlem için yetkiniz yok"
NOT_FOUND_MESSAGE = "Kayıt bulunamadı"
ERROR_MESSAGE = "Veri okunamadı"


@dataclass
class ToolRuntime:
    data_repo: Any = None
    permission_service: Any = None


_runtime = ToolRuntime()


def set_runtime(data_repo: Any, permission_service: Any) -> None:
    _runtime.data_repo = data_repo
    _runtime.permission_service = permission_service


def get_runtime() -> ToolRuntime:
    return _runtime


def _forbidden() -> dict:
    return {"status": "forbidden", "message": FORBIDDEN_MESSAGE}


def _error() -> dict:
    return {"status": "error", "message": ERROR_MESSAGE}


def _userid(tool_context: Any) -> str:
    try:
        state = getattr(tool_context, "invocation_state", None) or {}
        value = state.get("userid")
    except Exception:  # noqa: BLE001
        return ""
    return str(value).strip() if value is not None else ""


def json_safe(value: Any) -> Any:
    """Decimal -> int/float (özyinelemeli); yanıt JSON uyumlu olur."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def guarded_call(
    *,
    function_name: str,
    table: str,
    tool_context: Any,
    fetch: Callable[[Any], list[dict]],
    shape: Callable[[list[dict]], list[dict]],
    key_param: str | None = None,
    key_value: object = None,
) -> dict:
    """Ortak Tool akışı. Asla istisna fırlatmaz.

    Sıra: Key_ID doğrulama -> izin (FUNCTION + TABLE) -> veri okuma -> biçimlendirme.
    ``fetch(repo)`` ham satırları döner; ``shape(rows)`` çıktı satırlarını üretir.
    """
    try:
        if key_param is not None and (key_value is None or not str(key_value).strip()):
            return {
                "status": "missing_parameter",
                "parameter": key_param,
                "message": f"'{key_param}' bilgisi gerekli. Lütfen kullanıcıdan bu bilgiyi isteyin.",
            }
        userid = _userid(tool_context)
        if not userid:
            return _forbidden()
        runtime = _runtime
        if runtime.permission_service is None or runtime.data_repo is None:
            _logger.error("tool runtime not configured")
            return _error()
        try:
            runtime.permission_service.require_tool(userid, function_name, [table])
        except PermissionDenied:
            return _forbidden()
        raw = fetch(runtime.data_repo)
        if not raw:
            return {
                "status": "not_found",
                "key": str(key_value).strip() if key_param is not None else None,
                "message": NOT_FOUND_MESSAGE,
            }
        rows = json_safe(shape(list(raw)))
        return {"status": "ok", "rows": rows, "count": len(rows)}
    except Exception as exc:  # noqa: BLE001 - yalnızca tür günlüğe yazılır
        _logger.error("tool failed: %s (%s)", function_name, type(exc).__name__)
        return _error()
