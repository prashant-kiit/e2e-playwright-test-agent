"""The cutover: snapshot every target, gate on parity, import its app.json.

One command, run once with the mount still present. Parity's last act is to gate
its own removal: a target whose head revision disagrees with the files on disk
is exactly the target whose configuration we must not trust, so the command
refuses and names it.

Re-running is a **no-op, not an error** -- a snapshot of an unchanged tree
commits nothing and the config import is idempotent -- because the operator who
is unsure whether it ran should be able to just run it again.
"""

from __future__ import annotations

import json

import pytest

from app import cutover, monorepo, repo, revisions
from app.models import FileIndex
from tests.delivery_helpers import make_workspace
from tests.storage_helpers import FakeStorage
from tests.target_helpers import backfilled_target


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    ws = make_workspace(tmp_path / "workspace", app="demo")
    monkeypatch.setenv("QA_REPO_ROOT", str(ws))
    return ws


@pytest.fixture()
def target(session, workspace):
    project = repo.create_project(session, name="demo")
    # Exactly as the migration's backfill leaves it: no real configuration.
    return backfilled_target(session, project.id, app="demo")


def test_the_cutover_imports_every_targets_app_json_into_its_row(session, target):
    result = cutover.run_cutover(session, FakeStorage())

    session.expire_all()
    stored = repo.get_target(session, target.id)
    assert stored.base_url == "https://demo.example.com"
    assert stored.target_repo == "o/r"
    assert stored.target_branch == "master"
    assert stored.locators == "data-testid"
    assert stored.agent_notes == []
    assert [o.app for o in result.targets] == ["demo"]
    assert result.targets[0].imported is True


def test_the_cutover_snapshots_each_targets_tracked_tree(session, target):
    """The P2 path, unchanged: a target with no history gets revision 1."""
    result = cutover.run_cutover(session, FakeStorage())

    head = revisions.head_revision(session, target.id)
    assert head is not None and head.rev == 1
    assert result.targets[0].rev == 1
    assert result.targets[0].committed is True


def test_re_running_the_cutover_commits_no_revision_and_changes_no_row(session, target):
    store = FakeStorage()
    cutover.run_cutover(session, store)
    session.expire_all()
    first = repo.get_target(session, target.id)
    before = (first.base_url, first.target_repo, first.agent_notes)

    again = cutover.run_cutover(session, store)

    session.expire_all()
    after_target = repo.get_target(session, target.id)
    assert (after_target.base_url, after_target.target_repo, after_target.agent_notes) == before
    assert [r.rev for r, _ in revisions.list_revisions_with_file_counts(session, target.id)] == [1]
    assert again.targets[0].committed is False
    assert again.targets[0].imported is False


def test_a_target_whose_parity_is_red_blocks_the_cutover_and_is_named(
    session, target, workspace
):
    """The head's file index disagrees with the disk, so what app.json says
    about this target is not something to import."""
    store = FakeStorage()
    cutover.run_cutover(session, store)

    # Tamper with one file_index row: the tree hash still matches, so the
    # snapshot commits nothing and parity is the only thing that notices.
    head = revisions.head_revision(session, target.id)
    row = session.get(FileIndex, {"revision_id": head.id, "path": "seed.spec.ts"})
    row.blob_key = revisions.blob_key(row.tenant_id, "0" * 64)
    session.commit()

    with pytest.raises(cutover.ParityNotGreen) as exc:
        cutover.run_cutover(session, store)
    assert "demo" in str(exc.value)


def test_a_red_target_is_not_imported(session, target, workspace):
    """The gate refuses *before* writing the row, so a blocked cutover leaves
    the configuration exactly as it was."""
    store = FakeStorage()
    with monorepo.staged_tree(target.app) as root:
        revisions.commit_revision(session, target, store, root, author="operator")
    head = revisions.head_revision(session, target.id)
    row = session.get(FileIndex, {"revision_id": head.id, "path": "seed.spec.ts"})
    row.blob_key = revisions.blob_key(row.tenant_id, "0" * 64)
    session.commit()

    with pytest.raises(cutover.ParityNotGreen):
        cutover.run_cutover(session, store)

    session.expire_all()
    assert repo.get_target(session, target.id).base_url == ""


def test_the_command_verifies_its_own_result(session, target, workspace):
    """"Every target has a head revision and a complete config row" is asserted
    by the command, not left for a human to read out of its output."""
    (workspace / "apps" / "demo" / "app.json").write_text(
        json.dumps({"name": "Demo", "baseURL": "", "targetRepo": "o/r"}) + "\n"
    )

    with pytest.raises(cutover.CutoverIncomplete) as exc:
        cutover.run_cutover(session, FakeStorage())
    assert "demo" in str(exc.value)


def test_a_target_with_no_app_json_on_disk_blocks_the_cutover(session, workspace):
    project = repo.create_project(session, name="other")
    backfilled_target(session, project.id, app="ghost")

    with pytest.raises(cutover.CutoverError) as exc:
        cutover.run_cutover(session, FakeStorage())
    assert "ghost" in str(exc.value)
