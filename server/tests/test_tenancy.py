"""`tenant_id` everywhere, and the one helper that resolves it.

The structural test here is the assertion that makes P5 a data backfill rather
than a migration across every model: if a future table forgets `tenant_id`, it
fails here rather than when a second tenant exists.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401  (register the ORM tables on Base.metadata)
from app import repo
from app.db import Base
from app.domain.roles import UserRole
from app.models import Revision, Tenant, User
from app.tenancy import DEFAULT_TENANT_ID, current_tenant_id, tenant_scope
from tests.target_helpers import create_target


def test_every_table_has_a_non_null_tenant_id():
    """Every table carries the column, so P5 only has to backfill its values.

    `tenants` itself is exempt: its own id *is* the tenant.
    """
    offenders = {}
    for table in Base.metadata.sorted_tables:
        if table.name == "tenants":
            continue
        col = table.columns.get("tenant_id")
        if col is None:
            offenders[table.name] = "no tenant_id column"
        elif col.nullable:
            offenders[table.name] = "tenant_id is nullable"
    assert offenders == {}, f"tables not ready for P5's backfill: {offenders}"


def test_no_table_keeps_the_backfill_server_default():
    """The migration adds `tenant_id` with a server default so existing rows
    backfill, then drops it in the same revision. A lingering default would let
    application code forget to set the column and still pass."""
    for table in Base.metadata.sorted_tables:
        col = table.columns.get("tenant_id")
        if col is not None:
            assert col.server_default is None, (
                f"{table.name}.tenant_id still has a server default; "
                "application code must set it from current_tenant_id()"
            )


def test_current_tenant_id_is_the_single_seeded_tenant():
    """Outside any request/run scope it is the seeded default -- which is what
    keeps the thread/CI path and every pure-domain test writing tenant 1."""
    assert current_tenant_id() == DEFAULT_TENANT_ID == 1


def test_current_tenant_id_resolves_from_an_active_scope():
    """P5's replacement: inside a scope (a request's authenticated user, or a
    run on the thread path) the resolver answers that tenant, not the constant.

    The call sites in repo.py do not change; this one function does."""
    with tenant_scope(42):
        assert current_tenant_id() == 42
    # and it falls back the moment the scope closes
    assert current_tenant_id() == DEFAULT_TENANT_ID


def test_tenant_scopes_nest_and_restore():
    with tenant_scope(7):
        assert current_tenant_id() == 7
        with tenant_scope(9):
            assert current_tenant_id() == 9
        assert current_tenant_id() == 7
    assert current_tenant_id() == DEFAULT_TENANT_ID


def test_the_migration_seeds_exactly_one_tenant(session):
    tenants = list(session.scalars(repo.select(Tenant)))
    assert [t.id for t in tenants] == [DEFAULT_TENANT_ID]


def test_the_migration_seeds_the_single_operator_as_a_tenant_admin(session):
    """P5 preserves the shared-password operator as one admin user in the
    default tenant, so yesterday's login still works -- as a real user now."""
    users = list(session.scalars(repo.select(User)))
    assert len(users) == 1
    (admin,) = users
    assert admin.tenant_id == DEFAULT_TENANT_ID
    assert admin.role is UserRole.ADMIN
    # The credential is a hash, never the password itself.
    assert admin.credential != "admin"


def test_the_thread_path_binds_the_runs_tenant(session):
    """The background equivalent of `require_auth`: `drive_run` resolves the
    run's tenant and binds it, so a run's inserts are written as its own tenant
    and not the resolver's default."""
    from sqlalchemy.orm import sessionmaker

    from app.launcher import _run_tenant_scope

    session.add(Tenant(id=2, slug="second", name="second"))
    session.commit()
    with tenant_scope(2):
        project = repo.create_project(session, name="t2")
        target = create_target(session, project.id, app="a2", name="A2")
        run = repo.start_run(session, target_id=target.id, story_id="SCRUM-1", mode="full")
    assert run.tenant_id == 2

    # A throwaway factory on the same engine: `_run_tenant_scope` opens and
    # closes its own session, so it must not be handed the fixture's shared one.
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False, future=True)

    assert current_tenant_id() == DEFAULT_TENANT_ID  # outside the scope
    with _run_tenant_scope(run.id, factory):
        assert current_tenant_id() == 2
    assert current_tenant_id() == DEFAULT_TENANT_ID  # restored after


def test_insert_paths_set_tenant_id_explicitly(session):
    """Not by relying on a database default -- there is none to rely on."""
    project = repo.create_project(session, name="demo")
    target = create_target(session, project.id, app="a", name="A")
    run = repo.start_run(session, target_id=target.id, story_id="SCRUM-1", mode="full")
    step = repo.start_step(session, run.id, repo.Step.READ_STORY)
    lock = session.get(app.models.AppLock, target.id)

    for row in (project, target, run, step, lock):
        assert row.tenant_id == current_tenant_id(), row


def test_a_revision_cannot_be_inserted_twice_for_the_same_target_and_rev(session):
    """The unique constraint *is* this phase's concurrency control (DESIGN §3):
    a concurrent committer of rev N+1 loses here rather than on a version
    column."""
    project = repo.create_project(session, name="demo")
    target = create_target(session, project.id, app="a", name="A")

    session.add(
        Revision(
            tenant_id=current_tenant_id(),
            target_id=target.id,
            rev=1,
            parent_rev=None,
            tree_hash="a" * 64,
            author="test",
        )
    )
    session.commit()

    session.add(
        Revision(
            tenant_id=current_tenant_id(),
            target_id=target.id,
            rev=1,
            parent_rev=None,
            tree_hash="b" * 64,
            author="test",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_delivered_sha_exists_and_is_never_written_in_p2(session):
    """P2 adds the column and leaves it null: delivery still works off the
    filesystem, so invariant 5 is deliberately not satisfied yet."""
    assert "delivered_sha" in Revision.__table__.columns

    project = repo.create_project(session, name="demo")
    target = create_target(session, project.id, app="a", name="A")
    rev = Revision(
        tenant_id=current_tenant_id(),
        target_id=target.id,
        rev=1,
        tree_hash="a" * 64,
        author="test",
    )
    session.add(rev)
    session.commit()
    assert rev.delivered_sha is None


# --- the tenant's login slug ---------------------------------------------

def test_the_seeded_tenant_has_a_slug(session):
    """A tenant needs a stable handle a person can type at the login form: the
    id is an implementation detail and the name is prose. The migration gives
    the seeded tenant `default`."""
    (tenant,) = list(session.scalars(repo.select(Tenant)))
    assert tenant.slug == "default"


def test_two_tenants_cannot_share_a_slug(session):
    """The slug is what login resolves a tenant *by*, so it has to be unique
    globally -- otherwise the handle names two tenants and login is ambiguous
    again, one level up."""
    session.add(Tenant(id=2, slug="default", name="impostor"))
    with pytest.raises(IntegrityError):
        session.commit()


# --- a user's email is unique per tenant, not globally -------------------

def test_two_tenants_can_hold_the_same_user_email(session):
    """The point of the composite constraint: an address is an identity *inside*
    a tenant. Two customers who both employ the same contractor can both give
    them an account, and the first tenant to claim an address no longer locks
    every other tenant out of it."""
    session.add(Tenant(id=2, slug="second", name="second"))
    session.commit()
    for tenant_id in (DEFAULT_TENANT_ID, 2):
        session.add(
            User(
                tenant_id=tenant_id,
                email="ops@contractor.com",
                role=UserRole.MEMBER,
                credential="x",
            )
        )
    session.commit()  # no IntegrityError

    rows = session.scalars(
        repo.select(User).where(User.email == "ops@contractor.com")
    ).all()
    assert sorted(u.tenant_id for u in rows) == [DEFAULT_TENANT_ID, 2]


def test_one_tenant_cannot_hold_the_same_email_twice(session):
    """Composite, not absent: within a tenant an address is still one account,
    which is what makes "the user with this email, in this tenant" a lookup that
    can return at most one row."""
    for _ in range(2):
        session.add(
            User(
                tenant_id=DEFAULT_TENANT_ID,
                email="dup@example.com",
                role=UserRole.MEMBER,
                credential="x",
            )
        )
    with pytest.raises(IntegrityError):
        session.commit()
