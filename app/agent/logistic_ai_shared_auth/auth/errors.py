"""Kimlik doğrulama hata türleri ve sabit, genel kullanıcı mesajları."""

from __future__ import annotations

from enum import Enum


class AuthErrorKind(Enum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    NEW_PASSWORD_REQUIRED = "NEW_PASSWORD_REQUIRED"
    LOCKED_OUT = "LOCKED_OUT"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


# Her tür için sabit, genel Türkçe mesaj (teknik ayrıntı veya hesap bilgisi içermez).
USER_MESSAGES: dict[AuthErrorKind, str] = {
    AuthErrorKind.INVALID_INPUT: "Kullanıcı adı ve şifre geçerli olmalıdır",
    AuthErrorKind.INVALID_CREDENTIALS: "Geçersiz kullanıcı adı veya şifre",
    AuthErrorKind.NEW_PASSWORD_REQUIRED: "Devam etmek için şifrenizi değiştirmeniz gerekiyor",
    AuthErrorKind.LOCKED_OUT: "Çok fazla deneme, lütfen daha sonra tekrar deneyin",
    AuthErrorKind.SERVICE_UNAVAILABLE: "Hizmete şu anda ulaşılamıyor, lütfen daha sonra tekrar deneyin",
}


class AuthError(Exception):
    """Kimlik doğrulama hatası; `user_message` her tür için sabittir."""

    kind: AuthErrorKind
    user_message: str
    invalid_fields: tuple[str, ...]

    def __init__(
        self,
        kind: AuthErrorKind,
        invalid_fields: tuple[str, ...] = (),
    ) -> None:
        self.kind = kind
        self.user_message = USER_MESSAGES[kind]
        # Yalnızca INVALID_INPUT için anlamlıdır.
        self.invalid_fields = (
            tuple(invalid_fields) if kind is AuthErrorKind.INVALID_INPUT else ()
        )
        super().__init__(self.user_message)
