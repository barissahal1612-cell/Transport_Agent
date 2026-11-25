from logistic_ai_shared_auth.auth.users import (
    ADMIN,
    ROLES,
    DynamoUserRepository,
    InMemoryUserRepository,
    UserRecord,
)


def _u(name="alice", uid="1", role="SUPPLIER"):
    return UserRecord(userid=uid, username=name, role=role, password_hash="SECRET-HASH")


def test_repr_hides_hash():
    assert "SECRET-HASH" not in repr(_u())
    assert "SECRET-HASH" not in str(_u())


def test_roles_include_admin():
    assert ADMIN in ROLES and len(ROLES) == 4


def test_put_user_create_if_absent_and_lookup():
    repo = InMemoryUserRepository()
    assert repo.put_user(_u()) is True
    assert repo.put_user(_u()) is False
    assert repo.get_by_userid("1").username == "alice"
    assert repo.get_by_username("ALICE") is None


def test_lockout_and_reset():
    repo = InMemoryUserRepository([_u()])
    for _ in range(4):
        assert repo.record_failure("alice", 100.0, 5, 900).locked_until is None
    assert repo.record_failure("alice", 100.0, 5, 900).locked_until == 1000.0
    repo.reset_failures("alice")
    assert repo.get_by_username("alice").failed_count == 0


def test_active_admin_count():
    repo = InMemoryUserRepository([_u(), _u("root", "2", ADMIN)])
    assert repo.count_active_admins() == 1
    repo.set_active("root", False)
    assert repo.count_active_admins() == 0
    assert repo.set_active("nobody", True) is False


class _CondErr(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class _FakeTable:
    def __init__(self):
        self.calls = []
        self.put_raises = False

    def put_item(self, **kw):
        self.calls.append(("put", kw))
        if self.put_raises:
            raise _CondErr()

    def update_item(self, **kw):
        self.calls.append(("update", kw))
        return {"Attributes": {"USERNAME": "a", "USERID": "1", "ROLE": "SUPPLIER",
                               "password_hash": "h", "active": True, "failed_count": 5}}


def test_dynamo_conditional_put_and_atomic_counter():
    t = _FakeTable()
    repo = DynamoUserRepository(table=t)
    assert repo.put_user(_u()) is True
    assert t.calls[0][1]["ConditionExpression"] == "attribute_not_exists(USERNAME)"
    t.put_raises = True
    assert repo.put_user(_u()) is False
    rec = repo.record_failure("a", 10.0, 5, 900)
    upd = [c[1] for c in t.calls if c[0] == "update"]
    assert upd[0]["UpdateExpression"] == "ADD failed_count :one"
    assert rec.locked_until == 910.0
