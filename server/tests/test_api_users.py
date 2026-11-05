"""User administration over HTTP: the gate, the boundary and the trail.

P5-14 / #46, stories 2 and 27. What `tests/test_accounts.py` proves about the
functions, this proves about the surface an admin actually presses -- plus the
half that only exists here: **who is allowed to press it.**

Real auth and real roles throughout, never an overridden `require_tenant_admin`.
The thing under test is which role gets through, and a test that overrode the
gate would be asserting the behaviour of its own override.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import accounts, repo
from app.db import get_session
from app.domain.roles import UserRole
from app.main import app
from app.models import Tenant
from app.tenancy import DEFAULT_TENANT_ID, actor_scope, tenant_scope

SEED_ADMIN_EMAIL = "admin@example.com"
SEED_ADMIN_PASSWORD = "admin"
SEED_TENANT_SLUG = "default"


@pytest.fixture()
def client(session, monkeypatch):
    monkeypatch.setenv("QA_SECRET_KEY", "test-key")
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, *, email, password, tenant=SEED_TENANT_SLUG):
    r = client.post(
        "/auth/login", json={"tenant": tenant, "email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    return r


@pytest.fixture()
def admin(client):
    _login(client, email=SEED_ADMIN_EMAIL, password=SEED_ADMIN_PASSWORD)
    return client


@pytest.fixture()
def member(client, session):
    """A member of the same tenant, logged in."""
    with tenant_scope(DEFAULT_TENANT_ID), actor_scope(SEED_ADMIN_EMAIL):
        added = accounts.add_user(
            session, email="member@example.com", role=UserRole.MEMBER
        )
    _login(client, email=added.user.email, password=added.password)
    return client


# --- the gate ------------------------------------------------------------

def test_an_admin_lists_their_tenants_users(admin):
    r = admin.get("/users")

    assert r.status_code == 200, r.text
    assert [u["email"] for u in r.json()] == [SEED_ADMIN_EMAIL]
    assert "credential" not in r.json()[0], "no password hash reaches the browser"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    (
        ("GET", "/users", None),
        ("POST", "/users", {"email": "x@example.com", "role": "member"}),
        ("DELETE", "/users/1", None),
    ),
)
def test_a_member_is_refused_every_user_administration_call(member, method, path, body):
    r = member.request(method, path, json=body)

    assert r.status_code == 403
    assert "admin" in r.json()["detail"]


@pytest.mark.parametrize(
    ("method", "path"),
    (("GET", "/users"), ("POST", "/users"), ("DELETE", "/users/1")),
)
def test_an_unauthenticated_caller_is_refused(client, method, path):
    assert client.request(method, path, json={}).status_code == 401


# --- inviting ------------------------------------------------------------

def test_an_admin_invites_a_user_and_is_shown_the_password_once(admin):
    r = admin.post("/users", json={"email": "New@Example.com ", "role": "member"})

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "new@example.com", "normalised, so logging in works"
    assert body["role"] == "member"
    assert body["password"], "the one time it exists in the clear"

    # And it is genuinely the password: the new user can log in with it.
    assert admin.post(
        "/auth/login",
        json={
            "tenant": SEED_TENANT_SLUG,
            "email": "new@example.com",
            "password": body["password"],
        },
    ).status_code == 200


def test_the_password_is_not_handed_out_again_by_the_listing(admin):
    admin.post("/users", json={"email": "new@example.com", "role": "member"})

    listed = admin.get("/users").json()

    assert all("password" not in u for u in listed), (
        "the password exists once, in the response that created the account"
    )


def test_an_invite_can_make_another_admin(admin):
    r = admin.post("/users", json={"email": "boss2@example.com", "role": "admin"})

    assert r.status_code == 201
    assert r.json()["role"] == "admin"


def test_a_duplicate_address_is_refused_with_a_readable_reason(admin):
    admin.post("/users", json={"email": "new@example.com", "role": "member"})

    r = admin.post("/users", json={"email": "new@example.com", "role": "member"})

    assert r.status_code == 409
    assert "already has an account" in r.json()["detail"]


def test_an_unknown_role_is_refused_by_the_schema(admin):
    r = admin.post("/users", json={"email": "new@example.com", "role": "superuser"})

    assert r.status_code == 422


# --- removing ------------------------------------------------------------

def test_an_admin_removes_a_user(admin):
    created = admin.post(
        "/users", json={"email": "new@example.com", "role": "member"}
    ).json()

    r = admin.delete(f"/users/{created['id']}")

    assert r.status_code == 204, r.text
    assert [u["email"] for u in admin.get("/users").json()] == [SEED_ADMIN_EMAIL]


def test_removing_the_last_admin_is_refused_and_the_portal_is_told_why(admin):
    """409 with the sentence, because this is a thing the operator must read
    and act on -- "make another admin first" is the remedy, and a bare status
    code does not carry it."""
    me = next(u for u in admin.get("/users").json() if u["email"] == SEED_ADMIN_EMAIL)

    r = admin.delete(f"/users/{me['id']}")

    assert r.status_code == 409
    assert "last admin" in r.json()["detail"]
    assert "another admin" in r.json()["detail"]


def test_removing_a_user_who_is_not_there_is_404(admin):
    assert admin.delete("/users/99999").status_code == 404


# --- the tenant boundary -------------------------------------------------

def test_another_tenants_user_cannot_be_removed_by_id(admin, session):
    """The id is a small integer, so guessing one is trivial. The read filter
    is what refuses it, and the answer is the same 404 an unknown id gets --
    "no such user" and "not yours" must not be distinguishable."""
    other = Tenant(name="Second", slug="second")
    session.add(other)
    session.commit()
    session.refresh(other)
    with tenant_scope(other.id), actor_scope("boss@second.example"):
        theirs = accounts.add_user(
            session, email="boss@second.example", role=UserRole.ADMIN
        ).user

    assert admin.delete(f"/users/{theirs.id}").status_code == 404

    with tenant_scope(other.id):
        assert [u.email for u in accounts.list_users(session)] == [
            "boss@second.example"
        ]


def test_an_invite_cannot_be_aimed_at_another_tenant(admin, session):
    """There is no tenant in the path or the body, so this is not a check the
    surface performs -- it is a request the surface cannot express. A smuggled
    id is ignored, and the account lands in the acting tenant."""
    other = Tenant(name="Second", slug="second")
    session.add(other)
    session.commit()
    session.refresh(other)

    r = admin.post(
        "/users",
        json={"email": "new@example.com", "role": "member", "tenant_id": other.id},
    )

    assert r.status_code == 201
    with tenant_scope(other.id):
        assert accounts.list_users(session) == []
    with tenant_scope(DEFAULT_TENANT_ID):
        assert "new@example.com" in {u.email for u in accounts.list_users(session)}


# --- the trail -----------------------------------------------------------

def test_adding_and_removing_are_audited_naming_the_acting_admin(admin, session):
    from app import audit
    from app.domain.audit import Action

    created = admin.post(
        "/users", json={"email": "new@example.com", "role": "member"}
    ).json()
    admin.delete(f"/users/{created['id']}")

    with tenant_scope(DEFAULT_TENANT_ID):
        rows = {e.action: e for e in audit.entries(session)}
    assert rows[Action.USER_ADD].actor == SEED_ADMIN_EMAIL
    assert rows[Action.USER_ADD].after == {"email": "new@example.com", "role": "member"}
    assert rows[Action.USER_REMOVE].actor == SEED_ADMIN_EMAIL
    assert rows[Action.USER_REMOVE].before == {
        "email": "new@example.com",
        "role": "member",
    }
    assert "password" not in str(rows[Action.USER_ADD].after)


def test_the_new_account_is_committed_rather_than_only_flushed(
    session_factory, monkeypatch
):
    """Two sessions, because one cannot see a missing commit -- the failure
    P5-06's prompt override shipped with. A route that only flushed would
    answer 201 and create nobody."""
    monkeypatch.setenv("QA_SECRET_KEY", "test-key")

    def _session():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _session
    try:
        with TestClient(app) as c:
            _login(c, email=SEED_ADMIN_EMAIL, password=SEED_ADMIN_PASSWORD)
            created = c.post(
                "/users", json={"email": "committed@example.com", "role": "member"}
            )
            assert created.status_code == 201, created.text
    finally:
        app.dependency_overrides.clear()

    with session_factory() as s:
        assert repo.get_user_for_login(
            s, tenant_slug=SEED_TENANT_SLUG, email="committed@example.com"
        ) is not None


# --- removal withdraws access (#56, from UAT 3) --------------------------
#
# Two cookie jars, because the thing under test is what *another* browser's
# session can still do after the admin pressed Remove. One client cannot hold
# two sessions: logging in replaces the jar.

def test_a_removed_users_own_session_dies_on_their_next_request(admin):
    """The window #56 closed, over HTTP and through the route an admin presses.

    The refresh fix that shipped with UAT 3 stops a removed user minting a new
    cookie. This is the one they already hold: before #56 the removed member
    kept their role for the rest of `ACCESS_MAX_AGE`, and the demonstration in
    the ticket was a user removed seconds earlier getting `POST /users` -> 201.
    """
    invited = admin.post("/users", json={"email": "leaver@example.com", "role": "member"})
    assert invited.status_code == 201, invited.text
    body = invited.json()

    with TestClient(app) as leaver:
        _login(leaver, email=body["email"], password=body["password"])
        assert leaver.get("/auth/me").status_code == 200

        assert admin.delete(f"/users/{body['id']}").status_code == 204

        # The cookie is untouched between those two requests: no logout, no
        # refresh, no new login.
        assert leaver.get("/auth/me").status_code == 401

    # And the admin who did the removing is unaffected.
    assert admin.get("/users").status_code == 200


def test_an_admin_who_removes_themselves_loses_access_at_once(admin):
    """UAT 3's finding, end to end: the sequence that was observed live.

    An admin removed *themselves* and went on working -- reading `/users`,
    creating another admin, changing the tenant's quotas -- all recorded in the
    audit log under the deleted account's name, which is how it was noticed.
    Two admins exist here because the last-admin rule (correctly) refuses the
    departure that would leave the tenant unadministrable.
    """
    invited = admin.post("/users", json={"email": "second@example.com", "role": "admin"})
    body = invited.json()

    with TestClient(app) as leaving_admin:
        _login(leaving_admin, email=body["email"], password=body["password"])

        assert leaving_admin.delete(f"/users/{body['id']}").status_code == 204

        assert leaving_admin.get("/users").status_code == 401
        # The move UAT 3 actually watched: creating another admin afterwards.
        assert leaving_admin.post(
            "/users", json={"email": "third@example.com", "role": "admin"}
        ).status_code == 401
