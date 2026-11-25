"""Single user-context interface for future AI components (Req 9.5, 9.6).

The role comes only from the verified identity held by ``SessionManager``;
nothing a client can modify is consulted.
"""
from __future__ import annotations

from dataclasses import dataclass

from logistic_ai_shared_auth.authorization.roles import Role

from logistic_ai.session.manager import SessionInvalid, SessionManager

NOT_AUTHENTICATED_MESSAGE = "Kimlik doğrulaması gerekli"


class NotAuthenticated(Exception):
    """No valid session. Carries no username or role information."""

    def __init__(self) -> None:
        self.user_message = NOT_AUTHENTICATED_MESSAGE
        super().__init__(NOT_AUTHENTICATED_MESSAGE)


@dataclass(frozen=True)
class UserContext:
    username: str
    role: Role


class UserContextProvider:
    def __init__(self, session: SessionManager) -> None:
        self._session = session

    def current(self) -> UserContext:
        """Return the context of the valid session, else raise ``NotAuthenticated``."""
        try:
            view = self._session.require_valid_session()
        except SessionInvalid:
            raise NotAuthenticated() from None
        return UserContext(username=view.username, role=view.role)
