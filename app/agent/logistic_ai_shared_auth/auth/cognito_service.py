"""Amazon Cognito tabanlı AuthService (USER_PASSWORD_AUTH, Req 2.1-2.7, 7.3, 8.7, 8.8)."""
from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .errors import AuthError, AuthErrorKind
from .lockout import LoginAttemptTracker
from .service import AuthResult, AuthService, TokenSet, validate_credentials

_logger = logging.getLogger(__name__)

# Toplam bekleme 5 saniyeyi aşmaz: bağlantı + okuma, tek deneme.
CONNECT_TIMEOUT_SECONDS = 2
READ_TIMEOUT_SECONDS = 3

_INVALID_CREDENTIAL_CODES = frozenset(
    {
        "NotAuthorizedException",
        "UserNotFoundException",
        "UserNotConfirmedException",
        "PasswordResetRequiredException",
    }
)
_LOCKED_CODES = frozenset({"TooManyRequestsException", "LimitExceededException"})


class CognitoAuthService(AuthService):
    def __init__(
        self,
        user_pool_id: str,
        app_client_id: str,
        region: str,
        endpoint_url: str | None = None,
        tracker: LoginAttemptTracker | None = None,
        client: Any | None = None,
    ) -> None:
        self._user_pool_id = user_pool_id
        self._app_client_id = app_client_id
        self._region = region
        self._tracker = tracker or LoginAttemptTracker()
        # Req 8.7/8.8: yalnızca https:// uç noktası; aksi hâlde veri göndermeden hata.
        self._endpoint_insecure = bool(
            endpoint_url and not endpoint_url.lower().startswith("https://")
        )
        self._client: Any | None = client
        if self._client is None and not self._endpoint_insecure:
            self._client = boto3.client(
                "cognito-idp",
                region_name=region,
                endpoint_url=endpoint_url or None,
                config=Config(
                    connect_timeout=CONNECT_TIMEOUT_SECONDS,
                    read_timeout=READ_TIMEOUT_SECONDS,
                    retries={"max_attempts": 1},
                ),
            )

    # ------------------------------------------------------------------ helpers
    def _require_client(self) -> Any:
        if self._endpoint_insecure or self._client is None:
            _logger.error("Cognito endpoint is not https; request refused")
            raise AuthError(AuthErrorKind.SERVICE_UNAVAILABLE)
        return self._client

    @staticmethod
    def _map_client_error(exc: ClientError) -> AuthError:
        error = exc.response.get("Error", {})
        code = error.get("Code", "")
        message = str(error.get("Message", ""))
        if code in _LOCKED_CODES or "Password attempts exceeded" in message:
            return AuthError(AuthErrorKind.LOCKED_OUT)
        if code in _INVALID_CREDENTIAL_CODES:
            return AuthError(AuthErrorKind.INVALID_CREDENTIALS)
        # Ayrıntı yalnızca günlükte; kullanıcıya genel mesaj.
        _logger.error("Cognito call failed: code=%s", code)
        return AuthError(AuthErrorKind.SERVICE_UNAVAILABLE)

    @staticmethod
    def _tokens_from(auth_result: dict[str, Any], fallback_refresh: str | None = None) -> TokenSet:
        return TokenSet(
            id_token=auth_result["IdToken"],
            access_token=auth_result["AccessToken"],
            refresh_token=auth_result.get("RefreshToken", fallback_refresh),
            expires_in=int(auth_result.get("ExpiresIn", 0)),
        )

    # --------------------------------------------------------------- AuthService
    def authenticate(self, username: str, password: str) -> AuthResult:
        invalid = validate_credentials(username, password)
        if invalid:
            raise AuthError(AuthErrorKind.INVALID_INPUT, invalid)
        if self._tracker.is_locked(username):
            raise AuthError(AuthErrorKind.LOCKED_OUT)
        client = self._require_client()
        try:
            response = client.initiate_auth(
                AuthFlow="USER_PASSWORD_AUTH",
                ClientId=self._app_client_id,
                AuthParameters={"USERNAME": username, "PASSWORD": password},
            )
        except ClientError as exc:
            err = self._map_client_error(exc)
            if err.kind in (AuthErrorKind.INVALID_CREDENTIALS, AuthErrorKind.LOCKED_OUT):
                self._tracker.record_failure(username)
            raise err from None
        except (BotoCoreError, OSError) as exc:
            _logger.error("Cognito unreachable: %s", type(exc).__name__)
            raise AuthError(AuthErrorKind.SERVICE_UNAVAILABLE) from None

        if response.get("ChallengeName"):
            # NEW_PASSWORD_REQUIRED dahil hiçbir challenge'da token iletilmez.
            if response["ChallengeName"] == "NEW_PASSWORD_REQUIRED":
                raise AuthError(AuthErrorKind.NEW_PASSWORD_REQUIRED)
            _logger.error("Unsupported Cognito challenge: %s", response["ChallengeName"])
            raise AuthError(AuthErrorKind.SERVICE_UNAVAILABLE)

        auth_result = response.get("AuthenticationResult")
        if not auth_result or "IdToken" not in auth_result or "AccessToken" not in auth_result:
            _logger.error("Cognito response missing AuthenticationResult")
            raise AuthError(AuthErrorKind.SERVICE_UNAVAILABLE)

        self._tracker.record_success(username)
        return AuthResult(username=username, tokens=self._tokens_from(auth_result))

    def refresh(self, refresh_token: str) -> TokenSet:
        if not isinstance(refresh_token, str) or not refresh_token:
            raise AuthError(AuthErrorKind.INVALID_CREDENTIALS)
        client = self._require_client()
        try:
            response = client.initiate_auth(
                AuthFlow="REFRESH_TOKEN_AUTH",
                ClientId=self._app_client_id,
                AuthParameters={"REFRESH_TOKEN": refresh_token},
            )
        except ClientError as exc:
            raise self._map_client_error(exc) from None
        except (BotoCoreError, OSError) as exc:
            _logger.error("Cognito unreachable: %s", type(exc).__name__)
            raise AuthError(AuthErrorKind.SERVICE_UNAVAILABLE) from None
        auth_result = response.get("AuthenticationResult")
        if not auth_result or "IdToken" not in auth_result or "AccessToken" not in auth_result:
            raise AuthError(AuthErrorKind.SERVICE_UNAVAILABLE)
        return self._tokens_from(auth_result, fallback_refresh=refresh_token)

    def revoke(self, refresh_token: str) -> None:
        if not isinstance(refresh_token, str) or not refresh_token:
            return
        client = self._require_client()
        try:
            client.revoke_token(Token=refresh_token, ClientId=self._app_client_id)
        except ClientError as exc:
            raise self._map_client_error(exc) from None
        except (BotoCoreError, OSError) as exc:
            _logger.error("Cognito unreachable: %s", type(exc).__name__)
            raise AuthError(AuthErrorKind.SERVICE_UNAVAILABLE) from None
