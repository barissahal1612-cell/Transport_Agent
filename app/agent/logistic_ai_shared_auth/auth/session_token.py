"""HS256 Session_Token üretimi ve doğrulaması (PyJWT)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable

import jwt

from ..common.clock import Clock, SystemClock

SESSION_TTL_SECONDS = 30 * 60
ALGORITHM = "HS256"
DEFAULT_SECRET_ENV = "LOGISTIC_AI_SESSION_SECRET"
_MIN_SECRET_LEN = 16


class SessionTokenError(Exception):
    """Geçersiz, süresi dolmuş veya bozuk belirteç için genel hata."""

    def __init__(self, message: str = "Oturum geçersiz.") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class VerifiedSession:
    userid: str
    username: str
    role: str
    exp: int


@runtime_checkable
class SecretProvider(Protocol):
    def get_secret(self) -> str: ...


class EnvSecretProvider:
    def __init__(self, env_var: str = DEFAULT_SECRET_ENV, environ: Mapping[str, str] | None = None) -> None:
        self._env_var = env_var
        self._environ = environ if environ is not None else os.environ

    def get_secret(self) -> str:
        value = self._environ.get(self._env_var, "")
        if not value:
            raise SessionTokenError("Oturum anahtarı yapılandırılmamış.")
        return value


class SecretsManagerSecretProvider:
    """Secrets Manager'dan okur; boto3 tembel içe aktarılır, sonuç önbelleğe alınır.

    Gizli değer düz metin veya JSON olabilir; JSON ise `json_key` alanı kullanılır.
    """

    def __init__(self, secret_id: str, *, json_key: str = "secret", client=None, region_name: str | None = None) -> None:
        self._secret_id = secret_id
        self._json_key = json_key
        self._client = client
        self._region = region_name
        self._cached: str | None = None

    def get_secret(self) -> str:
        if self._cached is not None:
            return self._cached
        try:
            if self._client is None:
                import boto3  # tembel içe aktarma

                self._client = boto3.client("secretsmanager", region_name=self._region)
            raw = self._client.get_secret_value(SecretId=self._secret_id)["SecretString"]
            value = raw
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    value = parsed[self._json_key]
            except (ValueError, KeyError):
                pass
            if not isinstance(value, str) or not value:
                raise ValueError("empty secret")
        except Exception as exc:  # noqa: BLE001
            raise SessionTokenError("Oturum anahtarı okunamadı.") from exc
        self._cached = value
        return value


class SessionTokenService:
    def __init__(
        self,
        secret_provider: SecretProvider,
        clock: Clock | None = None,
        ttl_seconds: int = SESSION_TTL_SECONDS,
    ) -> None:
        self._secrets = secret_provider
        self._clock = clock or SystemClock()
        self._ttl = ttl_seconds

    def _key(self) -> str:
        key = self._secrets.get_secret()
        if not isinstance(key, str) or len(key) < _MIN_SECRET_LEN:
            raise SessionTokenError("Oturum anahtarı geçersiz.")
        return key

    def issue(self, userid: str, username: str, role: str) -> str:
        iat = int(self._clock.timestamp())
        claims = {"uid": str(userid), "usr": username, "role": role, "iat": iat, "exp": iat + self._ttl}
        return jwt.encode(claims, self._key(), algorithm=ALGORITHM)

    def verify(self, token: str) -> VerifiedSession:
        try:
            if not isinstance(token, str) or not token:
                raise SessionTokenError()
            # Algoritma beyaz listesi: none ve diğerleri reddedilir.
            header = jwt.get_unverified_header(token)
            if header.get("alg") != ALGORITHM:
                raise SessionTokenError()
            claims = jwt.decode(
                token,
                self._key(),
                algorithms=[ALGORITHM],
                options={"verify_exp": False, "verify_iat": False, "require": ["uid", "usr", "role", "iat", "exp"]},
            )
            exp, iat = claims["exp"], claims["iat"]
            if isinstance(exp, bool) or isinstance(iat, bool) or not isinstance(exp, (int, float)) or not isinstance(iat, (int, float)):
                raise SessionTokenError()
            if self._clock.timestamp() >= exp:
                raise SessionTokenError()
            uid, usr, role = claims["uid"], claims["usr"], claims["role"]
            if not all(isinstance(v, str) and v for v in (uid, usr, role)):
                raise SessionTokenError()
            return VerifiedSession(userid=uid, username=usr, role=role, exp=int(exp))
        except SessionTokenError:
            raise
        except Exception as exc:  # noqa: BLE001 - tüm hatalar tek genel hataya iner
            raise SessionTokenError() from exc
