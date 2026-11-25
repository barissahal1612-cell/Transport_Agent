"""AuthService soyut arayüzü, veri türleri ve girdi doğrulama."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

USERNAME_MAX_LENGTH = 64
PASSWORD_MAX_LENGTH = 128


@dataclass(frozen=True)
class TokenSet:
    id_token: str = field(repr=False)
    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    expires_in: int = 0


@dataclass(frozen=True)
class AuthResult:
    """Başarılı kimlik doğrulama sonucu."""

    username: str
    tokens: TokenSet


class AuthService(ABC):
    @abstractmethod
    def authenticate(self, username: str, password: str) -> AuthResult:
        """Başarısızlıkta AuthError fırlatır."""

    @abstractmethod
    def refresh(self, refresh_token: str) -> TokenSet: ...

    @abstractmethod
    def revoke(self, refresh_token: str) -> None: ...


def validate_credentials(username: str, password: str) -> tuple[str, ...]:
    """Geçersiz alan adlarını döndürür; boş demet geçerli demektir.

    Kullanıcı adı 1-64, şifre 1-128 karakter olmalıdır. Yalnızca boşluktan
    oluşan değerler boş sayılır.
    """
    invalid: list[str] = []
    if (
        not isinstance(username, str)
        or not username.strip()
        or len(username) > USERNAME_MAX_LENGTH
    ):
        invalid.append("username")
    if (
        not isinstance(password, str)
        or not password.strip()
        or len(password) > PASSWORD_MAX_LENGTH
    ):
        invalid.append("password")
    return tuple(invalid)
