"""Dependency container shared by the UI screens and the router."""
from __future__ import annotations

from dataclasses import dataclass

from logistic_ai_data import DataRepository
from logistic_ai_shared_auth.auth.user_auth_service import UserAuthService
from logistic_ai_shared_auth.authorization.admin_service import AdminService
from logistic_ai_shared_auth.authorization.permission_service import PermissionService
from logistic_ai_shared_auth.common.audit import AuditLogger

from logistic_ai.config.settings import Settings
from logistic_ai.session.agentcore_client import AgentCoreClient
from logistic_ai.session.manager import SessionManager
from logistic_ai.session.user_context import UserContextProvider


@dataclass(frozen=True)
class AppDeps:
    settings: Settings
    auth: UserAuthService
    session: SessionManager
    user_context: UserContextProvider
    agent_client: AgentCoreClient
    audit: AuditLogger
    data_repo: DataRepository
    permission_service: PermissionService
    admin_service: AdminService
