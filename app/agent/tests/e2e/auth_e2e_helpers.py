"""Helpers for the auth/permission E2E tests (task 12.2).

* Real Excel auth sheets -> in-memory or fake-DynamoDB repositories via ``seed_workbook``.
* Real passwords are read from the workbook at test time and are wrapped in ``Cred`` so that
  they never show up in ``repr``/assertion output.
* ``FakeDynamoTable`` implements the subset of the boto3 ``Table`` API the adapters use.
"""
from __future__ import annotations

import copy
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]  # .../Logistic_AI
for _p in (ROOT / "scripts", ROOT / "app" / "agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from botocore.exceptions import ClientError  # noqa: E402
from argon2 import PasswordHasher as _Argon2  # noqa: E402

from ingest.excel_reader import WorkbookData, read_workbook  # noqa: E402
from ingest.seed import _text, seed_workbook  # noqa: E402
from logistic_ai_shared_auth.auth.passwords import PasswordHasher  # noqa: E402

EXCEL = ROOT / "Data" / "Agent_AWS_2026-11-24.xlsx"
ROLES = ("SUPPLIER", "MATERIAL_RESPONSIBLE", "TRANSPORT_OFFICE", "ADMIN")
SECRET = "e2e-session-secret-0123456789abcdef"

FUNCTION_TABLE = {
    "get_truck_location": "question1",
    "get_material_truck_allocation": "question2",
    "get_truck_route_info": "question3",
    "get_delayed_truck": "question4",
    "get_truck_tobearrived": "question5",
    "get_critical_part_status": "critical",
}


def fast_hasher() -> PasswordHasher:
    return PasswordHasher(_Argon2(time_cost=1, memory_cost=8, parallelism=1))


class Cred:
    """A real user from the workbook. The password is hidden from repr/str."""

    def __init__(self, role: str, userid: str, username: str, password: str) -> None:
        self.role, self.userid, self.username = role, userid, username
        self._password = password

    @property
    def password(self) -> str:
        return self._password

    def __repr__(self) -> str:
        return f"Cred(role={self.role!r}, username={self.username!r})"

    __str__ = __repr__


def load_workbook_subset(extra_suppliers: int = 1) -> tuple[WorkbookData, dict[str, Cred], list[Cred]]:
    """Real Excel rows: first user of every role (+ ``extra_suppliers`` more suppliers)."""
    wb = read_workbook(EXCEL)
    rows = wb.auth_sheets["role_user"]
    chosen: list[dict[str, Any]] = []
    by_role: dict[str, Cred] = {}
    extras: list[Cred] = []
    for row in rows:
        role = _text(row.get("ROLE"))
        cred = Cred(role, _text(row["USERID"]), _text(row["USERNAME"]), _text(row.get("Password")))
        if role in ROLES and role not in by_role:
            by_role[role] = cred
            chosen.append(row)
        elif role == "SUPPLIER" and len(extras) < extra_suppliers:
            extras.append(cred)
            chosen.append(row)
    missing = set(ROLES) - set(by_role)
    assert not missing, f"workbook has no user for roles {sorted(missing)}"
    subset = WorkbookData(
        sheets={},
        columns={},
        auth_sheets={"role_user": chosen, "permissions": wb.auth_sheets["permissions"]},
        report=wb.report,
    )
    return subset, by_role, extras


def seed(subset: WorkbookData, user_repo: Any, perm_repo: Any):
    report = seed_workbook(subset, apply=True, user_repo=user_repo, permission_repo=perm_repo, hasher=fast_hasher())
    return report


# --------------------------------------------------------------------------- audit
@dataclass
class RecordingAudit:
    events: list[tuple] = field(default_factory=list)

    def log_login(self, username, success):
        self.events.append(("login", username, bool(success)))

    def log_logout(self, username):
        self.events.append(("logout", username))

    def log_session_timeout(self, username):
        self.events.append(("timeout", username))

    def log_authorization_denied(self, username, role, permission):
        self.events.append(("denied", username, role, permission))

    def log_lockout(self, username):
        self.events.append(("lockout", username))


class RecordingAdminAudit:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def log_admin_action(self, record: dict) -> None:
        self.records.append(record)


class FixedSecret:
    def get_secret(self) -> str:
        return SECRET


# --------------------------------------------------------------------- fake DynamoDB
def _cond_fail(op: str) -> ClientError:
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "cond"}}, op)


def _reject_floats(value: Any) -> None:
    """boto3 refuses Python floats; the fake behaves the same."""
    if isinstance(value, float):
        raise TypeError("Float types are not supported. Use Decimal types instead.")
    if isinstance(value, dict):
        for v in value.values():
            _reject_floats(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _reject_floats(v)


class FakeDynamoTable:
    """In-process stand-in for a boto3 ``Table`` (hash [+ range] key, optional GSI on one attribute)."""

    def __init__(self, hash_key: str, range_key: str | None = None, gsi: dict[str, str] | None = None) -> None:
        self.hash_key, self.range_key = hash_key, range_key
        self.gsi = gsi or {}  # index name -> attribute
        self._items: dict[tuple, dict] = {}
        self.calls: list[str] = []

    # -- helpers
    def _k(self, source: dict) -> tuple:
        return (source[self.hash_key],) + ((source[self.range_key],) if self.range_key else ())

    @staticmethod
    def _cond_ok(expr: str | None, item: dict | None, hash_key: str) -> bool:
        if not expr:
            return True
        m = re.fullmatch(r"attribute_(not_)?exists\((\w+)\)", expr.strip())
        assert m, f"unsupported ConditionExpression {expr!r}"
        exists = item is not None
        return (not exists) if m.group(1) else exists

    @staticmethod
    def _present(item: dict) -> dict:
        return copy.deepcopy(item)

    # -- API
    def put_item(self, Item, ConditionExpression=None, **kw):
        self.calls.append("put_item")
        _reject_floats(Item)
        existing = self._items.get(self._k(Item))
        if not self._cond_ok(ConditionExpression, existing, self.hash_key):
            raise _cond_fail("PutItem")
        self._items[self._k(Item)] = copy.deepcopy(Item)
        return {}

    def get_item(self, Key, ConsistentRead=False, **kw):
        self.calls.append("get_item")
        item = self._items.get(self._k(Key))
        return {"Item": self._present(item)} if item is not None else {}

    def delete_item(self, Key, ReturnValues="NONE", **kw):
        self.calls.append("delete_item")
        old = self._items.pop(self._k(Key), None)
        if ReturnValues == "ALL_OLD" and old is not None:
            return {"Attributes": old}
        return {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues=None, ConditionExpression=None,
                    ReturnValues="NONE", **kw):
        self.calls.append("update_item")
        values = ExpressionAttributeValues or {}
        _reject_floats(values)
        existing = self._items.get(self._k(Key))
        if not self._cond_ok(ConditionExpression, existing, self.hash_key):
            raise _cond_fail("UpdateItem")
        item = copy.deepcopy(existing) if existing is not None else dict(Key)
        clauses = re.findall(r"(SET|ADD|REMOVE)\s+(.*?)(?=\s+(?:SET|ADD|REMOVE)\s|$)", UpdateExpression.strip())
        assert clauses, f"unsupported UpdateExpression {UpdateExpression!r}"
        for kind, body in clauses:
            if kind == "SET":
                for part in body.split(","):
                    name, val = [s.strip() for s in part.split("=")]
                    item[name] = copy.deepcopy(values[val])
            elif kind == "ADD":
                for part in body.split(","):
                    name, val = part.split()
                    item[name] = item.get(name, 0) + values[val]
            else:  # REMOVE
                for name in body.split(","):
                    item.pop(name.strip(), None)
        self._items[self._k(Key)] = item
        if ReturnValues == "ALL_NEW":
            return {"Attributes": self._present(item)}
        return {}

    def query(self, KeyConditionExpression, ExpressionAttributeValues, IndexName=None, ConsistentRead=False, **kw):
        self.calls.append("query")
        m = re.fullmatch(r"(\w+) = (:\w+)", KeyConditionExpression.strip())
        assert m, f"unsupported KeyConditionExpression {KeyConditionExpression!r}"
        attr, want = m.group(1), ExpressionAttributeValues[m.group(2)]
        if IndexName is not None:
            assert self.gsi.get(IndexName) == attr, "query on unknown index/attribute"
            assert not ConsistentRead, "GSIs do not support consistent reads"
        else:
            assert attr == self.hash_key
        items = [self._present(i) for i in self._items.values() if i.get(attr) == want]
        if self.range_key and IndexName is None:
            items.sort(key=lambda i: i[self.range_key])
        return {"Items": items}

    def scan(self, FilterExpression=None, ExpressionAttributeValues=None, **kw):
        self.calls.append("scan")
        items = [self._present(i) for i in self._items.values()]
        if FilterExpression:
            conds = []
            for part in FilterExpression.split(" AND "):
                m = re.fullmatch(r"(\w+) = (:\w+)", part.strip())
                assert m, f"unsupported FilterExpression {FilterExpression!r}"
                conds.append((m.group(1), ExpressionAttributeValues[m.group(2)]))
            items = [i for i in items if all(i.get(a) == v for a, v in conds)]
        return {"Items": items}


def users_table() -> FakeDynamoTable:
    return FakeDynamoTable("USERNAME", gsi={"userid-index": "USERID"})


def permissions_table() -> FakeDynamoTable:
    return FakeDynamoTable("SUBJECT", "RESOURCE")


# ------------------------------------------------------------------------ misc
def collect(gen) -> list:
    import asyncio

    async def run():
        return [e async for e in gen]

    return asyncio.run(run())


def locked_decimal(x: float) -> Decimal:
    return Decimal(str(x))
