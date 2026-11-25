"""Argon2id şifre özeti. Düz metin şifre asla günlüğe yazılmaz veya saklanmaz."""
from __future__ import annotations

from argon2 import PasswordHasher as _Argon2Hasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class PasswordHasher:
    def __init__(self, hasher: _Argon2Hasher | None = None) -> None:
        # argon2-cffi varsayılanı Argon2id'dir.
        self._hasher = hasher or _Argon2Hasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """Eşleşme yoksa veya özet bozuksa False döner; asla istisna fırlatmaz."""
        try:
            return bool(self._hasher.verify(password_hash, password))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        except Exception:  # noqa: BLE001 - bozuk girdi hiçbir koşulda sızmamalı
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except Exception:  # noqa: BLE001
            return True
