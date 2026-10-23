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
from app.models import Revision, Tenant
from app.tenancy import DEFAULT_TENANT_ID, current_tenant_id


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
    """The one call site P5 replaces."""
    assert current_tenant_id() == DEFAULT_TENANT_ID == 1


def test_the_migration_seeds_exactly_one_tenant(session):
    tenants = list(session.scalars(repo.select(Tenant)))
    assert [t.id for t in tenants] == [DEFAULT_TENANT_ID]


def test_insert_paths_set_tenant_id_explicitly(session):
    """Not by relying on a database default -- there is none to rely on."""
    project = repo.create_project(session, name="demo")
    target = repo.create_target(session, project_id=project.id, app="a", name="A")
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
    target = repo.create_target(session, project_id=project.id, app="a", name="A")

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
    target = repo.create_target(session, project_id=project.id, app="a", name="A")
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
