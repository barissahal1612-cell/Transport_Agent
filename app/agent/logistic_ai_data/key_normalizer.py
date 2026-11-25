"""Anahtar normalizasyonu: yalnızca strip + upper.

Baştaki sıfırlar ve sondaki harfler korunur. Integral float değerlere '.0' eklenmez.
"""

from __future__ import annotations

import math


def to_key_string(value: object) -> str:
    """int/float/str değerini anahtar string'ine çevirir. None -> ''."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isfinite(value) and value == int(value):
            return str(int(value))
        return str(value)
    return str(value)


def normalize_key(value: object) -> str:
    """Anahtarı string'e çevirir, ardından yalnızca strip + upper uygular."""
    return to_key_string(value).strip().upper()
