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
    NoTenantScope,
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


@pytest.mark.unscoped_tenant
def test_resolving_the_tenant_outside_a_scope_fails_closed():
    """Story 6's guarantee, at the seam that decides it (P5-11).

    This used to answer `DEFAULT_TENANT_ID`, and that is the opposite of what
    the spec asks for: a route that forgot its auth dependency, or background
    work that forgot to bind a scope, read *and wrote* the first customer's
    rows and looked like it was working. "A missing filter is a bug that fails
    closed rather than a leak" is only true if the thing every filter is built
    from refuses to guess.

    Opted out of the harness's autouse scope (P5-09): the claim *is* what the
    resolver does with nothing bound, so a test of it cannot run inside a
    binding.
    """
    with pytest.raises(NoTenantScope) as excinfo:
        current_tenant_id()

    # Naming the problem, not just failing: whoever hits this is looking at a
    # stack with no request and no run in it, and needs to be told what is
    # missing rather than left to infer it from a KeyError.
    message = str(excinfo.value)
    assert "tenant" in message.lower()
    assert "scope" in message.lower()


@pytest.mark.unscoped_tenant
def test_the_seeded_tenant_is_still_the_constant_the_migrations_use():
    """The constant does not go away with the fallback: the migrations seed it,
    the CLI defaults to it and the harness binds it. What goes away is the
    resolver *guessing* it."""
    assert DEFAULT_TENANT_ID == 1


@pytest.mark.unscoped_tenant
def test_current_tenant_id_resolves_from_an_active_scope():
    """P5's replacement: inside a scope (a request's authenticated user, or a
    run on the thread path) the resolver answers that tenant, not the constant.

    The call sites in repo.py do not change; this one function does."""
    with tenant_scope(42):
        assert current_tenant_id() == 42
    # and it stops resolving at all the moment the scope closes
    with pytest.raises(NoTenantScope):
        current_tenant_id()


@pytest.mark.unscoped_tenant
def test_tenant_scopes_nest_and_restore():
    with tenant_scope(7):
        assert current_tenant_id() == 7
        with tenant_scope(9):
            assert current_tenant_id() == 9
        assert current_tenant_id() == 7
    with pytest.raises(NoTenantScope):
        current_tenant_id()


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


@pytest.mark.unscoped_tenant
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

    with pytest.raises(NoTenantScope):  # outside the scope: nothing is acting
        current_tenant_id()
    with service.acting_as(scope):
        assert current_tenant_id() == 2
    with pytest.raises(NoTenantScope):  # and unbound again after
        current_tenant_id()


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


# --- the guard asks for a tenant only when one is at stake ---------------

@pytest.mark.unscoped_tenant
def test_reading_the_tenants_table_needs_no_scope(session):
    """`tenants` is not tenant-owned, so reading it is not an unscoped read.

    The guard resolves the tenant in order to build its filter, and resolving
    now raises -- so a guard that resolved for *every* ORM select would demand
    a scope from statements it then had nothing to filter. That is not
    hypothetical: `repo.list_tenant_ids` is how the reaper discovers which
    tenants to sweep, and it necessarily runs before any tenant is bound. A
    guard that failed there would take the whole maintenance loop down
    ("reaper pass failed; continuing", once every thirty seconds, forever)
    while looking like the fail-closed behaviour working as intended.

    So the tenant is resolved only when a tenant-owned entity is actually in
    the statement. `tenants` carries no `tenant_id` -- its own id *is* the
    tenant -- and needs no bypass for the same reason it needs no filter.
    """
    assert repo.list_tenant_ids(session) == [DEFAULT_TENANT_ID]


@pytest.mark.unscoped_tenant
def test_reading_a_tenant_owned_table_still_needs_one(session):
    """The other half, so the test above cannot be mistaken for the guard
    having gone quiet: a select of an owned entity outside a scope still
    fails."""
    with pytest.raises(NoTenantScope):
        list(session.scalars(repo.select(Project)))


def test_an_aggregate_over_an_owned_table_is_still_filtered(session):
    """The fail-closed direction of the guard's "is anything owned here?" check.

    `select(func.count()).select_from(Run)` reports **no** mappers at all, so a
    check written as "skip unless some mapper is tenant-owned" skips precisely
    the statements whose entities it cannot see -- and that shape is how
    `repo.tenant_usage` counts runs for the quota. The first version of that
    check let one tenant's runs count against another's cap.

    Asserted directly on an aggregate here, as well as through the quota in
    test_quotas.py, because the quota test says "the cap is wrong" where this
    one says why.
    """
    from sqlalchemy import func

    session.add(Tenant(id=2, slug="second", name="Second"))
    session.commit()

    with tenant_scope(2):
        project = repo.create_project(session, name="theirs")
        target = create_target(session, project.id, app="theirs", name="Theirs")
        repo.start_run(session, target_id=target.id, story_id="SCRUM-1", mode="full")

    # Counted from the harness's own tenant, which owns none of the above.
    counted = session.scalar(
        repo.select(func.count()).select_from(app.models.Run)
    )
    assert counted == 0, (
        f"an aggregate counted {counted} of another tenant's runs; the guard "
        f"skipped a statement whose mappers it could not read"
    )
