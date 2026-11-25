"""Test için programlanabilir AuthService uygulaması (ağ çağrısı yapmaz)."""

from __future__ import annotations

from collections import deque

from .service import AuthResult, AuthService, TokenSet

# Bir sonuç: dönecek değer, fırlatılacak istisna veya çağrı bağımsız değişkenlerinden
# sonuç üreten çağrılabilir.
Outcome = object


class MockAuthService(AuthService):
    """Programlanabilir sonuçlar ve çağrı sayacı sunar.

    Her metot için `program_*` ile sıraya sonuç eklenir; sıra boşalınca varsayılan
    sonuç kullanılır. Sonuç bir `Exception` ise fırlatılır, çağrılabilirse
    bağımsız değişkenlerle çağrılır, aksi hâlde olduğu gibi döndürülür.
    Hiçbir kimlik bilgisi doğrulaması yapılmaz ve hiçbir ağ çağrısı yapılmaz.
    """

    def __init__(
        self,
        default_authenticate: Outcome | None = None,
        default_refresh: Outcome | None = None,
        default_revoke: Outcome | None = None,
    ) -> None:
        self._defaults: dict[str, Outcome | None] = {
            "authenticate": default_authenticate,
            "refresh": default_refresh,
            "revoke": default_revoke,
        }
        self._queues: dict[str, deque[Outcome]] = {
            "authenticate": deque(),
            "refresh": deque(),
            "revoke": deque(),
        }
        self.authenticate_calls = 0
        self.refresh_calls = 0
        self.revoke_calls = 0
        self.authenticate_args: list[tuple[str, str]] = []
        self.refresh_args: list[str] = []
        self.revoke_args: list[str] = []

    # -- programlama -------------------------------------------------------
    def program_authenticate(self, *outcomes: Outcome) -> None:
        self._queues["authenticate"].extend(outcomes)

    def program_refresh(self, *outcomes: Outcome) -> None:
        self._queues["refresh"].extend(outcomes)

    def program_revoke(self, *outcomes: Outcome) -> None:
        self._queues["revoke"].extend(outcomes)

    @property
    def total_calls(self) -> int:
        return self.authenticate_calls + self.refresh_calls + self.revoke_calls

    # -- AuthService -------------------------------------------------------
    def authenticate(self, username: str, password: str) -> AuthResult:
        self.authenticate_calls += 1
        self.authenticate_args.append((username, password))
        outcome = self._next("authenticate")
        if outcome is None:
            outcome = AuthResult(
                username=username,
                tokens=TokenSet(
                    id_token="mock-id-token",
                    access_token="mock-access-token",
                    refresh_token="mock-refresh-token",
                    expires_in=3600,
                ),
            )
        return self._resolve(outcome, username, password)  # type: ignore[return-value]

    def refresh(self, refresh_token: str) -> TokenSet:
        self.refresh_calls += 1
        self.refresh_args.append(refresh_token)
        outcome = self._next("refresh")
        if outcome is None:
            outcome = TokenSet(
                id_token="mock-id-token",
                access_token="mock-access-token",
                refresh_token=refresh_token,
                expires_in=3600,
            )
        return self._resolve(outcome, refresh_token)  # type: ignore[return-value]

    def revoke(self, refresh_token: str) -> None:
        self.revoke_calls += 1
        self.revoke_args.append(refresh_token)
        outcome = self._next("revoke")
        if outcome is not None:
            self._resolve(outcome, refresh_token)

    # -- yardımcılar -------------------------------------------------------
    def _next(self, method: str) -> Outcome | None:
        queue = self._queues[method]
        if queue:
            return queue.popleft()
        return self._defaults[method]

    @staticmethod
    def _resolve(outcome: Outcome, *args: str) -> object:
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, type) and issubclass(outcome, BaseException):
            raise outcome()
        if callable(outcome):
            result = outcome(*args)  # type: ignore[operator]
            return result
        return outcome


__all__ = ["MockAuthService"]
