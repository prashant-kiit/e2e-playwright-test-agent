"""bootstrap-target.sh, ported: real git against a local bare remote."""

from __future__ import annotations

import pytest

from app.delivery import errors, render
from app.delivery.bootstrap import (
    bootstrap,
    ensure_bootstrapped,
    is_bootstrapped,
    require_bootstrapped,
)
from tests.delivery_helpers import (
    FakeGitHub,
    make_bare_remote,
    make_tools,
    make_workspace,
    remote_branches,
    remote_files,
    remote_log,
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path / "ws")
    remote = make_bare_remote(tmp_path)
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))
    return workspace, remote


def test_first_bootstrap_creates_the_branch_with_every_infra_file(env):
    workspace, remote = env
    gh = FakeGitHub(has_commits=False)
    result = bootstrap("demo", tools=make_tools(workspace, remote, gh))

    assert result.mode == "bootstrap"
    assert result.pushed is True
    assert remote_files(remote) == set(render.infra_files("demo"))
    assert remote_log(remote) == ["chore: bootstrap Playwright project (demo)"]


def test_second_bootstrap_with_no_changes_pushes_nothing(env):
    workspace, remote = env
    tools = make_tools(workspace, remote, FakeGitHub(has_commits=False))
    bootstrap("demo", tools=tools)

    tools = make_tools(workspace, remote, FakeGitHub(has_commits=True))
    result = bootstrap("demo", tools=tools)

    assert result.mode == "in-sync"
    assert result.pushed is False
    assert len(remote_log(remote)) == 1  # no empty commit


def test_re_bootstrap_pushes_only_what_changed(env):
    """The changed file is an app-scoped one: the infra entries come from the
    templates in this package, so there is nothing in the workspace to edit."""
    workspace, remote = env
    bootstrap("demo", tools=make_tools(workspace, remote, FakeGitHub(has_commits=False)))

    (workspace / "apps" / "demo" / "seed.spec.ts").write_text("// seed v2\n")
    result = bootstrap(
        "demo", tools=make_tools(workspace, remote, FakeGitHub(has_commits=True))
    )

    assert result.mode == "re-bootstrap"
    assert "apps/demo/seed.spec.ts" in result.changes
    assert "package.json" not in result.changes
    assert remote_log(remote)[0] == "chore: re-bootstrap Playwright project (demo)"


def test_the_generated_config_is_pushed_from_the_target_row_not_the_workspace(env):
    """A base-URL change arrives in the delivered config without any file in
    this repo changing: that is what "generated" buys."""
    workspace, remote = env
    bootstrap("demo", tools=make_tools(workspace, remote, FakeGitHub(has_commits=False)))

    import json

    app_json = workspace / "apps" / "demo" / "app.json"
    data = json.loads(app_json.read_text())
    data["baseURL"] = "https://moved.example.com"
    app_json.write_text(json.dumps(data, indent=2) + "\n")

    result = bootstrap(
        "demo", tools=make_tools(workspace, remote, FakeGitHub(has_commits=True))
    )

    assert "playwright.config.ts" in result.changes
    assert result.pushed is True


def test_dry_run_touches_nothing(env):
    workspace, remote = env
    result = bootstrap(
        "demo", dry_run=True, tools=make_tools(workspace, remote, FakeGitHub())
    )

    assert result.mode == "dry-run"
    assert result.pushed is False
    assert remote_branches(remote) == set()


def test_a_missing_workspace_file_fails_before_cloning(env):
    """Only the app-scoped files still come off the workspace; the infra set
    comes from the package, so it cannot be missing."""
    workspace, remote = env
    (workspace / "apps" / "demo" / "seed.spec.ts").unlink()

    with pytest.raises(errors.DeliveryError, match="missing workspace file"):
        bootstrap("demo", tools=make_tools(workspace, remote, FakeGitHub()))

    from tests.delivery_helpers import remote_branches

    assert remote_branches(remote) == set()


def test_is_bootstrapped_is_read_only(env):
    workspace, remote = env
    gh = FakeGitHub(bootstrapped=True)
    ready, target = is_bootstrapped("demo", tools=make_tools(workspace, remote, gh))

    assert ready is True
    assert target.repo == "o/r"
    assert remote_branches(remote) == set()


def test_ensure_bootstrapped_is_a_no_op_when_ready(env):
    workspace, remote = env
    gh = FakeGitHub(bootstrapped=True, has_commits=True)
    assert ensure_bootstrapped("demo", tools=make_tools(workspace, remote, gh)) is None


def test_ensure_bootstrapped_bootstraps_when_not_ready(env):
    workspace, remote = env
    gh = FakeGitHub(bootstrapped=False, has_commits=False)
    result = ensure_bootstrapped("demo", tools=make_tools(workspace, remote, gh))

    assert result is not None and result.pushed is True
    assert remote_files(remote) == set(render.infra_files("demo"))


def test_require_bootstrapped_raises_when_not_ready(env):
    workspace, remote = env
    gh = FakeGitHub(bootstrapped=False)
    with pytest.raises(errors.NotBootstrapped) as exc:
        require_bootstrapped("demo", tools=make_tools(workspace, remote, gh))
    assert exc.value.app == "demo"
