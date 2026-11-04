"""Offboarding a tenant: rows, objects, and nothing else. P5-15 / #47.

Story 32, and the largest piece of #30 that was never built. This is the one
operation in the system with no undo and no backup behind it, so the tests are
weighted accordingly: the single most important one is
`test_nothing_of_the_other_tenant_is_touched`, driven with **two populated
tenants**, because a purge that took a neighbour's data with it is the failure
that cannot be apologised for.

The fixture populates every tenant-owned table it reasonably can, rather than
one or two, because the purge derives its table list from the mapped classes --
so a test that populated only `runs` would pass while leaving nine tables
untouched, and would go on passing when a tenth was added.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text

from app import accounts, audit, prompt_store, repo, revisions
from app.accounts import __main__ as cli
from app.accounts import purge as purge_mod
from app.domain import store_keys
from app.domain.audit import Action
from app.domain.roles import UserRole
from app.models import (
    AppLock,
    Artifact,
    AuditLog,
    Base,
    FileIndex,
    Project,
    Prompt,
    PurgeLog,
    Revision,
    Run,
    RunLog,
    RunStep,
    Target,
    TenantOwned,
    User,
)
from app.tenancy import actor_scope, tenant_scope
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target

OPERATOR = "ops@platform.example"


def _populate(session, store, tmp_path, *, slug, name, app_slug):
    """One tenant with something in every table a tenant can own."""
    created = accounts.create_tenant(
        session, name=name, slug=slug, admin_email=f"boss@{slug}.example"
    )
    tenant_id = created.user.tenant_id
    with tenant_scope(tenant_id), actor_scope(f"boss@{slug}.example"):
        # A second user, so `users` has more than the admin.
        accounts.add_user(session, email=f"dev@{slug}.example", role=UserRole.MEMBER)
        project = repo.create_project(session, name=f"{slug}-project")
        target = create_target(session, project.id, app=app_slug, name=name)
        # A revision and its file index, plus the blobs behind them.
        revisions.commit_revision(
            session, target, store, make_worktree(tmp_path / f"src-{slug}"), author="op"
        )
        run = repo.start_run(
            session, target_id=target.id, story_id="SCRUM-1", mode="full"
        )
        repo.begin_run(session, run.id)
        repo.start_step(session, run.id, __import__(
            "app.domain.steps", fromlist=["Step"]
        ).Step.READ_STORY)
        # An artifact, under the tenant prefix (#42) so the sweep can find it.
        blob = tmp_path / f"artifact-{slug}"
        blob.write_bytes(b"evidence")
        key = store_keys.artifact_key(tenant_id, run.run_key, "trace.zip")
        store.put_file(key, blob)
        session.add(
            Artifact(
                tenant_id=tenant_id,
                run_id=run.id,
                step=None,
                kind="other",
                s3_key=key,
                sha256="abc",
                version=1,
            )
        )
        # A log line, a prompt override and an audit row.
        session.add(
            RunLog(tenant_id=tenant_id, run_id=run.id, seq=1, line="hello")
        )
        prompt_store.save_override(
            session, "steps/2-plan.md", f"Plan it the {slug} way.\n"
        )
        audit.record(
            session,
            action=Action.TARGET_RESET,
            target=f"target:{target.id}",
            after={"slug": slug},
        )
        session.commit()
    return tenant_id, run


@pytest.fixture()
def two_tenants(session, tmp_path):
    """Two customers, both populated. Neither is the seeded default tenant,
    so the seeded admin -- which conftest cannot restore -- is never at risk.
    """
    store = FakeStorage()
    doomed, doomed_run = _populate(
        session, store, tmp_path, slug="doomed", name="Doomed Ltd", app_slug="doomed-app"
    )
    keeper, keeper_run = _populate(
        session, store, tmp_path, slug="keeper", name="Keeper Ltd", app_slug="keeper-app"
    )
    return store, (doomed, doomed_run), (keeper, keeper_run)


def _owned_counts(session, tenant_id):
    """How many rows this tenant has, per tenant-owned table."""
    counts = {}
    with tenant_scope(tenant_id):
        for mapper in Base.registry.mappers:
            model = mapper.class_
            if issubclass(model, TenantOwned):
                counts[model.__tablename__] = session.scalar(
                    select(func.count()).select_from(model)
                )
    return counts


def _borrowed(session):
    class _B:
        def __enter__(self_inner):
            return session

        def __exit__(self_inner, *exc):
            return False

    return lambda: _B()


# --- the fixture is worth asserting, or the rest proves nothing ----------

def test_the_fixture_really_populates_every_tenant_owned_table(two_tenants, session):
    """If this starts failing because a table was added, the purge tests have
    stopped covering it -- which is the whole reason the purge derives its
    table list from the mappers rather than from a literal."""
    _store, (doomed, _r), _keeper = two_tenants

    counts = _owned_counts(session, doomed)

    empty = [table for table, count in counts.items() if not count]
    assert empty == [], f"nothing in {empty}; the purge tests do not cover them"


# --- the purge -----------------------------------------------------------

def test_a_purge_removes_every_row_and_every_object(two_tenants, session):
    store, (doomed, _run), _keeper = two_tenants

    with actor_scope(OPERATOR):
        report = purge_mod.purge_tenant(
            session, store, slug="doomed", confirm_slug="doomed"
        )

    assert report.objects > 0
    assert report.total_rows > 0
    assert all(count == 0 for count in _owned_counts(session, doomed).values())
    assert list(store.list_keys(store_keys.tenant_prefix(doomed))) == []
    # And the tenant itself is gone, which is what makes the slug reusable.
    assert repo.select is not None
    assert session.scalars(
        select(purge_mod.Tenant).where(purge_mod.Tenant.slug == "doomed")
    ).one_or_none() is None


def test_nothing_of_the_other_tenant_is_touched(two_tenants, session):
    """The test that matters most, and the reason the fixture builds two
    populated tenants rather than one. A purge that took a neighbour's rows
    or objects with it is the failure with no apology available."""
    store, (_doomed, _dr), (keeper, _kr) = two_tenants
    before_rows = _owned_counts(session, keeper)
    before_objects = set(store.list_keys(store_keys.tenant_prefix(keeper)))
    assert before_objects, "the keeper has objects to lose"

    with actor_scope(OPERATOR):
        purge_mod.purge_tenant(session, store, slug="doomed", confirm_slug="doomed")

    assert _owned_counts(session, keeper) == before_rows
    assert set(store.list_keys(store_keys.tenant_prefix(keeper))) == before_objects
    # The keeper's own admin can still be found, so `users` survived too.
    with tenant_scope(keeper):
        assert {u.email for u in accounts.list_users(session)} == {
            "boss@keeper.example",
            "dev@keeper.example",
        }


def test_a_tenant_whose_id_is_a_prefix_of_anothers_is_safe(session, tmp_path):
    """`tenant/1` is a prefix of `tenant/11`, and S3's `Prefix` is a byte
    comparison rather than a path walk. The separator in
    `store_keys.tenant_prefix` is what stops a purge of the first taking the
    second's objects; this drives it with keys shaped exactly that way."""
    store = FakeStorage()
    blob = tmp_path / "o"
    blob.write_bytes(b"x")
    low, high = 1, 11
    store.put_file(store_keys.blob_key(low, "a" * 64), blob)
    keep = store_keys.blob_key(high, "b" * 64)
    store.put_file(keep, blob)

    removed = purge_mod._sweep_storage(store, low)

    assert removed == 1
    assert keep in store.objects


# --- idempotence ---------------------------------------------------------

def test_a_purge_interrupted_before_the_tenant_row_is_finished_by_a_re_run(
    two_tenants, session
):
    """The reason the `tenants` row goes last. Everything else is already
    gone, the slug still resolves, and the same command completes."""
    store, (doomed, _run), _keeper = two_tenants
    with actor_scope(OPERATOR):
        # Exactly the state an interruption after step 3 leaves.
        purge_mod._sweep_storage(store, doomed)
        with tenant_scope(doomed):
            for table in purge_mod._owned_tables():
                purge_mod._delete_table(session, table)
            session.commit()

        report = purge_mod.purge_tenant(
            session, store, slug="doomed", confirm_slug="doomed"
        )

    assert report.objects == 0, "nothing left to sweep"
    assert report.total_rows == 0, "nothing left to delete"
    assert session.scalars(
        select(purge_mod.Tenant).where(purge_mod.Tenant.slug == "doomed")
    ).one_or_none() is None
    # And it still recorded the completion, which is what the re-run is for.
    assert [row.slug for row in purge_mod.purged(session)] == ["doomed"]


def test_purging_a_slug_that_is_already_gone_says_so_rather_than_half_running(
    two_tenants, session
):
    """A finished purge leaves no tenant row, so this is how "already done"
    presents. Refused before anything is deleted, so a mistyped slug cannot
    sweep a prefix on its way to failing."""
    store, (_doomed, _run), _keeper = two_tenants
    with actor_scope(OPERATOR):
        purge_mod.purge_tenant(session, store, slug="doomed", confirm_slug="doomed")

        with pytest.raises(purge_mod.PurgeError, match="no tenant with slug"):
            purge_mod.purge_tenant(
                session, store, slug="doomed", confirm_slug="doomed"
            )


# --- the gate ------------------------------------------------------------

def test_a_mismatched_confirmation_refuses_and_deletes_nothing(two_tenants, session):
    """Naming the tenant twice rather than a `--yes`: a flag can be pasted
    into any invocation, while a second spelling cannot be confirmed for the
    wrong tenant by accident."""
    store, (doomed, _run), _keeper = two_tenants
    before = _owned_counts(session, doomed)

    with pytest.raises(purge_mod.PurgeError, match="confirmation named"):
        purge_mod.purge_tenant(session, store, slug="doomed", confirm_slug="keeper")

    assert _owned_counts(session, doomed) == before
    assert list(store.list_keys(store_keys.tenant_prefix(doomed))), "objects intact"


# --- the audit log is the one permitted exception ------------------------

def test_the_purge_removes_the_audit_rows_it_is_allowed_to(two_tenants, session):
    store, (doomed, _run), _keeper = two_tenants
    with tenant_scope(doomed):
        assert audit.entries(session), "there is a trail to remove"

    with actor_scope(OPERATOR):
        purge_mod.purge_tenant(session, store, slug="doomed", confirm_slug="doomed")

    with tenant_scope(doomed):
        assert audit.entries(session) == []


def test_the_append_only_trigger_is_back_on_afterwards(two_tenants, session):
    """The exception is for one statement, not for the rest of the session.
    A purge that left the trigger disabled would quietly remove the guarantee
    story 28 is about -- and nothing else in the system would notice."""
    store, (_doomed, _run), (keeper, _kr) = two_tenants

    with actor_scope(OPERATOR):
        purge_mod.purge_tenant(session, store, slug="doomed", confirm_slug="doomed")

    with tenant_scope(keeper):
        row = audit.entries(session)[0]
        with pytest.raises(Exception, match="append-only|immutable|audit"):
            session.execute(
                text("DELETE FROM audit_log WHERE id = :id").bindparams(id=row.id)
            )
            session.flush()
    session.rollback()


# --- the record that survives it -----------------------------------------

def test_the_purge_records_what_it_did_somewhere_that_survives_it(
    two_tenants, session
):
    """`purge_log` is deliberately not tenant-owned: a record belonging to the
    purged tenant would be deleted by the thing it records."""
    store, (doomed, _run), _keeper = two_tenants

    with actor_scope(OPERATOR):
        report = purge_mod.purge_tenant(
            session, store, slug="doomed", confirm_slug="doomed"
        )

    (logged,) = purge_mod.purged(session)
    assert logged.purged_tenant_id == doomed
    assert logged.slug == "doomed"
    assert logged.name == "Doomed Ltd"
    assert logged.actor == OPERATOR, "who offboarded them, not `system`"
    assert logged.removed["objects"] == report.objects
    assert logged.removed["runs"] == 1
    # The row is outside every tenant, so it is not reachable through the
    # guard at all -- which is what "survives it" means.
    assert not issubclass(PurgeLog, TenantOwned)


# --- the command ---------------------------------------------------------

def test_the_command_purges_and_prints_what_it_removed(two_tenants, session, capsys):
    store, (doomed, _run), _keeper = two_tenants

    with actor_scope(OPERATOR):
        code = cli.main(
            ["purge-tenant", "--slug", "doomed", "--confirm-slug", "doomed"],
            store=store,
            session_factory=_borrowed(session),
        )

    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "doomed" in out
    assert "object(s)" in out and "row(s)" in out
    assert all(count == 0 for count in _owned_counts(session, doomed).values())


def test_the_command_refuses_a_mismatched_confirmation(two_tenants, session, capsys):
    store, (doomed, _run), _keeper = two_tenants

    code = cli.main(
        ["purge-tenant", "--slug", "doomed", "--confirm-slug", "typo"],
        store=store,
        session_factory=_borrowed(session),
    )

    assert code == cli.EXIT_ERROR
    assert "confirmation named" in capsys.readouterr().err
    assert _owned_counts(session, doomed)["runs"] == 1


def test_the_command_requires_both_slugs():
    """argparse refuses the invocation rather than the function refusing the
    arguments, so "I forgot the confirmation" never reaches the purge."""
    with pytest.raises(SystemExit):
        cli.main(["purge-tenant", "--slug", "doomed"])


# --- the tables are derived, not listed ----------------------------------

def test_the_table_list_is_every_tenant_owned_table_in_a_safe_order(two_tenants):
    """Derived from the mappers so a table added later is purged without
    anybody remembering this file -- the argument `install_tenant_guard` makes
    for the read filter, applied to the delete."""
    tables = purge_mod._owned_tables()

    expected = {
        model.__tablename__
        for model in (
            User,
            Project,
            Target,
            Run,
            RunStep,
            Artifact,
            RunLog,
            AppLock,
            Revision,
            FileIndex,
            Prompt,
            AuditLog,
        )
    }
    assert set(tables) == expected
    # Children before parents: every `tenant_id` FK is ondelete=RESTRICT, so a
    # parent deleted first would be refused by its own children.
    assert tables.index("runs") < tables.index("targets")
    assert tables.index("run_steps") < tables.index("runs")
    assert tables.index("targets") < tables.index("projects")
    assert tables.index("file_index") < tables.index("revisions")
