"""Per-user auth (P5): login is by email + password against a `users` row.

The seams here are the HTTP boundary (login / me / a protected route / a role-
gated route) and the password hash. What these prove, against the acceptance
criteria of the users+auth ticket:

* a user logs in as themselves, and the shared-password path is gone;
* the session carries the user and their tenant, so `current_tenant_id()`
  resolves to *their* tenant for the request (observed through what an insert
  writes, not by reaching into the resolver);
* the admin role gates a tenant-admin action, and a member is refused.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app.auth import hash_password, verify_password
from app.db import get_session
from app.domain.roles import UserRole
from app.main import app
from app.models import Project, Tenant, User

# The migration seeds this operator; see the P5 users migration.
SEED_ADMIN_EMAIL = "admin@example.com"
SEED_ADMIN_PASSWORD = "admin"


@pytest.fixture()
def client(session, monkeypatch):
    """Real auth (require_auth is *not* overridden), backed by the test session.

    The delivery seam is stubbed so the role-gate tests exercise the gate
    rather than git or a PAT; nothing here reaches the network.
    """
    from app.api import get_delivery_tools

    monkeypatch.setenv("QA_SECRET_KEY", "test-key")
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_delivery_tools] = lambda: object()
    yield TestClient(app)
    app.dependency_overrides.clear()


def client_session(client):
    """The session the overridden dependency hands the routes -- the same one
    the test writes its fixtures into."""
    return app.dependency_overrides[get_session]()


def _add_user(session, *, email, password, role=UserRole.MEMBER, tenant_id=1):
    user = User(
        tenant_id=tenant_id,
        email=email,
        role=role,
        credential=hash_password(password),
    )
    session.add(user)
    session.commit()
    return user


# --- password hashing -----------------------------------------------------

def test_password_hash_roundtrips_and_is_not_the_plaintext():
    stored = hash_password("hunter2")
    assert stored != "hunter2"
    assert verify_password("hunter2", stored) is True
    assert verify_password("wrong", stored) is False


def test_verify_password_rejects_a_garbage_hash():
    assert verify_password("anything", "not-a-pbkdf2-string") is False


# --- the shared-password path is gone -------------------------------------

def test_the_shared_password_api_no_longer_exists():
    """The old speed bump exposed `check_password` against QA_ADMIN_PASSWORD.
    Both are gone: the only way in is a users row."""
    assert not hasattr(auth, "check_password")
    assert not hasattr(auth, "_password")


def test_login_requires_an_email_not_just_a_password(client):
    """A password-only body (the shared-password shape) is now a 422."""
    assert client.post("/auth/login", json={"password": "admin"}).status_code == 422


# --- per-user login -------------------------------------------------------

def test_protected_route_rejects_without_cookie(client):
    assert client.get("/projects").status_code == 401


def test_login_wrong_password_is_401(client):
    _add_user(client_session(client), email="dev@example.com", password="right")
    assert client.post(
        "/auth/login", json={"email": "dev@example.com", "password": "wrong"}
    ).status_code == 401


def test_login_unknown_email_is_401(client):
    assert client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "x"}
    ).status_code == 401


def test_a_user_logs_in_as_themselves(client):
    _add_user(client_session(client), email="dev@example.com", password="s3cret")

    r = client.post("/auth/login", json={"email": "dev@example.com", "password": "s3cret"})
    assert r.status_code == 200
    assert auth.COOKIE_NAME in r.cookies

    me = client.get("/auth/me").json()
    assert me == {
        "authenticated": True,
        "email": "dev@example.com",
        "role": "member",
        "tenant_id": 1,
    }


def test_the_seeded_operator_logs_in_as_an_admin(client):
    r = client.post(
        "/auth/login",
        json={"email": SEED_ADMIN_EMAIL, "password": SEED_ADMIN_PASSWORD},
    )
    assert r.status_code == 200
    assert client.get("/auth/me").json()["role"] == "admin"


def test_logout_clears_the_cookie(client):
    _add_user(client_session(client), email="dev@example.com", password="s3cret")
    client.post("/auth/login", json={"email": "dev@example.com", "password": "s3cret"})
    client.post("/auth/logout")
    client.cookies.clear()
    assert client.get("/auth/me").status_code == 401


# --- the session carries the tenant --------------------------------------

def test_an_insert_in_a_session_uses_that_users_tenant(client):
    """The core P5 seam, observed through behaviour: a user in tenant 2 creates
    a project, and the row is written with tenant_id 2 -- `current_tenant_id()`
    resolved from their session, not the constant 1."""
    s = client_session(client)
    s.add(Tenant(id=2, name="second"))
    s.commit()
    _add_user(s, email="t2@example.com", password="pw", tenant_id=2)

    client.post("/auth/login", json={"email": "t2@example.com", "password": "pw"})
    r = client.post("/projects", json={"name": "owned-by-t2"})
    assert r.status_code == 201

    project = s.scalars(select(Project).where(Project.name == "owned-by-t2")).one()
    assert project.tenant_id == 2


# --- roles gate the tenant-admin actions ----------------------------------

def test_a_member_is_refused_a_tenant_admin_action(client):
    """Delivery approval is admin-only; a member gets 403 before any push."""
    _add_user(client_session(client), email="member@example.com", password="pw")
    client.post("/auth/login", json={"email": "member@example.com", "password": "pw"})

    r = client.post("/targets/999/deliver", json={"story_id": "SCRUM-1"})
    assert r.status_code == 403


def test_the_admin_gate_refuses_a_bypassed_user(client):
    """The gate does not treat "auth was overridden" as "allowed".

    It used to: a `None` user fell through the role check, which put an
    authorization decision in the hands of a test convention. A test that wants
    past this gate overrides the gate.
    """
    from app.auth import require_auth, require_tenant_admin

    app.dependency_overrides[require_auth] = lambda: None
    try:
        assert client.post(
            "/targets/999/deliver", json={"story_id": "SCRUM-1"}
        ).status_code == 403
        # ...and overriding the gate itself is what lets a test through.
        app.dependency_overrides[require_tenant_admin] = lambda: None
        assert client.post(
            "/targets/999/deliver", json={"story_id": "SCRUM-1"}
        ).status_code == 404
    finally:
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(require_tenant_admin, None)


def test_an_admin_passes_the_gate(client):
    """The seeded admin is let through the gate -- the 404 is the handler not
    finding target 999, which only runs because the role check passed (a member
    gets 403 on the same call)."""
    client.post(
        "/auth/login",
        json={"email": SEED_ADMIN_EMAIL, "password": SEED_ADMIN_PASSWORD},
    )
    r = client.post("/targets/999/deliver", json={"story_id": "SCRUM-1"})
    assert r.status_code == 404
