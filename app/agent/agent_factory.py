"""Tembel Agent ve çalışma zamanı bağlantısı. İçe aktarmada hiçbir AWS erişimi yapılmaz."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RuntimeWiring:
    data_repo: Any
    user_repo: Any
    permission_repo: Any
    permission_service: Any


def build_runtime(
    *,
    data_repo: Any = None,
    user_repo: Any = None,
    permission_repo: Any = None,
    audit: Any = None,
) -> RuntimeWiring:
    """Depoları ve PermissionService'i kurar, ``tools.guard.set_runtime`` ile bağlar.

    Parametreler testlerde bellek içi uyarlayıcı enjekte etmek içindir; verilmezse DynamoDB
    uyarlayıcıları kullanılır (tablo adları ortam değişkenlerinden).
    """
    from logistic_ai_data.dynamo_repository import DynamoDataRepository
    from logistic_ai_shared_auth.authorization.permission_service import PermissionService
    from logistic_ai_shared_auth.authorization.permission_store import DynamoPermissionRepository
    from logistic_ai_shared_auth.auth.users import DynamoUserRepository
    from logistic_ai_shared_auth.common.audit import JsonAuditLogger
    from tools import guard

    data_repo = data_repo if data_repo is not None else DynamoDataRepository()
    user_repo = user_repo if user_repo is not None else DynamoUserRepository()
    permission_repo = permission_repo if permission_repo is not None else DynamoPermissionRepository()
    service = PermissionService(user_repo, permission_repo, audit if audit is not None else JsonAuditLogger())
    guard.set_runtime(data_repo, service)
    return RuntimeWiring(data_repo, user_repo, permission_repo, service)


def build_agent(model: Any = None, messages: list[dict[str, Any]] | None = None) -> Any:
    """Strands Agent oluşturur. ``model`` verilmezse Bedrock modeli yüklenir.

    ``messages``: yalnızca bu isteğe ait önceki konuşma (Strands Message listesi); kopyalanır.
    """
    from strands import Agent

    from model.load import load_model
    from prompts.system_prompt import get_system_prompt
    from tools.logistics_tools import ALL_TOOLS

    return Agent(
        model=model if model is not None else load_model(),
        system_prompt=get_system_prompt(),
        tools=list(ALL_TOOLS),
        messages=[dict(m) for m in messages] if messages else None,
        callback_handler=None,
    )
