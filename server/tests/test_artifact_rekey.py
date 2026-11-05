"""Moving existing artifact objects under the tenant prefix (P5-10 / #42).

The contract half of expand-then-contract, and the half with no undo: it
rewrites keys and deletes objects. So the properties asserted here are the ones
an operator actually relies on -- that a legacy object still downloads before
the pass, that the pass is re-runnable, that it is safe to interrupt at either
of its two interesting moments, and that it never deletes bytes a row still
points at.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app import repo, revisions
from app.artifacts import __main__ as cli
from app.artifacts import rekey as rekey_mod
from app.domain import store_keys
from app.models import Artifact, Tenant
from app.tenancy import DEFAULT_TENANT_ID, tenant_scope
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def legacy(session, tmp_path):
    """A run with two artifacts stored the **old** way.

    Written through `store_keys.legacy_artifact_key` rather than by hand, so
    the one place that still knows the old shape is the one place that admits
    to knowing it.
    """
    store = FakeStorage()
    blob = tmp_path / "object"
    blob.write_bytes(b"evidence")
    # Start from an empty artifacts table rather than assuming one. conftest
    # truncates at *teardown*, so the first test of a session sees whatever a
    # previous one left in `qa_test` -- and a dev database here holds rows from
    # real runs. These tests count rows, so running them first must not mean
    # counting somebody else's: that is the "passes in a full suite, fails
    # alone" shape #50 was about, with the order reversed.
    session.execute(text("DELETE FROM artifacts"))
    session.commit()
    with tenant_scope(DEFAULT_TENANT_ID):
        project = repo.create_project(session, name="demo")
        target = create_target(session, project.id, app="demo", name="Demo")
        revisions.commit_revision(
            session, target, store, make_worktree(tmp_path / "source"), author="op"
        )
        run = repo.start_run(
            session, target_id=target.id, story_id="SCRUM-1", mode="full"
        )
        rows = []
        for rel in ("trace.zip", "report/index.html"):
            key = store_keys.legacy_artifact_key(run.run_key, rel)
            store.put_file(key, blob)
            row = Artifact(
                tenant_id=DEFAULT_TENANT_ID,
                run_id=run.id,
                step=None,
                kind="other",
                s3_key=key,
                sha256="deadbeef",
                version=1,
            )
            session.add(row)
            rows.append(row)
        session.commit()
    return store, run, rows


def _keys(session):
    return {row.s3_key for row in session.scalars(repo.select(Artifact)).all()}


# --- the pass ------------------------------------------------------------

def test_a_pass_moves_the_bytes_and_the_rows_together(legacy, session):
    store, run, _rows = legacy

    with tenant_scope(DEFAULT_TENANT_ID):
        outcome = rekey_mod.rekey_tenant(session, store)

    assert outcome.moved == 2
    expected = {
        store_keys.artifact_key(DEFAULT_TENANT_ID, run.run_key, rel)
        for rel in ("trace.zip", "report/index.html")
    }
    assert expected <= set(store.objects), "the bytes are under the new keys"
    with tenant_scope(DEFAULT_TENANT_ID):
        assert expected <= _keys(session), "and so are the rows"
    # The old objects are gone, which is the point: a key space nobody can
    # enumerate per tenant is what the ticket is about.
    assert not [k for k in store.objects if not k.startswith("tenant/")]
    # The content came across byte for byte.
    for key in expected:
        assert store.objects[key][0] == b"evidence"


def test_after_the_pass_every_object_is_under_the_tenants_one_prefix(legacy, session):
    """The acceptance criterion, asserted the way story 32 will ask it: by
    listing one prefix and finding everything."""
    store, _run, _rows = legacy

    with tenant_scope(DEFAULT_TENANT_ID):
        rekey_mod.rekey_tenant(session, store)

    listed = set(store.list_keys(store_keys.tenant_prefix(DEFAULT_TENANT_ID)))
    assert listed == set(store.objects), "nothing of this tenant's sits outside"


def test_a_second_pass_moves_nothing_and_says_so(legacy, session):
    """Re-runnable, which is the same requirement as interruptible."""
    store, _run, _rows = legacy
    with tenant_scope(DEFAULT_TENANT_ID):
        rekey_mod.rekey_tenant(session, store)
        after = dict(store.objects)

        again = rekey_mod.rekey_tenant(session, store)

    assert (again.moved, again.already, again.failed) == (0, 2, 0)
    assert store.objects == after, "a second pass is a no-op, not a re-copy"


def test_an_interruption_after_the_copy_is_finished_by_the_next_pass(legacy, session):
    """The first of the two interesting moments: bytes copied, row not yet
    updated. The next pass must notice the object is already there and move
    the row rather than copying again."""
    store, run, _rows = legacy
    new_key = store_keys.artifact_key(DEFAULT_TENANT_ID, run.run_key, "trace.zip")
    old_key = store_keys.legacy_artifact_key(run.run_key, "trace.zip")
    # Exactly the state step 1 leaves: the new object exists, the row does not
    # know, and the old object is still there.
    store.objects[new_key] = store.objects[old_key]

    with tenant_scope(DEFAULT_TENANT_ID):
        outcome = rekey_mod.rekey_tenant(session, store)
        assert new_key in _keys(session)

    assert outcome.moved == 2
    assert old_key not in store.objects


def test_an_interruption_after_the_row_leaves_an_orphan_and_nothing_broken(
    legacy, session
):
    """The second moment: row updated, old object not yet deleted. The next
    pass skips the row entirely -- it is already migrated -- which leaves one
    unreferenced old object behind. That is deliberate and harmless: nothing
    points at it, and the row resolves."""
    store, run, rows = legacy
    old_key = store_keys.legacy_artifact_key(run.run_key, "trace.zip")
    new_key = store_keys.artifact_key(DEFAULT_TENANT_ID, run.run_key, "trace.zip")
    with tenant_scope(DEFAULT_TENANT_ID):
        store.objects[new_key] = store.objects[old_key]
        rows[0].s3_key = new_key
        session.commit()

        outcome = rekey_mod.rekey_tenant(session, store)

    assert (outcome.moved, outcome.already) == (1, 1)
    assert store.objects[new_key][0] == b"evidence", "the row still resolves"
    assert old_key in store.objects, "the orphan is left rather than guessed at"


def test_a_row_whose_bytes_are_missing_is_left_alone_and_counted(legacy, session):
    """"Blob before row" means this should never happen, so the pass reports
    it rather than papering over it: re-keying such a row would move the
    inconsistency instead of fixing it, and would delete nothing while
    claiming a move."""
    store, run, _rows = legacy
    old_key = store_keys.legacy_artifact_key(run.run_key, "trace.zip")
    del store.objects[old_key]

    with tenant_scope(DEFAULT_TENANT_ID):
        outcome = rekey_mod.rekey_tenant(session, store)
        assert old_key in _keys(session), "the row is untouched"

    assert (outcome.moved, outcome.missing, outcome.failed) == (1, 1, 0)


# --- every tenant, each in its own scope ---------------------------------

def test_the_pass_covers_every_tenant_rather_than_the_default_one(
    legacy, session, session_factory
):
    """The failure this shape prevents: a maintenance pass with no request
    behind it resolves to the seeded tenant, so one that simply queried would
    migrate tenant 1 and report a clean run while leaving every other
    customer's objects outside their prefix -- the same trap
    `reaper._for_each_tenant` exists for.
    """
    store, _run, _rows = legacy
    other = Tenant(name="Second", slug="second")
    session.add(other)
    session.commit()
    session.refresh(other)
    blob_path = None
    with tenant_scope(other.id):
        project = repo.create_project(session, name="theirs")
        target = create_target(session, project.id, app="theirs", name="Theirs")
        run = repo.start_run(
            session, target_id=target.id, story_id="SCRUM-9", mode="full"
        )
        their_old = store_keys.legacy_artifact_key(run.run_key, "trace.zip")
        import tempfile
        from pathlib import Path

        blob_path = Path(tempfile.mkdtemp()) / "o"
        blob_path.write_bytes(b"theirs")
        store.put_file(their_old, blob_path)
        session.add(
            Artifact(
                tenant_id=other.id,
                run_id=run.id,
                step=None,
                kind="other",
                s3_key=their_old,
                sha256="cafe",
                version=1,
            )
        )
        session.commit()
        their_new = store_keys.artifact_key(other.id, run.run_key, "trace.zip")

    rekey_mod.rekey_all(store, session_factory=lambda: _Borrowed(session))

    assert their_new in store.objects, "the second tenant's object moved too"
    assert not [k for k in store.objects if not k.startswith("tenant/")]


class _Borrowed:
    """Lends one session without closing it. See tests/control_helpers.py."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


# --- the command ---------------------------------------------------------

def test_the_command_reports_what_it_did_and_exits_zero(
    legacy, session, borrowed, capsys
):
    store, _run, _rows = legacy

    code = cli.main(
        ["rekey"], store=_StoreFor(store, session), session_factory=borrowed
    )

    assert code == cli.EXIT_OK
    assert "moved 2" in capsys.readouterr().out


def test_the_command_exits_nonzero_when_a_row_could_not_be_moved(
    legacy, session, borrowed, capsys
):
    """An operator scripting this needs the exit code to mean something, and
    "some rows are still outside the prefix" is not a success -- the purge
    that follows would miss them."""
    store, _run, _rows = legacy

    class Refuses(_StoreFor):
        def put_file(self, key, path, content_type=None):
            raise OSError("store is down")

    code = cli.main(
        ["rekey"], store=Refuses(store, session), session_factory=borrowed
    )

    assert code == cli.EXIT_ERROR
    assert "could not be moved" in capsys.readouterr().err


class _StoreFor(FakeStorage):
    """The fixture's store, with the command's session factory pinned to the
    test's session so `rekey_all` reaches the fixtures' rows."""

    def __init__(self, store, session):
        super().__init__()
        self.objects = store.objects
        self._session = session

    def __enter__(self):  # pragma: no cover - not used as a context manager
        raise AssertionError


@pytest.fixture()
def borrowed(session):
    """The session factory these tests inject.

    Injected rather than patched: `rekey_all` and the command both take one,
    and the suite's `_no_dev_database` guard is what refuses the default --
    which is the behaviour `test_the_pass_cannot_reach_the_developers_database`
    pins.
    """
    return lambda: _Borrowed(session)


def test_the_pass_cannot_reach_the_developers_database():
    """The seam is blocked, and this proves the block reaches *this* module.

    `_no_dev_database` in conftest patches `app.db.SessionLocal`, so a module
    that did `from ..db import SessionLocal` and used the bare name would
    bypass the guard entirely and open a session on the dev database. That is
    not hypothetical here: this function captured the factory as a default
    argument at first, the test's monkeypatch had no effect, and the pass
    connected to the dev `qa` database and read 25 artifact rows from a real
    October run. It wrote nothing only because the fake store held none of
    those objects.
    """
    with pytest.raises(AssertionError, match="developer's database"):
        rekey_mod.rekey_all(FakeStorage())


# --- expand then contract: the old shape still reads ---------------------

def test_a_legacy_artifact_still_downloads_before_the_pass(legacy, session):
    """The expand half, and the reason the pass can be taken at leisure.

    An artifact is downloaded by the `s3_key` on its own row, not by a key
    rebuilt from parts, so an object written under the old shape resolves
    unchanged. If this were not true, deploying P5-10 would have broken every
    existing artifact until the migration ran -- which is exactly the outage
    an Alembic-only re-key would have caused.
    """
    store, run, rows = legacy

    chunks, _ct = store.get_stream(rows[0].s3_key)

    assert b"".join(chunks) == b"evidence"
    assert not rows[0].s3_key.startswith("tenant/"), "this is the old shape"


def test_the_old_shape_is_written_nowhere_in_the_application():
    """The contract half, asserted structurally because it is a claim about
    *absence* and no behavioural test can make it.

    `store_keys.legacy_artifact_key` is the only thing in the tree that builds
    the old shape, and its callers are the rekey command (which migrates away
    from it) and these tests (which prove it still reads). An application
    module that called it would be writing the shape this ticket removed.
    """
    import pathlib

    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = [
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*.py")
        if "legacy_artifact_key" in path.read_text()
    ]
    assert offenders == ["domain/store_keys.py"], offenders
