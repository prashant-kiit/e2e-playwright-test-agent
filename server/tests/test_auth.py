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
from app.tenancy import across_tenants

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


SEED_TENANT_SLUG = "default"


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


def test_the_single_week_long_cookie_api_is_gone():
    """The one-cookie session is not deprecated, it is removed: a caller still
    reaching for `mint_token`/`MAX_AGE` would be minting something nothing
    reads, and `COOKIE_NAME` no longer says *which* of the two cookies it
    means."""
    for name in ("mint_token", "read_token", "COOKIE_NAME", "MAX_AGE"):
        assert not hasattr(auth, name), name


def test_login_requires_an_email_not_just_a_password(client):
    """A password-only body (the shared-password shape) is now a 422."""
    assert client.post("/auth/login", json={"password": "admin"}).status_code == 422


def test_login_requires_a_tenant(client):
    """Email alone no longer names an account, so a body without a tenant slug
    is a 422 rather than a guess at which tenant was meant."""
    _add_user(client_session(client), email="dev@example.com", password="s3cret")
    r = client.post(
        "/auth/login", json={"email": "dev@example.com", "password": "s3cret"}
    )
    assert r.status_code == 422


# --- per-user login -------------------------------------------------------

def test_protected_route_rejects_without_cookie(client):
    assert client.get("/projects").status_code == 401


def test_login_wrong_password_is_401(client):
    _add_user(client_session(client), email="dev@example.com", password="right")
    assert client.post(
        "/auth/login",
        json={"tenant": SEED_TENANT_SLUG, "email": "dev@example.com", "password": "wrong"},
    ).status_code == 401


def test_login_unknown_email_is_401(client):
    assert client.post(
        "/auth/login",
        json={"tenant": SEED_TENANT_SLUG, "email": "nobody@example.com", "password": "x"},
    ).status_code == 401


def test_a_user_logs_in_as_themselves(client):
    _add_user(client_session(client), email="dev@example.com", password="s3cret")

    r = client.post(
        "/auth/login",
        json={"tenant": SEED_TENANT_SLUG, "email": "dev@example.com", "password": "s3cret"},
    )
    assert r.status_code == 200
    assert auth.ACCESS_COOKIE in r.cookies

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
        json={
            "tenant": SEED_TENANT_SLUG,
            "email": SEED_ADMIN_EMAIL,
            "password": SEED_ADMIN_PASSWORD,
        },
    )
    assert r.status_code == 200
    assert client.get("/auth/me").json()["role"] == "admin"


def test_logout_clears_the_cookie(client):
    _add_user(client_session(client), email="dev@example.com", password="s3cret")
    client.post(
        "/auth/login",
        json={"tenant": SEED_TENANT_SLUG, "email": "dev@example.com", "password": "s3cret"},
    )
    client.post("/auth/logout")
    client.cookies.clear()
    assert client.get("/auth/me").status_code == 401


# --- the session carries the tenant --------------------------------------

def test_an_insert_in_a_session_uses_that_users_tenant(client):
    """The core P5 seam, observed through behaviour: a user in tenant 2 creates
    a project, and the row is written with tenant_id 2 -- `current_tenant_id()`
    resolved from their session, not the constant 1."""
    s = client_session(client)
    s.add(Tenant(id=2, slug="second", name="second"))
    s.commit()
    _add_user(s, email="t2@example.com", password="pw", tenant_id=2)

    client.post(
        "/auth/login", json={"tenant": "second", "email": "t2@example.com", "password": "pw"}
    )
    r = client.post("/projects", json={"name": "owned-by-t2"})
    assert r.status_code == 201

    # The assertion reads across tenants on purpose: this test is standing
    # outside both of them, checking which tenant the row was written to. From
    # inside tenant 1 -- which is what `current_tenant_id()` answers here, with
    # no request scope around the test body -- the enforced read path (P5-02)
    # correctly hides a tenant-2 row, and the test would be unable to see the
    # very thing it is asserting about.
    project = s.scalars(
        across_tenants(select(Project).where(Project.name == "owned-by-t2"))
    ).one()
    assert project.tenant_id == 2


# --- roles gate the tenant-admin actions ----------------------------------

def test_a_member_is_refused_a_tenant_admin_action(client):
    """Delivery approval is admin-only; a member gets 403 before any push."""
    _add_user(client_session(client), email="member@example.com", password="pw")
    client.post(
        "/auth/login",
        json={"tenant": SEED_TENANT_SLUG, "email": "member@example.com", "password": "pw"},
    )

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
        json={
            "tenant": SEED_TENANT_SLUG,
            "email": SEED_ADMIN_EMAIL,
            "password": SEED_ADMIN_PASSWORD,
        },
    )
    r = client.post("/targets/999/deliver", json={"story_id": "SCRUM-1"})
    assert r.status_code == 404


# --- the tenant slug is what disambiguates the email ---------------------

def test_the_same_email_logs_into_the_tenant_its_slug_names(client):
    """The behaviour the composite constraint exists for, end to end.

    One address, two tenants, two different passwords. The slug in the login
    body decides which account answers -- and `/auth/me` reports that tenant, so
    the session that comes back is scoped to it and not to whichever row the
    database happened to return first.
    """
    s = client_session(client)
    s.add(Tenant(id=2, slug="second", name="second"))
    s.commit()
    _add_user(s, email="ops@contractor.com", password="pw-one", tenant_id=1)
    _add_user(s, email="ops@contractor.com", password="pw-two", tenant_id=2)

    for slug, password, tenant_id in (("default", "pw-one", 1), ("second", "pw-two", 2)):
        r = client.post(
            "/auth/login",
            json={"tenant": slug, "email": "ops@contractor.com", "password": password},
        )
        assert r.status_code == 200, slug
        assert client.get("/auth/me").json()["tenant_id"] == tenant_id
        client.cookies.clear()

    # ...and a tenant's password does not open the other tenant's account.
    assert client.post(
        "/auth/login",
        json={"tenant": "second", "email": "ops@contractor.com", "password": "pw-one"},
    ).status_code == 401


def test_login_to_an_unknown_tenant_is_401(client):
    """An unknown slug, an unknown email and a wrong password are the same 401:
    a probe cannot map out which tenants exist any more than which users do."""
    _add_user(client_session(client), email="dev@example.com", password="s3cret")
    assert client.post(
        "/auth/login",
        json={"tenant": "no-such-tenant", "email": "dev@example.com", "password": "s3cret"},
    ).status_code == 401


# --- the access token expires, and the refresh token renews it -----------

def _login(client, *, email="dev@example.com", password="s3cret", tenant=SEED_TENANT_SLUG):
    return client.post(
        "/auth/login", json={"tenant": tenant, "email": email, "password": password}
    )


def test_login_sets_both_an_access_and_a_refresh_cookie(client):
    _add_user(client_session(client), email="dev@example.com", password="s3cret")
    r = _login(client)
    assert r.status_code == 200
    assert auth.ACCESS_COOKIE in r.cookies
    assert auth.REFRESH_COOKIE in r.cookies
    # The two must not be the same string, or the short lifetime is decorative.
    assert r.cookies[auth.ACCESS_COOKIE] != r.cookies[auth.REFRESH_COOKIE]


def test_the_access_cookie_expires_and_refresh_renews_the_session(client, monkeypatch):
    """The whole point of the split, through real cookies over real HTTP.

    The access cookie's lifetime is squeezed to a second so the test can outlive
    it. Past that second the session is refused -- which is what "the token
    expires" has to mean to be worth anything -- and `POST /auth/refresh`, which
    reads the still-valid refresh cookie, hands back a working one.
    """
    import time

    monkeypatch.setattr(auth, "ACCESS_MAX_AGE", 1)
    _add_user(client_session(client), email="dev@example.com", password="s3cret")
    assert _login(client).status_code == 200
    assert client.get("/auth/me").status_code == 200

    time.sleep(1.1)
    assert client.get("/auth/me").status_code == 401, "an aged access cookie still worked"

    # Put a realistic lifetime back before refreshing. What is under test here
    # is that refresh renews the session, not that a one-second cookie can be
    # raced to the next assertion on a loaded CI box.
    monkeypatch.setattr(auth, "ACCESS_MAX_AGE", 15 * 60)
    assert client.post("/auth/refresh").status_code == 200
    assert client.get("/auth/me").status_code == 200


def test_refresh_without_a_refresh_cookie_is_401(client):
    assert client.post("/auth/refresh").status_code == 401


def test_an_expired_refresh_cookie_cannot_renew(client, monkeypatch):
    """The refresh token is the outer bound on a session: once *it* ages out,
    there is nothing left to trade and the user logs in again. Without this the
    pair would be a session that never ends."""
    import time

    monkeypatch.setattr(auth, "ACCESS_MAX_AGE", 1)
    monkeypatch.setattr(auth, "REFRESH_MAX_AGE", 1)
    _add_user(client_session(client), email="dev@example.com", password="s3cret")
    _login(client)

    time.sleep(1.1)
    assert client.post("/auth/refresh").status_code == 401


def test_a_refresh_token_is_not_an_access_token(client):
    """The two are signed with different salts, so the long-lived cookie cannot
    be presented as a session. Otherwise the access cookie's short life would be
    trivially bypassed by sending the refresh token in its place."""
    _add_user(client_session(client), email="dev@example.com", password="s3cret")
    _login(client)
    refresh = client.cookies[auth.REFRESH_COOKIE]

    client.cookies.clear()
    client.cookies.set(auth.ACCESS_COOKIE, refresh)
    assert client.get("/auth/me").status_code == 401


def test_an_access_token_cannot_be_used_to_refresh(client):
    """And the other direction: a stolen access cookie does not mint itself a
    fresh one, so its short life is the real bound on what it is worth."""
    _add_user(client_session(client), email="dev@example.com", password="s3cret")
    _login(client)
    access = client.cookies[auth.ACCESS_COOKIE]

    client.cookies.clear()
    client.cookies.set(auth.REFRESH_COOKIE, access)
    assert client.post("/auth/refresh").status_code == 401


def test_refresh_preserves_the_tenant_and_role(client):
    """A renewed session is the *same* session: a member in tenant 2 who
    refreshes is still a member in tenant 2, not the resolver's default."""
    s = client_session(client)
    s.add(Tenant(id=2, slug="second", name="second"))
    s.commit()
    _add_user(s, email="t2@example.com", password="pw", tenant_id=2)
    _login(client, tenant="second", email="t2@example.com", password="pw")

    before = client.get("/auth/me").json()
    assert client.post("/auth/refresh").status_code == 200
    assert client.get("/auth/me").json() == before == {
        "authenticated": True,
        "email": "t2@example.com",
        "role": "member",
        "tenant_id": 2,
    }


def test_logout_clears_the_refresh_cookie_too(client):
    """A logout that left the refresh cookie behind would not be a logout: the
    next refresh would mint a new session out of it."""
    _add_user(client_session(client), email="dev@example.com", password="s3cret")
    _login(client)
    r = client.post("/auth/logout")
    assert r.status_code == 200
    # Both cookies are expired by the response, so what the client keeps is
    # empty rather than a usable token.
    assert client.cookies.get(auth.REFRESH_COOKIE) in (None, "")
    assert client.post("/auth/refresh").status_code == 401


def test_the_cookies_carry_the_attributes_the_session_depends_on(client):
    """Pin the two Set-Cookie attributes that fail silently when they regress.

    `Path=/auth` on the refresh cookie is what `clear_session_cookies` has to
    match to delete it -- a refresh cookie re-pathed to "/" would leave logout
    deleting nothing and the browser still holding a 30-day credential, and
    every other test here would still pass. The access cookie's `Max-Age` is
    the expiry itself; without this, dropping it (making it a session cookie
    the browser keeps until it closes) would go unnoticed.
    """
    _add_user(client_session(client), email="dev@example.com", password="s3cret")
    headers = _login(client).headers.get_list("set-cookie")
    access = next(h for h in headers if h.startswith(f"{auth.ACCESS_COOKIE}="))
    refresh = next(h for h in headers if h.startswith(f"{auth.REFRESH_COOKIE}="))

    assert f"Max-Age={auth.ACCESS_MAX_AGE}" in access
    assert "Path=/; " in access or access.endswith("Path=/")
    assert "HttpOnly" in access

    assert f"Max-Age={auth.REFRESH_MAX_AGE}" in refresh
    assert f"Path={auth.REFRESH_PATH}" in refresh
    assert "HttpOnly" in refresh
