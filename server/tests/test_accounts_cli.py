"""`python -m app.accounts` — onboarding a customer without SQL. P5-14 / #46.

Why this is a command and not a route is
docs/adr/0002-tenant-creation-is-an-operator-action.md. What is asserted here
is that it is a real substitute for the hand-written `INSERT` it replaces: it
validates, it writes both rows together, it cannot leave a tenant
unadministrable, and the customer can log in afterwards.

The command is driven through `main(argv)` rather than a subprocess: the
database it must act on is the one the fixtures built, and a subprocess would
get its own connection to whatever `DATABASE_URL` happens to say -- which in
CI is nothing. `tests/test_delivery_cli.py` takes the same approach for the
same reason.
"""

from __future__ import annotations

import pytest

from app import accounts, audit, repo
from app.accounts import __main__ as cli
from app.domain.audit import Action
from app.domain.roles import UserRole
from app.models import Tenant
from app.tenancy import SYSTEM_ACTOR, tenant_scope


@pytest.fixture()
def db(session, monkeypatch):
    """Point the CLI's own `SessionLocal` at the test session.

    The command opens its own session because it has none -- it is a console
    entry point -- so the seam to substitute is that factory. Borrowed rather
    than a second connection, for the reason tests/control_helpers.py spells
    out: two sessions in one test means two teardowns, and the second one's
    TRUNCATE waits for ever on the first one's open transaction.
    """
    monkeypatch.setattr(cli, "SessionLocal", lambda: _Borrowed(session))
    return session


class _Borrowed:
    """A context manager that lends a session it does not own."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False  # emphatically does not close it


def test_create_tenant_makes_a_tenant_and_its_first_admin(db, capsys):
    exit_code = cli.main(
        ["create-tenant", "--name", "Acme Ltd", "--slug", "acme", "--admin", "boss@acme.example"]
    )

    assert exit_code == cli.EXIT_OK
    tenant = db.scalars(repo.select(Tenant).where(Tenant.slug == "acme")).one()
    assert tenant.name == "Acme Ltd"
    with tenant_scope(tenant.id):
        (admin,) = accounts.list_users(db)
    assert admin.email == "boss@acme.example"
    assert admin.role is UserRole.ADMIN


def test_the_printed_password_is_the_one_that_logs_in(db, capsys):
    cli.main(
        ["create-tenant", "--name", "Acme", "--slug", "acme", "--admin", "boss@acme.example"]
    )

    printed = capsys.readouterr().out
    # The password is on its own line, labelled, so an operator can copy it
    # without the surrounding prose.
    password = [
        line.split(":", 1)[1].strip()
        for line in printed.splitlines()
        if line.lower().startswith("password:")
    ][0]
    assert password

    user = repo.get_user_for_login(db, tenant_slug="acme", email="boss@acme.example")
    from app.auth import verify_password

    assert verify_password(password, user.credential) is True


def test_a_duplicate_slug_is_refused_rather_than_creating_a_second_tenant(db, capsys):
    """The slug is what a user types to log in, so two tenants sharing one
    would make "which tenant's user table?" unanswerable."""
    assert cli.main(
        ["create-tenant", "--name", "First", "--slug", "acme", "--admin", "a@acme.example"]
    ) == cli.EXIT_OK

    exit_code = cli.main(
        ["create-tenant", "--name", "Second", "--slug", "acme", "--admin", "b@acme.example"]
    )

    assert exit_code == cli.EXIT_ERROR
    assert "already taken" in capsys.readouterr().err
    assert len(db.scalars(repo.select(Tenant).where(Tenant.slug == "acme")).all()) == 1


def test_a_bad_admin_address_leaves_no_tenant_behind(db, capsys):
    """A tenant with no admin is the state `remove_user` refuses to create, so
    the command must not create it either: the two writes are one transaction,
    and a refusal rolls the tenant back rather than leaving an orphan nobody
    can log into or administer."""
    exit_code = cli.main(
        ["create-tenant", "--name", "Acme", "--slug", "acme", "--admin", "not-an-email"]
    )

    assert exit_code == cli.EXIT_ERROR
    assert db.scalars(repo.select(Tenant).where(Tenant.slug == "acme")).all() == []


def test_the_first_admin_is_audited_against_the_new_tenant_as_system(db):
    """The actor is `system`, which is honest: the CLI binds no user, and "a
    human at a console did this and we cannot say which human" beats silence
    (the argument app/delivery/__main__.py already makes)."""
    cli.main(
        ["create-tenant", "--name", "Acme", "--slug", "acme", "--admin", "boss@acme.example"]
    )

    tenant = db.scalars(repo.select(Tenant).where(Tenant.slug == "acme")).one()
    with tenant_scope(tenant.id):
        (row,) = [e for e in audit.entries(db) if e.action is Action.USER_ADD]
    assert row.actor == SYSTEM_ACTOR
    assert row.tenant_id == tenant.id, "recorded against the tenant being created"
    assert row.after == {"email": "boss@acme.example", "role": "admin"}


def test_the_command_prints_what_to_do_next(db, capsys):
    """An operator finishing this has to tell the customer two things -- the
    slug they log in with and the password -- and the slug is not obvious from
    the name they gave."""
    cli.main(
        ["create-tenant", "--name", "Acme Ltd", "--slug", "acme", "--admin", "boss@acme.example"]
    )

    out = capsys.readouterr().out
    assert "acme" in out
    assert "boss@acme.example" in out
    assert "not shown again" in out.lower()


def test_an_unknown_command_is_a_usage_error(db):
    with pytest.raises(SystemExit):
        cli.main(["demolish-tenant", "--slug", "acme"])
