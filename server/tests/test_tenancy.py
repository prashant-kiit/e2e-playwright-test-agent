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
from app.models import Project, Revision, Target, Tenant, User
from app.tenancy import (
    DEFAULT_TENANT_ID,
    across_tenants,
    current_tenant_id,
    tenant_scope,
)
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


def test_the_background_path_binds_the_runs_tenant_from_its_token(session):
    """The background equivalent of `require_auth`, as P5-05 left it.

    It used to be `launcher._run_tenant_scope`, which read the run across
    tenants in order to discover whose it was -- a chicken-and-egg that needed a
    hole in the read guard, and the reason `launcher` was on the bypass
    allowlist. The token carries the tenant now: it is minted by the control
    plane while the run's own tenant is acting, and every operation the run
    performs is bound to it by `service.acting_as`. So the run's inserts are
    still written as the run's tenant, and nothing on that path reads a row
    without a scope -- because nothing on that path reads a row at all.
    """
    from sqlalchemy.orm import sessionmaker

    from app.control import factory as control_factory
    from app.control import service
    from app.run_token import verify

    session.add(Tenant(id=2, slug="second", name="second"))
    session.commit()
    with tenant_scope(2):
        project = repo.create_project(session, name="t2")
        target = create_target(session, project.id, app="a2", name="A2")
        run = repo.start_run(session, target_id=target.id, story_id="SCRUM-1", mode="full")
    # A throwaway factory on the same engine, for the reason the deleted
    # `_run_tenant_scope` test used one: minting opens its own session, and a
    # session that already created the run would answer `session.get` from its
    # identity map without ever querying -- so the read guard would not run and
    # the test would prove nothing about it.
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False, future=True)
    with tenant_scope(2):
        # Minted inside the acting tenant's scope, exactly as the two production
        # call sites do it -- on a request thread, under `require_auth`.
        token = control_factory.mint_for_run(run.id, session_factory=factory)
    assert run.tenant_id == 2

    scope = verify(token)
    assert scope.tenant_id == 2
    assert scope.run_id == run.id
    assert scope.target_id == target.id

    assert current_tenant_id() == DEFAULT_TENANT_ID  # outside the scope
    with service.acting_as(scope):
        assert current_tenant_id() == 2
    assert current_tenant_id() == DEFAULT_TENANT_ID  # restored after


def test_a_token_cannot_be_minted_for_another_tenants_run(session):
    """Minting is a tenant-filtered read, which is why it needs no bypass.

    A control plane acting as tenant 1 cannot mint a token for tenant 2's run:
    the read simply does not find it. That is the property that let
    `_run_tenant_scope` -- and `launcher`'s entry in the bypass allowlist -- be
    deleted rather than replaced.
    """
    from sqlalchemy.orm import sessionmaker

    from app.control import factory as control_factory

    session.add(Tenant(id=2, slug="second", name="second"))
    session.commit()
    with tenant_scope(2):
        project = repo.create_project(session, name="t2")
        target = create_target(session, project.id, app="a2", name="A2")
        run = repo.start_run(session, target_id=target.id, story_id="SCRUM-1", mode="full")

    # A fresh session, so the read really goes to the database: see the note in
    # the test above about the identity map.
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False, future=True)

    with pytest.raises(repo.NotFound):
        control_factory.mint_for_run(run.id, session_factory=factory)


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

    # Read across tenants deliberately: the claim is about what the *database*
    # holds, and no tenant is allowed to see both of these rows. The enforced
    # read path (P5-02) would otherwise show this test only tenant 1's, which
    # is the filter working rather than the constraint failing.
    rows = session.scalars(
        across_tenants(repo.select(User).where(User.email == "ops@contractor.com"))
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


# --- a project name and an app slug are unique per tenant ---------------

def test_two_tenants_can_register_the_same_app_slug(session):
    """The constraint flip P5-02 exists for.

    `uq_targets_app` was global, so the first tenant to register `saucedemo`
    took the name from every other customer -- and the slug is not a label they
    chose freely: it is the app they are testing, so two customers testing the
    same public demo site, or the same vendor's product, collided by nature.
    The refusal would have arrived as a 409 on target creation with nothing the
    operator could do about it.
    """
    session.add(Tenant(id=2, slug="second", name="second"))
    session.commit()

    project_ids = {}
    for tenant_id in (DEFAULT_TENANT_ID, 2):
        with tenant_scope(tenant_id):
            project = repo.create_project(session, name="shared-name")
            project_ids[tenant_id] = project.id
            create_target(session, project.id, app="saucedemo", name="Sauce")

    # Both exist, each owned by its own tenant -- read across tenants because
    # by design no single tenant may see both.
    rows = session.scalars(
        across_tenants(repo.select(Target).where(Target.app == "saucedemo"))
    ).all()
    assert sorted(t.tenant_id for t in rows) == [DEFAULT_TENANT_ID, 2]
    assert len({t.project_id for t in rows}) == 2  # and under its own project


def test_two_tenants_can_use_the_same_project_name(session):
    """`projects.name` was globally unique for the same reason and with the
    same consequence: a customer naming a project "Checkout" denied the name to
    everyone else."""
    session.add(Tenant(id=2, slug="second", name="second"))
    session.commit()

    for tenant_id in (DEFAULT_TENANT_ID, 2):
        with tenant_scope(tenant_id):
            repo.create_project(session, name="Checkout")

    rows = session.scalars(
        across_tenants(repo.select(Project).where(Project.name == "Checkout"))
    ).all()
    assert sorted(p.tenant_id for p in rows) == [DEFAULT_TENANT_ID, 2]


def test_one_tenant_cannot_register_the_same_app_slug_twice(session):
    """Composite, not absent. Within a tenant the slug still identifies one
    target: it is what the target's revisions, blobs and delivered branch names
    are keyed on, so two targets sharing it inside one tenant would make those
    ambiguous."""
    project = repo.create_project(session, name="demo")
    create_target(session, project.id, app="saucedemo", name="Sauce")
    with pytest.raises(IntegrityError):
        create_target(session, project.id, app="saucedemo", name="Sauce again")
    session.rollback()


def test_one_tenant_cannot_use_the_same_project_name_twice(session):
    repo.create_project(session, name="Checkout")
    with pytest.raises(IntegrityError):
        repo.create_project(session, name="Checkout")
    session.rollback()
