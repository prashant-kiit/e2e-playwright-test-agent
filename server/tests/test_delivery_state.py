""""Is this delivered?" is a Postgres query, and delivery is what answers it.

Invariant 5, finally met. Through P2 the question cost two network round trips
(`ls-remote` plus a worktree diff) and could answer differently depending on who
had moved what in the customer's repo. Now the head revision either carries a
`delivered_sha` or it is N revisions ahead of the newest one that does, and that
is the same answer for everyone whether or not GitHub is reachable.

`delivered_sha` is written by delivery and by nothing else.
"""

from __future__ import annotations

import pytest

from app import repo, revisions
from app.delivery.catalog import DbCatalog
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def catalog_env(session_factory, tmp_path):
    """One target with revision 1, and a catalog over the same database.

    Only `session_factory` is used, never `session` as well: both fixtures
    TRUNCATE on teardown, and one TRUNCATE waiting on the other's open
    connection is a deadlock rather than a test failure.
    """
    store = FakeStorage()
    with session_factory() as s:
        project = repo.create_project(s, name="demo")
        target = create_target(s, project.id, app="demo", name="Demo")
        revisions.commit_revision(
            s, target, store, make_worktree(tmp_path / "source"), author="operator"
        )
        target_id = target.id
    return DbCatalog(session_factory, store), target_id, store, session_factory


def _commit_another(session_factory, target_id, store, tmp_path, text):
    root = make_worktree(tmp_path / f"src-{abs(hash(text))}")
    (root / "tests" / "checkout" / "extra.spec.ts").write_text(text)
    with session_factory() as s:
        target = repo.get_target(s, target_id)
        return revisions.commit_revision(s, target, store, root, author="operator")


# --- the state query ------------------------------------------------------

def test_a_never_delivered_target_is_n_revisions_ahead_of_nothing(catalog_env):
    catalog, target_id, _store, sessions = catalog_env

    state = catalog.state("demo")

    assert state.rev == 1
    assert state.delivered is False
    assert state.delivered_sha is None
    assert state.revisions_ahead == 1
    assert state.ever_delivered is False


def test_recording_a_sha_makes_the_head_delivered(catalog_env):
    catalog, target_id, _store, sessions = catalog_env

    catalog.record_delivered("demo", "a" * 40)

    state = catalog.state("demo")
    assert state.delivered is True
    assert state.delivered_sha == "a" * 40
    assert state.revisions_ahead == 0


def test_a_further_revision_is_one_ahead_of_the_delivered_one(catalog_env, tmp_path):
    catalog, target_id, store, sessions = catalog_env
    catalog.record_delivered("demo", "a" * 40)
    _commit_another(sessions, target_id, store, tmp_path, "// one\n")

    state = catalog.state("demo")
    assert state.delivered is False
    assert state.revisions_ahead == 1
    assert state.ever_delivered is True, "it has been delivered before, just not this head"


def test_two_further_revisions_are_two_ahead(catalog_env, tmp_path):
    catalog, target_id, store, sessions = catalog_env
    catalog.record_delivered("demo", "a" * 40)
    _commit_another(sessions, target_id, store, tmp_path, "// one\n")
    _commit_another(sessions, target_id, store, tmp_path, "// two\n")

    assert catalog.state("demo").revisions_ahead == 2


def test_the_state_answers_without_a_network_call(catalog_env, monkeypatch):
    """The point of the query. Anything reaching for the network here fails."""
    import subprocess

    import httpx

    def no_network(*a, **kw):
        raise AssertionError("delivery state must not touch the network")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(subprocess, "run", no_network)
    monkeypatch.setattr(subprocess, "Popen", no_network)

    catalog, target_id, _store, sessions = catalog_env
    assert catalog.state("demo").rev == 1


def test_a_target_is_bootstrapped_iff_a_revision_carries_a_delivered_sha(catalog_env):
    """Derived the same way, so there is one definition of "we have pushed to
    this repo" rather than an `ls-remote` that can answer differently."""
    catalog, target_id, _store, sessions = catalog_env
    assert catalog.state("demo").ever_delivered is False

    catalog.record_delivered("demo", "b" * 40)

    assert catalog.state("demo").ever_delivered is True


def test_recording_writes_the_sha_on_the_head_revision_itself(catalog_env):
    catalog, target_id, _store, sessions = catalog_env

    catalog.record_delivered("demo", "c" * 40)

    with sessions() as s:
        assert revisions.head_revision(s, target_id).delivered_sha == "c" * 40


def test_an_unknown_target_is_an_error_not_an_empty_state(catalog_env):
    from app.delivery.errors import DeliveryError

    catalog, target_id, _store, sessions = catalog_env
    with pytest.raises(DeliveryError, match="ghost"):
        catalog.state("ghost")


# --- the materialized workspace -------------------------------------------

def test_the_catalog_materializes_the_head_revision(catalog_env):
    catalog, target_id, _store, sessions = catalog_env

    with catalog.materialize("demo") as workspace:
        assert (workspace / "seed.spec.ts").is_file()
        assert (workspace / "user-stories" / "SCRUM-1-checkout.md").is_file()
        assert revisions.scan_tracked_tree(workspace).tree_hash == (
            catalog.state("demo").tree_hash
        )


def test_the_workspace_is_removed_after_the_operation(catalog_env):
    """Created and removed per operation: what we push is a tree we built from
    the revision we are about to record, not a mount that outlives it."""
    catalog, target_id, _store, sessions = catalog_env

    with catalog.materialize("demo") as workspace:
        path = workspace
        assert path.is_dir()

    assert not path.exists()


def test_the_workspace_is_removed_even_when_the_operation_raises(catalog_env):
    catalog, target_id, _store, sessions = catalog_env

    path = None
    with pytest.raises(RuntimeError):
        with catalog.materialize("demo") as workspace:
            path = workspace
            raise RuntimeError("the push failed")

    assert path is not None and not path.exists()


def test_materializing_a_target_with_no_revision_is_an_error(session_factory):
    from app.delivery.errors import DeliveryError

    with session_factory() as s:
        project = repo.create_project(s, name="other")
        create_target(s, project.id, app="empty", name="Empty")
    catalog = DbCatalog(session_factory, FakeStorage())

    with pytest.raises(DeliveryError, match="no head revision"):
        with catalog.materialize("empty"):
            pass


# --- the target's configuration comes from the row -------------------------

def test_the_config_comes_from_the_targets_row(catalog_env):
    catalog, target_id, _store, sessions = catalog_env
    with sessions() as s:
        repo.update_target_config(
            s, target_id, target_repo="owner/moved", target_branch="trunk"
        )

    cfg = catalog.config("demo")
    assert cfg.target_repo == "owner/moved"
    assert cfg.target_branch == "trunk"


def test_the_config_of_an_unknown_target_is_an_error(catalog_env):
    from app.delivery.errors import DeliveryError

    catalog, target_id, _store, sessions = catalog_env
    with pytest.raises(DeliveryError, match="ghost"):
        catalog.config("ghost")
