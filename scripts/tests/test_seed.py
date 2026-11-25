from ingest.excel_reader import ReadReport, WorkbookData
from ingest.seed import seed_workbook
from logistic_ai_shared_auth.auth.passwords import PasswordHasher
from logistic_ai_shared_auth.auth.users import InMemoryUserRepository
from logistic_ai_shared_auth.authorization.permission_store import InMemoryPermissionRepository


def wb(users, perms):
    return WorkbookData(sheets={}, columns={}, auth_sheets={"role_user": users, "permissions": perms},
                        report=ReadReport())


U = [
    {"ROLE": "ADMIN", "USERID": "ADMIN001", "USERNAME": "admin", "Password": 123456},
    {"ROLE": "SUPPLIER", "USERID": "129-01", "USERNAME": "s1", "Password": "pw"},
    {"ROLE": "BOGUS", "USERID": "1", "USERNAME": "x", "Password": "p"},
    {"ROLE": "SUPPLIER", "USERID": "2", "USERNAME": "s1", "Password": "p"},
    {"ROLE": "SUPPLIER", "USERID": "129-01", "USERNAME": "s2", "Password": "p"},
]
P = [
    {"ROLE": "SUPPLIER", "RESOURCE_TYPE": "TABLE", "RESOURCE_NAME": "question1", "ALLOWED": 1},
    {"ROLE": "SUPPLIER", "RESOURCE_TYPE": "FUNCTION", "RESOURCE_NAME": "get_truck_location", "ALLOWED": 0},
    {"ROLE": "SUPPLIER", "RESOURCE_TYPE": "TABLE", "RESOURCE_NAME": "role_user", "ALLOWED": 1},
    {"ROLE": "SUPPLIER", "RESOURCE_TYPE": "TABLE", "RESOURCE_NAME": "question2", "ALLOWED": 2},
    {"ROLE": "NOPE", "RESOURCE_TYPE": "TABLE", "RESOURCE_NAME": "question2", "ALLOWED": 1},
]


class Boom:
    def __getattr__(self, n): raise AssertionError("must not be called in dry-run")


def test_dry_run_touches_nothing():
    r = seed_workbook(wb(U, P), user_repo=Boom(), permission_repo=Boom(), hasher=Boom())
    assert not r.applied
    assert (r.sheets["role_user"].loaded, r.sheets["role_user"].skipped) == (2, 3)
    assert (r.sheets["permissions"].loaded, r.sheets["permissions"].skipped) == (2, 3)


def test_apply_idempotent_and_hashed():
    ur, pr = InMemoryUserRepository(), InMemoryPermissionRepository()
    r = seed_workbook(wb(U, P), apply=True, user_repo=ur, permission_repo=pr)
    assert r.sheets["role_user"].loaded == 2
    u = ur.get_by_username("admin")
    assert u.userid == "ADMIN001" and u.active and "123456" not in u.password_hash
    assert PasswordHasher().verify(u.password_hash, "123456")
    assert pr.get("ROLE#SUPPLIER", "TABLE#question1") is True
    assert pr.get("ROLE#SUPPLIER", "FUNCTION#get_truck_location") is False
    pr.put("ROLE#SUPPLIER", "TABLE#question1", False, "admin")
    r2 = seed_workbook(wb(U, P), apply=True, user_repo=ur, permission_repo=pr)
    assert r2.sheets["role_user"].loaded == 0 and r2.sheets["permissions"].loaded == 0
    assert pr.get("ROLE#SUPPLIER", "TABLE#question1") is False
    out = r.render() + r2.render()
    assert "123456" not in out and "pw" not in out.split()
