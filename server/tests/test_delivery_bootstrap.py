"""bootstrap-target.sh, ported: real git against a local bare remote.

P3 changed where the files come from and how "bootstrapped" is answered. The
infra entries are rendered from the templates in the server package and from the
target's row, so there is nothing in a workspace to be missing; and
"bootstrapped" is a Postgres query -- has anything ever been delivered to this
repo? -- rather than two REST calls asking GitHub what the branch holds.
"""

from __future__ import annotations

import pytest

from app.delivery import render
from app.delivery.bootstrap import bootstrap, ensure_bootstrapped, is_bootstrapped
from tests.delivery_helpers import (
    DictCatalog,
    FakeGitHub,
    make_bare_remote,
    make_tools,
    make_worktree,
    remote_branches,
    remote_files,
    remote_log,
)


@pytest.fixture()
def env(tmp_path):
    """A worktree-shaped source and a bare remote standing in for GitHub."""
    source = make_worktree(tmp_path / "source")
    remote = make_bare_remote(tmp_path)
    return source, remote


def test_first_bootstrap_creates_the_branch_with_every_infra_file(env):
    source, remote = env
    gh = FakeGitHub(has_commits=False)
    result = bootstrap("demo", tools=make_tools(source, remote, gh))

    assert result.mode == "bootstrap"
    assert result.pushed is True
    assert remote_files(remote) == set(render.INFRA_DESTINATIONS)
    assert remote_log(remote) == ["chore: bootstrap Playwright project (demo)"]


def test_the_infra_comes_from_the_package_not_from_a_workspace(env):
    """Each entry's bytes are its source's bytes: a template in this package, or
    the renderer reading the target's row."""
    source, remote = env
    bootstrap("demo", tools=make_tools(source, remote, FakeGitHub(has_commits=False)))

    files = remote_files(remote)
    assert ".github/workflows/playwright.yml" in files
    assert "playwright.config.ts" in files
    assert not any(f.startswith("apps/") for f in files)
    assert "app.json" not in files, "SaaS-internal config is never delivered"


def test_second_bootstrap_with_no_changes_pushes_nothing(env):
    source, remote = env
    bootstrap("demo", tools=make_tools(source, remote, FakeGitHub(has_commits=False)))

    result = bootstrap("demo", tools=make_tools(source, remote, FakeGitHub(has_commits=True)))

    assert result.mode == "in-sync"
    assert result.pushed is False
    assert len(remote_log(remote)) == 1  # no empty commit


def test_re_bootstrap_pushes_only_what_changed(env):
    """The changed file is the generated config, because a base-URL change is
    the only way an infra file changes without this repo changing."""
    source, remote = env
    import dataclasses

    from tests.target_helpers import CONFIG

    bootstrap("demo", tools=make_tools(source, remote, FakeGitHub(has_commits=False)))

    moved = dataclasses.replace(CONFIG, base_url="https://moved.example.com")
    result = bootstrap(
        "demo",
        tools=make_tools(source, remote, FakeGitHub(has_commits=True), cfg=moved),
    )

    assert result.mode == "re-bootstrap"
    assert "playwright.config.ts" in result.changes
    assert "package.json" not in result.changes
    assert remote_log(remote)[0] == "chore: re-bootstrap Playwright project (demo)"


def test_dry_run_touches_nothing(env):
    source, remote = env
    result = bootstrap("demo", dry_run=True, tools=make_tools(source, remote, FakeGitHub()))

    assert result.mode == "dry-run"
    assert result.pushed is False
    assert remote_branches(remote) == set()


# --- "bootstrapped" is a Postgres query -----------------------------------

def test_is_bootstrapped_is_read_only_and_reads_the_database(env):
    source, remote = env
    from tests.target_helpers import CONFIG

    catalog = DictCatalog(source, CONFIG)
    catalog.record_delivered("demo", "a" * 40)

    ready, target = is_bootstrapped(
        "demo", tools=make_tools(source, remote, FakeGitHub(), catalog=catalog)
    )

    assert ready is True
    assert target.repo == "o/r"
    assert remote_branches(remote) == set(), "a read-only check pushes nothing"


def test_a_target_nothing_has_been_delivered_to_is_not_bootstrapped(env):
    source, remote = env
    ready, _target = is_bootstrapped("demo", tools=make_tools(source, remote, FakeGitHub()))
    assert ready is False


def test_ensure_bootstrapped_is_a_no_op_once_something_has_been_delivered(env):
    source, remote = env
    from tests.target_helpers import CONFIG

    catalog = DictCatalog(source, CONFIG)
    catalog.record_delivered("demo", "a" * 40)

    tools = make_tools(source, remote, FakeGitHub(has_commits=True), catalog=catalog)
    assert ensure_bootstrapped("demo", tools=tools) is None


def test_ensure_bootstrapped_bootstraps_on_the_first_delivery(env):
    """One approval still means "set the repo up and deliver this story"
    (DESIGN.md decision 16)."""
    source, remote = env
    result = ensure_bootstrapped(
        "demo", tools=make_tools(source, remote, FakeGitHub(has_commits=False))
    )

    assert result is not None and result.pushed is True
    assert remote_files(remote) == set(render.INFRA_DESTINATIONS)


def test_an_unknown_target_is_refused(env):
    from app.delivery import errors

    source, remote = env
    with pytest.raises(errors.DeliveryError, match="ghost"):
        bootstrap("ghost", tools=make_tools(source, remote, FakeGitHub()))
