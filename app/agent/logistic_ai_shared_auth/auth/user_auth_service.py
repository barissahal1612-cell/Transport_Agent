"""Kullanıcı adı/şifre tabanlı kimlik doğrulama (Argon2id + Session_Token).

Req 2.5-2.7, 2.9, 2.11. Bilinmeyen kullanıcı, hatalı şifre, pasif ve kilitli hesap
aynı genel INVALID_CREDENTIALS hatasını döner; kilit/pasiflik bilgisi sızdırılmaz.
Kullanıcı adı büyük/küçük harf duyarlıdır. Şifre ve özetler günlüğe yazılmaz.
"""
from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from ..common.audit import AuditLogger
from ..common.clock import Clock, SystemClock
from .errors import AuthError, AuthErrorKind
from .passwords import PasswordHasher
from .service import validate_credentials
from .session_token import SessionTokenService
from .users import UserRepository

MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthenticatedSession:
    token: str
    userid: str
    username: str
    role: str

    def __repr__(self) -> str:  # belirteç günlüğe sızmasın
        return (
            f"AuthenticatedSession(userid={self.userid!r}, "
            f"username={self.username!r}, role={self.role!r})"
        )

    __str__ = __repr__


class UserAuthService:
    def __init__(
        self,
        users: UserRepository,
        hasher: PasswordHasher,
        tokens: SessionTokenService,
        audit: AuditLogger,
        clock: Clock | None = None,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._tokens = tokens
        self._audit = audit
        self._clock = clock or SystemClock()
        self._dummy_hash: str | None = None

    # ------------------------------------------------------------------ helpers
    def _dummy_verify(self, password: str) -> None:
        """Kullanıcı kaydı yokken/kullanılamazken zamanlama farkını azaltır."""
        if self._dummy_hash is None:
            self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(16))
        self._hasher.verify(self._dummy_hash, password)

    def _safe_audit(self, fn_name: str, *args: object) -> None:
        try:
            getattr(self._audit, fn_name)(*args)
        except Exception:  # noqa: BLE001 - denetim hatası girişi bozmamalı
            _logger.error("audit_call_failed fn=%s", fn_name)

    def _fail(self, username: str) -> AuthError:
        self._safe_audit("log_login", username, False)
        return AuthError(AuthErrorKind.INVALID_CREDENTIALS)

    # --------------------------------------------------------------------- API
    def authenticate(self, username: str, password: str) -> AuthenticatedSession:
        invalid = validate_credentials(username, password)
        if invalid:
            raise AuthError(AuthErrorKind.INVALID_INPUT, invalid)

        now = self._clock.timestamp()
        user = self._users.get_by_username(username)  # büyük/küçük harf duyarlı

        if user is None:
            self._dummy_verify(password)
            raise self._fail(username)

        if user.locked_until is not None and user.locked_until > now:
            self._dummy_verify(password)
            raise self._fail(username)

        if not user.active:
            self._dummy_verify(password)
            raise self._fail(username)

        if user.locked_until is not None:
            # Kilit süresi dolmuş: sayaç sıfırlanır, yeni 5 deneme hakkı başlar.
            self._users.reset_failures(user.username)

        if not self._hasher.verify(user.password_hash, password):
            try:
                updated = self._users.record_failure(
                    user.username, now, MAX_FAILURES, LOCK_SECONDS
                )
            except KeyError:
                updated = None
            if updated is not None and updated.locked_until is not None and updated.locked_until > now:
                # Kilitlenme olayı: ayrı yöntem varsa kullan, yoksa yalnızca başarısız giriş.
                if hasattr(self._audit, "log_lockout"):
                    self._safe_audit("log_lockout", user.username)
            raise self._fail(username)

        self._users.reset_failures(user.username)
        token = self._tokens.issue(user.userid, user.username, user.role)
        self._safe_audit("log_login", user.username, True)
        return AuthenticatedSession(
            token=token, userid=user.userid, username=user.username, role=user.role
        )

    def logout(self, userid: str, username: str) -> None:
        """Yalnızca denetim kaydı yazar; belirteç sunucuda saklanmaz (Req 2.11)."""
        self._safe_audit("log_logout", username)
