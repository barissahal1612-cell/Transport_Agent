"""User records and repositories (``logistic-ai-users`` table).

Requirements: 2.5, 2.7, 2.9, 4.7, 8.4.

``Role`` in ``authorization/roles.py`` is intentionally left untouched; the
``ADMIN`` role lives here as a plain string constant.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

SUPPLIER = "SUPPLIER"
MATERIAL_RESPONSIBLE = "MATERIAL_RESPONSIBLE"
TRANSPORT_OFFICE = "TRANSPORT_OFFICE"
ADMIN = "ADMIN"
ROLES: tuple[str, ...] = (SUPPLIER, MATERIAL_RESPONSIBLE, TRANSPORT_OFFICE, ADMIN)

USERS_TABLE_ENV = "LOGISTIC_AI_USERS_TABLE"
DEFAULT_USERS_TABLE = "logistic-ai-users"
USERID_INDEX = "userid-index"


@dataclass(frozen=True)
class UserRecord:
    userid: str
    username: str
    role: str
    password_hash: str = field(repr=False)
    active: bool = True
    failed_count: int = 0
    locked_until: float | None = None

    def __repr__(self) -> str:  # never expose password_hash
        return (
            f"UserRecord(userid={self.userid!r}, username={self.username!r}, "
            f"role={self.role!r}, active={self.active!r}, "
            f"failed_count={self.failed_count!r}, locked_until={self.locked_until!r})"
        )

    __str__ = __repr__


@runtime_checkable
class UserRepository(Protocol):
    def get_by_username(self, username: str) -> UserRecord | None: ...

    def get_by_userid(self, userid: str) -> UserRecord | None: ...

    def put_user(self, user: UserRecord) -> bool:
        """Create only if the username is absent. Returns True if created."""
        ...

    def set_active(self, username: str, active: bool) -> bool:
        """Returns False if the user does not exist."""
        ...

    def record_failure(
        self, username: str, now: float, max_failures: int, lock_seconds: float
    ) -> UserRecord:
        """Atomically increment the failure counter; lock once it reaches
        ``max_failures``. Raises ``KeyError`` for unknown users."""
        ...

    def reset_failures(self, username: str) -> None: ...

    def list_users(self) -> list[UserRecord]: ...

    def count_active_admins(self) -> int: ...


class InMemoryUserRepository:
    def __init__(self, users: list[UserRecord] | None = None) -> None:
        self._users: dict[str, UserRecord] = {}
        self._lock = threading.Lock()
        for user in users or []:
            self.put_user(user)

    def get_by_username(self, username: str) -> UserRecord | None:
        with self._lock:
            return self._users.get(username)

    def get_by_userid(self, userid: str) -> UserRecord | None:
        with self._lock:
            for user in self._users.values():
                if user.userid == userid:
                    return user
        return None

    def put_user(self, user: UserRecord) -> bool:
        with self._lock:
            if user.username in self._users:
                return False
            self._users[user.username] = user
            return True

    def set_active(self, username: str, active: bool) -> bool:
        with self._lock:
            user = self._users.get(username)
            if user is None:
                return False
            self._users[username] = replace(user, active=active)
            return True

    def record_failure(
        self, username: str, now: float, max_failures: int, lock_seconds: float
    ) -> UserRecord:
        with self._lock:
            user = self._users[username]
            count = user.failed_count + 1
            locked = now + lock_seconds if count >= max_failures else user.locked_until
            updated = replace(user, failed_count=count, locked_until=locked)
            self._users[username] = updated
            return updated

    def reset_failures(self, username: str) -> None:
        with self._lock:
            user = self._users.get(username)
            if user is not None:
                self._users[username] = replace(user, failed_count=0, locked_until=None)

    def list_users(self) -> list[UserRecord]:
        with self._lock:
            return list(self._users.values())

    def count_active_admins(self) -> int:
        with self._lock:
            return sum(1 for u in self._users.values() if u.role == ADMIN and u.active)


def _to_item(user: UserRecord) -> dict[str, Any]:
    item: dict[str, Any] = {
        "USERNAME": user.username,
        "USERID": user.userid,
        "ROLE": user.role,
        "password_hash": user.password_hash,
        "active": user.active,
        "failed_count": user.failed_count,
    }
    if user.locked_until is not None:
        item["locked_until"] = Decimal(str(user.locked_until))
    return item


def _from_item(item: dict[str, Any]) -> UserRecord:
    locked = item.get("locked_until")
    return UserRecord(
        userid=str(item["USERID"]),
        username=str(item["USERNAME"]),
        role=str(item["ROLE"]),
        password_hash=str(item.get("password_hash", "")),
        active=bool(item.get("active", True)),
        failed_count=int(item.get("failed_count", 0)),
        locked_until=float(locked) if locked is not None else None,
    )


class DynamoUserRepository:
    """DynamoDB adapter. ``table`` is injectable (boto3 Table resource or a
    compatible fake); no AWS call happens unless a real table is used."""

    def __init__(self, table: Any | None = None, table_name: str | None = None) -> None:
        if table is None:
            import boto3  # lazy: keeps cold start and tests light

            name = table_name or os.environ.get(USERS_TABLE_ENV, DEFAULT_USERS_TABLE)
            table = boto3.resource("dynamodb").Table(name)
        self._table = table

    def get_by_username(self, username: str) -> UserRecord | None:
        resp = self._table.get_item(Key={"USERNAME": username}, ConsistentRead=True)
        item = resp.get("Item")
        return _from_item(item) if item else None

    def get_by_userid(self, userid: str) -> UserRecord | None:
        resp = self._table.query(
            IndexName=USERID_INDEX,
            KeyConditionExpression="USERID = :u",
            ExpressionAttributeValues={":u": userid},
        )
        items = resp.get("Items", [])
        return _from_item(items[0]) if items else None

    def put_user(self, user: UserRecord) -> bool:
        try:
            self._table.put_item(
                Item=_to_item(user),
                ConditionExpression="attribute_not_exists(USERNAME)",
            )
            return True
        except Exception as exc:
            if _is_conditional_failure(exc):
                return False
            raise

    def set_active(self, username: str, active: bool) -> bool:
        try:
            self._table.update_item(
                Key={"USERNAME": username},
                UpdateExpression="SET active = :a",
                ConditionExpression="attribute_exists(USERNAME)",
                ExpressionAttributeValues={":a": active},
            )
            return True
        except Exception as exc:
            if _is_conditional_failure(exc):
                return False
            raise

    def record_failure(
        self, username: str, now: float, max_failures: int, lock_seconds: float
    ) -> UserRecord:
        try:
            resp = self._table.update_item(
                Key={"USERNAME": username},
                UpdateExpression="ADD failed_count :one",
                ConditionExpression="attribute_exists(USERNAME)",
                ExpressionAttributeValues={":one": 1},
                ReturnValues="ALL_NEW",
            )
        except Exception as exc:
            if _is_conditional_failure(exc):
                raise KeyError(username) from exc
            raise
        user = _from_item(resp["Attributes"])
        if user.failed_count >= max_failures:
            locked_until = now + lock_seconds
            self._table.update_item(
                Key={"USERNAME": username},
                UpdateExpression="SET locked_until = :l",
                ExpressionAttributeValues={":l": Decimal(str(locked_until))},
            )
            user = replace(user, locked_until=locked_until)
        return user

    def reset_failures(self, username: str) -> None:
        try:
            self._table.update_item(
                Key={"USERNAME": username},
                UpdateExpression="SET failed_count = :z REMOVE locked_until",
                ConditionExpression="attribute_exists(USERNAME)",
                ExpressionAttributeValues={":z": 0},
            )
        except Exception as exc:
            if not _is_conditional_failure(exc):
                raise

    def _scan(self, **kwargs: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while True:
            resp = self._table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            key = resp.get("LastEvaluatedKey")
            if not key:
                return items
            kwargs["ExclusiveStartKey"] = key

    def list_users(self) -> list[UserRecord]:
        return [_from_item(i) for i in self._scan()]

    def count_active_admins(self) -> int:
        items = self._scan(
            FilterExpression="ROLE = :r AND active = :t",
            ExpressionAttributeValues={":r": ADMIN, ":t": True},
        )
        return len(items)


def _is_conditional_failure(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
    return False
