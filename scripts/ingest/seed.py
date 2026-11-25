"""Kullanıcı ve izin tohumlayıcısı (role_user, permissions -> users/permissions tabloları).

- Varsayılan dry-run: AWS çağrısı yok, şifre özetleme yok, yazma yok.
- Yeniden çalıştırma mevcut kayıtları ezmez (create-if-absent).
- Şifre hiçbir yerde yazdırılmaz/günlüğe düşmez; rapor yalnızca sayı ve (sheet, satır, tür) içerir.
"""
from __future__ import annotations

from typing import Any, Callable

from logistic_ai_data.key_normalizer import to_key_string
from logistic_ai_shared_auth.auth.passwords import PasswordHasher
from logistic_ai_shared_auth.auth.users import ROLES, UserRecord, UserRepository
from logistic_ai_shared_auth.authorization.permission_store import (
    PermissionRepository,
    resource_key,
    role_subject,
)
from logistic_ai_shared_auth.authorization.resources import RESOURCE_TYPES, is_known_resource

from .excel_reader import WorkbookData
from .report import IngestReport

USERS_SHEET = "role_user"
PERMS_SHEET = "permissions"
SEED_ACTOR = "seed"


def _text(value: Any) -> str:
    """Hücreyi string'e çevirir ('.0' eklemeden); boş/None -> ''."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value.strip()
    return to_key_string(value)


def _parse_allowed(value: Any) -> bool | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return {1: True, 0: False}.get(value) if value in (0, 1) else None
    if isinstance(value, str) and value.strip() in ("0", "1"):
        return value.strip() == "1"
    return None


def seed_users(
    rows: list[dict[str, Any]],
    report: IngestReport,
    repo: UserRepository | None,
    hasher: PasswordHasher | None,
    apply: bool,
) -> None:
    counts = report.counts(USERS_SHEET)
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    for idx, row in enumerate(rows, start=2):
        counts.read += 1
        role = _text(row.get("ROLE"))
        userid = _text(row.get("USERID"))
        username = _text(row.get("USERNAME"))
        password = row.get("Password")
        pw_text = _text(password)
        if role not in ROLES:
            report.skip(USERS_SHEET, idx, "invalid_role", "ROLE")
            continue
        if not userid:
            report.skip(USERS_SHEET, idx, "missing_value", "USERID")
            continue
        if not username:
            report.skip(USERS_SHEET, idx, "missing_value", "USERNAME")
            continue
        if not pw_text:
            report.skip(USERS_SHEET, idx, "missing_value", "Password")
            continue
        if username in seen_names:
            report.skip(USERS_SHEET, idx, "duplicate_username", "USERNAME")
            continue
        if userid in seen_ids:
            report.skip(USERS_SHEET, idx, "duplicate_userid", "USERID")
            continue
        seen_names.add(username)
        seen_ids.add(userid)
        if not apply:
            counts.loaded += 1  # yazılacak (dry-run: özetleme ve yazma yok)
            continue
        assert repo is not None and hasher is not None
        user = UserRecord(
            userid=userid,
            username=username,
            role=role,
            password_hash=hasher.hash(pw_text),
            active=True,
        )
        if repo.put_user(user):
            counts.loaded += 1
        else:
            report.skip(USERS_SHEET, idx, "already_exists", "USERNAME")


def seed_permissions(
    rows: list[dict[str, Any]],
    report: IngestReport,
    repo: PermissionRepository | None,
    apply: bool,
) -> None:
    counts = report.counts(PERMS_SHEET)
    seen: set[tuple[str, str]] = set()
    for idx, row in enumerate(rows, start=2):
        counts.read += 1
        role = _text(row.get("ROLE"))
        rtype = _text(row.get("RESOURCE_TYPE"))
        name = _text(row.get("RESOURCE_NAME"))
        if role not in ROLES:
            report.skip(PERMS_SHEET, idx, "invalid_role", "ROLE")
            continue
        if rtype not in RESOURCE_TYPES:
            report.skip(PERMS_SHEET, idx, "unknown_resource_type", "RESOURCE_TYPE")
            continue
        if not is_known_resource(rtype, name):
            report.skip(PERMS_SHEET, idx, "unknown_resource", "RESOURCE_NAME")
            continue
        allowed = _parse_allowed(row.get("ALLOWED"))
        if allowed is None:
            report.skip(PERMS_SHEET, idx, "invalid_allowed", "ALLOWED")
            continue
        key = (role_subject(role), resource_key(rtype, name))
        if key in seen:
            report.skip(PERMS_SHEET, idx, "duplicate_permission")
            continue
        seen.add(key)
        if not apply:
            counts.loaded += 1
            continue
        assert repo is not None
        if repo.put(key[0], key[1], allowed, SEED_ACTOR, create_only=True):
            counts.loaded += 1
        else:
            report.skip(PERMS_SHEET, idx, "already_exists")


def seed_workbook(
    wb: WorkbookData,
    *,
    apply: bool = False,
    user_repo: UserRepository | None = None,
    permission_repo: PermissionRepository | None = None,
    hasher: PasswordHasher | None = None,
    repo_factory: Callable[[], tuple[UserRepository, PermissionRepository]] | None = None,
) -> IngestReport:
    """Tohumlar. ``apply=False`` iken depo/hasher kullanılmaz. Depolar enjekte edilir;
    verilmezse ``repo_factory`` (yalnızca apply) ile kurulur."""
    report = IngestReport(applied=apply, load_id="seed")
    if apply:
        if user_repo is None or permission_repo is None:
            if repo_factory is None:
                raise ValueError("apply requires repositories or repo_factory")
            user_repo, permission_repo = repo_factory()
        hasher = hasher or PasswordHasher()
    seed_users(wb.auth_sheets.get(USERS_SHEET, []), report, user_repo, hasher, apply)
    seed_permissions(wb.auth_sheets.get(PERMS_SHEET, []), report, permission_repo, apply)
    return report


def dynamo_repositories() -> tuple[UserRepository, PermissionRepository]:
    """Tablo adları LOGISTIC_AI_USERS_TABLE / LOGISTIC_AI_PERMISSIONS_TABLE ortam değişkenlerinden."""
    from logistic_ai_shared_auth.auth.users import DynamoUserRepository
    from logistic_ai_shared_auth.authorization.permission_store import DynamoPermissionRepository

    return DynamoUserRepository(), DynamoPermissionRepository()
