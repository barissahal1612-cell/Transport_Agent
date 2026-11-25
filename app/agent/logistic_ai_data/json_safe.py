"""Güvenli JSON ayrıştırma: hiçbir girdi için istisna fırlatmaz."""

from __future__ import annotations

import json

ERR_EMPTY = "empty"
ERR_INVALID_JSON = "invalid_json"
ERR_NOT_CONTAINER = "not_dict_or_list"
ERR_UNSUPPORTED_TYPE = "unsupported_type"
ERR_DECODE = "decode_error"


def safe_json_loads(raw: object) -> tuple[dict | list | None, str | None]:
    """(değer, None) veya (None, hata_türü) döner; istisna fırlatmaz.

    Yalnızca dict/list sonuçları geçerlidir. Zaten dict/list olan girdi aynen döner.
    """
    try:
        if isinstance(raw, (dict, list)):
            return raw, None
        if raw is None:
            return None, ERR_EMPTY
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = bytes(raw).decode("utf-8")
            except UnicodeDecodeError:
                return None, ERR_DECODE
        if not isinstance(raw, str):
            return None, ERR_UNSUPPORTED_TYPE
        if not raw.strip():
            return None, ERR_EMPTY
        try:
            parsed = json.loads(raw)
        except (ValueError, RecursionError):
            return None, ERR_INVALID_JSON
        if not isinstance(parsed, (dict, list)):
            return None, ERR_NOT_CONTAINER
        return parsed, None
    except Exception:  # noqa: BLE001 - sözleşme: asla istisna fırlatma
        return None, ERR_INVALID_JSON
