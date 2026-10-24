"""Hydrate: a revision plus a target row become a worktree, and then nothing.

**The round-trip property replaces parity.** Parity compared two copies of the
truth; with one copy left, the equivalent check is by construction -- materialize
a revision, re-scan the result, and the tree hash must be the one that was
committed. It is the most valuable test in the phase, and it is a property over
the real functions: real `commit_revision`, real `materialize`, real scan, with
only the blob store faked.

Hydrate is three named parts so P4 can replace them one at a time, and each is
tested for what a caller can observe: the paths in the worktree, the bytes in
them, and whether a step ever got to run.
"""

from __future__ import annotations

import os

import pytest

from app import repo, revisions
from app.delivery import render
from app.sandbox import hydrate as hyd
from app.target_config import config_of
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def target(session):
    project = repo.create_project(session, name="demo")
    return create_target(session, project.id, app="demo", name="Demo")


def _commit(session, target, store, root):
    return revisions.commit_revision(session, target, store, root, author="operator")


# --- the round-trip property ---------------------------------------------
#
# Over generated trees rather than one fixture: the property is about the tree
# hash encoding and the materialize/scan pair, so it must hold for empty files,
# deep nesting, unicode, bytes that are not text, and a tree with nothing in it
# but infra.

def _tree_shapes() -> list[dict[str, bytes]]:
    return [
        {},
        {"seed.spec.ts": b""},
        {"seed.spec.ts": b"// seed\n", "tests/a/one.spec.ts": b"// one\n"},
        {
            "seed.spec.ts": b"// seed\n",
            "user-stories/SCRUM-9-x.md": "# été — café\n".encode(),
            "specs/SCRUM-9-x-test-plan.md": b"# plan\n",
            "tests/x/a.spec.ts": b"\x00\x01\x02 not text \xff\xfe",
            "tests/x/deep/er/still/b.spec.ts": b"// deep\n",
        },
        {f"tests/many/t{i}.spec.ts": f"// {i}\n".encode() for i in range(25)},
    ]


@pytest.mark.parametrize("shape", _tree_shapes(), ids=lambda s: f"{len(s)}-files")
def test_commit_then_materialize_then_rescan_reproduces_the_tree_hash(
    session, target, tmp_path, shape
):
    """The property parity used to check by comparison, checked by construction."""
    source = tmp_path / "source"
    for rel, data in shape.items():
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    source.mkdir(parents=True, exist_ok=True)
    store = FakeStorage()

    committed = _commit(session, target, store, source)
    assert committed is not None, "an unseen tree always commits"

    dest = tmp_path / "dest"
    hyd.materialize(session, committed, store, dest)

    assert revisions.scan_tracked_tree(dest).tree_hash == committed.tree_hash


def test_materialize_writes_exactly_the_revisions_paths_and_nothing_else(
    session, target, tmp_path
):
    store = FakeStorage()
    committed = _commit(session, target, store, make_worktree(tmp_path / "source"))

    dest = tmp_path / "dest"
    hyd.materialize(session, committed, store, dest)

    on_disk = {
        p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()
    }
    in_revision = {row.path for row in revisions.list_files(session, committed.id)}
    assert on_disk == in_revision


def test_materialize_reproduces_the_bytes_exactly(session, target, tmp_path):
    source = make_worktree(tmp_path / "source")
    (source / "tests" / "checkout" / "binary.spec.ts").write_bytes(b"\x00\xff\xfe\n")
    store = FakeStorage()
    committed = _commit(session, target, store, source)

    dest = tmp_path / "dest"
    hyd.materialize(session, committed, store, dest)

    for path, on_disk in render.tracked_tree(source):
        assert (dest / path).read_bytes() == on_disk.read_bytes(), path


# --- a blob that is missing or does not match its key ---------------------

def test_a_missing_blob_fails_the_hydrate(session, target, tmp_path):
    store = FakeStorage()
    committed = _commit(session, target, store, make_worktree(tmp_path / "source"))
    store.objects.clear()

    with pytest.raises(hyd.HydrateError, match="blob"):
        hyd.materialize(session, committed, store, tmp_path / "dest")


def test_a_blob_whose_bytes_do_not_match_its_key_fails_the_hydrate(
    session, target, tmp_path
):
    """The blob key *is* the content hash, so every file is verified as it is
    written. A store that hands back the wrong bytes is caught here rather than
    becoming a worktree the agent then works in."""
    store = FakeStorage()
    committed = _commit(session, target, store, make_worktree(tmp_path / "source"))
    row = revisions.list_files(session, committed.id)[0]
    _bytes, ct = store.objects[row.blob_key]
    store.objects[row.blob_key] = (b"tampered", ct)

    with pytest.raises(hyd.HydrateError, match="does not match"):
        hyd.materialize(session, committed, store, tmp_path / "dest")


def test_a_failed_hydrate_leaves_no_partial_tree(session, target, tmp_path):
    store = FakeStorage()
    committed = _commit(session, target, store, make_worktree(tmp_path / "source"))
    row = revisions.list_files(session, committed.id)[-1]
    del store.objects[row.blob_key]

    dest = tmp_path / "dest"
    with pytest.raises(hyd.HydrateError):
        hyd.hydrate(session, target, store, dest, emit=lambda line: None)

    assert not dest.exists(), "a half-written worktree is worse than none"


# --- hydrate: materialize + render + install ------------------------------

def test_hydrate_builds_the_head_revisions_tree(session, target, tmp_path):
    store = FakeStorage()
    _commit(session, target, store, make_worktree(tmp_path / "source"))

    dest = tmp_path / "wt"
    result = hyd.hydrate(session, target, store, dest, emit=lambda line: None)

    assert result.rev == 1
    assert (dest / "seed.spec.ts").is_file()
    assert (dest / "tests" / "checkout" / "cart.spec.ts").is_file()


def test_a_second_hydrate_of_the_same_revision_is_byte_identical(
    session, target, tmp_path
):
    """Otherwise every run would commit a revision for the hydrate alone."""
    store = FakeStorage()
    _commit(session, target, store, make_worktree(tmp_path / "source"))

    one, two = tmp_path / "one", tmp_path / "two"
    hyd.hydrate(session, target, store, one, emit=lambda line: None)
    hyd.hydrate(session, target, store, two, emit=lambda line: None)

    assert revisions.scan_tracked_tree(one).blobs == revisions.scan_tracked_tree(two).blobs


def test_generated_entries_are_rendered_from_the_row_not_copied_from_the_revision(
    session, target, tmp_path
):
    """The generated config has exactly one author: the target row."""
    source = make_worktree(tmp_path / "source")
    (source / "playwright.config.ts").write_text("// a stale config from the revision\n")
    store = FakeStorage()
    _commit(session, target, store, source)

    dest = tmp_path / "wt"
    hyd.hydrate(session, target, store, dest, emit=lambda line: None)

    rendered = (dest / "playwright.config.ts").read_text()
    assert rendered == render.render_playwright_config(config_of(target))
    assert "stale config" not in rendered


def test_a_changed_base_url_changes_the_hydrated_config(session, target, tmp_path):
    store = FakeStorage()
    _commit(session, target, store, make_worktree(tmp_path / "source"))

    first = tmp_path / "one"
    hyd.hydrate(session, target, store, first, emit=lambda line: None)
    repo.update_target_config(session, target.id, base_url="https://moved.example.com")
    second = tmp_path / "two"
    hyd.hydrate(session, target, store, second, emit=lambda line: None)

    assert "https://moved.example.com" in (second / "playwright.config.ts").read_text()
    assert (first / "playwright.config.ts").read_text() != (
        second / "playwright.config.ts"
    ).read_text()


def test_a_target_with_no_head_revision_cannot_be_hydrated(session, target, tmp_path):
    """Every target gets revision 1 when it is created, so this is a broken
    target rather than a new one -- and the run must hear the reason."""
    with pytest.raises(hyd.NoHeadRevision, match="no head revision"):
        hyd.hydrate(session, target, FakeStorage(), tmp_path / "wt", emit=lambda line: None)


# --- install: a single named step -----------------------------------------

def test_dependency_install_is_skipped_for_the_fake_runner(
    session, target, tmp_path, monkeypatch
):
    """Nothing to install for synthetic steps, and the API image has no node."""
    monkeypatch.setenv("QA_RUNNER", "fake")
    store = FakeStorage()
    _commit(session, target, store, make_worktree(tmp_path / "source"))

    lines: list[str] = []
    dest = tmp_path / "wt"
    result = hyd.hydrate(session, target, store, dest, emit=lines.append)

    assert result.installed is False
    assert not (dest / "node_modules").exists()


def test_install_is_one_function_so_p4_can_replace_it():
    """P4's prebaked image and warm cache replace one function, not a thread
    through the pipeline."""
    assert callable(hyd.install_dependencies)


def test_a_missing_package_manager_is_a_hard_error_for_the_real_runner(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()

    with pytest.raises(hyd.HydrateError, match="npm"):
        hyd.install_dependencies(tmp_path, lambda line: None, runner_kind="claude")


# --- teardown -------------------------------------------------------------

def test_teardown_removes_the_worktree(session, target, tmp_path):
    store = FakeStorage()
    _commit(session, target, store, make_worktree(tmp_path / "source"))
    dest = tmp_path / "wt"
    hyd.hydrate(session, target, store, dest, emit=lambda line: None)

    hyd.teardown(dest)

    assert not dest.exists()


def test_teardown_of_a_worktree_that_is_not_there_is_not_an_error(tmp_path):
    """It runs at every terminal state, including ones reached before hydrate."""
    hyd.teardown(tmp_path / "never-made")


def test_teardown_removes_node_modules_too(tmp_path):
    """Disk use is bounded by live runs, which it would not be if the biggest
    directory in the worktree survived."""
    root = tmp_path / "wt"
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("//\n")
    os.chmod(root / "node_modules" / "pkg", 0o555)

    hyd.teardown(root)

    assert not root.exists()


# --- the worktree lives outside the run directory -------------------------

def test_the_worktree_is_not_inside_the_run_directory(monkeypatch, tmp_path):
    """Artifact collection sweeps the run dir recursively; a worktree inside it
    would upload the whole source tree and node_modules as run artifacts."""
    from app import config

    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("QA_WORKTREES_DIR", str(tmp_path / "worktrees"))

    run_dir = config.run_dir("r1")
    worktree = config.worktree_dir("r1")

    assert not worktree.is_relative_to(run_dir)
    assert not run_dir.is_relative_to(worktree)


def test_the_defaults_keep_the_worktree_out_of_the_run_dir(monkeypatch):
    """With nothing configured at all, the two are still separate trees."""
    from app import config

    monkeypatch.delenv("QA_WORKTREES_DIR", raising=False)
    monkeypatch.delenv("QA_RUNS_DIR", raising=False)

    assert not config.worktree_dir("r1").is_relative_to(config.runs_dir())
    assert not config.run_dir("r1").is_relative_to(config.worktrees_dir())
