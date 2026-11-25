"""Permission records (``logistic-ai-permissions`` table).

PK ``SUBJECT`` = ``ROLE#<role>`` | ``USER#<userid>``;
SK ``RESOURCE`` = ``TABLE#<name>`` | ``FUNCTION#<name>``;
attributes ``allowed`` (BOOL), ``updated_by``, ``updated_at``.

Requirements: 3.1, 3.4, 3.5, 3.9.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

PERMISSIONS_TABLE_ENV = "LOGISTIC_AI_PERMISSIONS_TABLE"
DEFAULT_PERMISSIONS_TABLE = "logistic-ai-permissions"


def role_subject(role: str) -> str:
    return f"ROLE#{role}"


def user_subject(userid: str) -> str:
    return f"USER#{userid}"


def resource_key(resource_type: str, resource: str) -> str:
    return f"{resource_type}#{resource}"


@dataclass(frozen=True)
class PermissionEntry:
    subject: str
    resource: str
    allowed: bool
    updated_by: str = ""
    updated_at: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@runtime_checkable
class PermissionRepository(Protocol):
    def get(self, subject: str, resource: str) -> bool | None:
        """``allowed`` value of the record, or None if there is no record."""
        ...

    def put(
        self,
        subject: str,
        resource: str,
        allowed: bool,
        updated_by: str,
        updated_at: str | None = None,
        create_only: bool = False,
    ) -> bool:
        """Upsert. With ``create_only`` an existing record is kept and False is
        returned. Returns True if written."""
        ...

    def delete(self, subject: str, resource: str) -> bool:
        """Returns True if a record existed."""
        ...

    def list_for_subject(self, subject: str) -> list[PermissionEntry]: ...


class InMemoryPermissionRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], PermissionEntry] = {}
        self._lock = threading.Lock()

    def get(self, subject: str, resource: str) -> bool | None:
        with self._lock:
            entry = self._items.get((subject, resource))
        return None if entry is None else entry.allowed

    def put(
        self,
        subject: str,
        resource: str,
        allowed: bool,
        updated_by: str,
        updated_at: str | None = None,
        create_only: bool = False,
    ) -> bool:
        with self._lock:
            if create_only and (subject, resource) in self._items:
                return False
            self._items[(subject, resource)] = PermissionEntry(
                subject, resource, bool(allowed), updated_by, updated_at or _now_iso()
            )
            return True

    def delete(self, subject: str, resource: str) -> bool:
        with self._lock:
            return self._items.pop((subject, resource), None) is not None

    def list_for_subject(self, subject: str) -> list[PermissionEntry]:
        with self._lock:
            return sorted(
                (e for (s, _), e in self._items.items() if s == subject),
                key=lambda e: e.resource,
            )


def _is_conditional_failure(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
    return False


class DynamoPermissionRepository:
    """DynamoDB adapter. ``table`` is injectable; no AWS call is made unless a
    real table is used."""

    def __init__(self, table: Any | None = None, table_name: str | None = None) -> None:
        if table is None:
            import boto3  # lazy

            name = table_name or os.environ.get(
                PERMISSIONS_TABLE_ENV, DEFAULT_PERMISSIONS_TABLE
            )
            table = boto3.resource("dynamodb").Table(name)
        self._table = table

    def get(self, subject: str, resource: str) -> bool | None:
        resp = self._table.get_item(
            Key={"SUBJECT": subject, "RESOURCE": resource}, ConsistentRead=True
        )
        item = resp.get("Item")
        return None if not item else bool(item.get("allowed", False))

    def put(
        self,
        subject: str,
        resource: str,
        allowed: bool,
        updated_by: str,
        updated_at: str | None = None,
        create_only: bool = False,
    ) -> bool:
        kwargs: dict[str, Any] = {
            "Item": {
                "SUBJECT": subject,
                "RESOURCE": resource,
                "allowed": bool(allowed),
                "updated_by": updated_by,
                "updated_at": updated_at or _now_iso(),
            }
        }
        if create_only:
            kwargs["ConditionExpression"] = "attribute_not_exists(SUBJECT)"
        try:
            self._table.put_item(**kwargs)
            return True
        except Exception as exc:
            if create_only and _is_conditional_failure(exc):
                return False
            raise

    def delete(self, subject: str, resource: str) -> bool:
        resp = self._table.delete_item(
            Key={"SUBJECT": subject, "RESOURCE": resource}, ReturnValues="ALL_OLD"
        )
        return bool(resp.get("Attributes"))

    def list_for_subject(self, subject: str) -> list[PermissionEntry]:
        entries: list[PermissionEntry] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "SUBJECT = :s",
            "ExpressionAttributeValues": {":s": subject},
            "ConsistentRead": True,
        }
        while True:
            resp = self._table.query(**kwargs)
            for item in resp.get("Items", []):
                entries.append(
                    PermissionEntry(
                        subject=str(item["SUBJECT"]),
                        resource=str(item["RESOURCE"]),
                        allowed=bool(item.get("allowed", False)),
                        updated_by=str(item.get("updated_by", "")),
                        updated_at=str(item.get("updated_at", "")),
                    )
                )
            key = resp.get("LastEvaluatedKey")
            if not key:
                return entries
            kwargs["ExclusiveStartKey"] = key
