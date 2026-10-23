"""reset-target.sh, ported -- destructive, so the guard is the main subject.

The shell tool read a typed confirmation from a TTY. A portal action has no TTY,
so the guard became part of the function's contract; these tests are what keep it
from being quietly dropped.
"""

from __future__ import annotations

import pytest

from app.delivery import errors
from app.delivery.bootstrap import bootstrap
from app.delivery.push import push_artifacts
from app.delivery.reset import plan_reset, reset_target
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


@pytest.fixture()
def populated(env):
    """A remote with infra on master and one delivered story branch."""
    workspace, remote = env
    bootstrap("demo", tools=make_tools(workspace, remote, FakeGitHub(has_commits=False)))
    push_artifacts(
        "demo",
        "SCRUM-1",
        tools=make_tools(workspace, remote, FakeGitHub(has_commits=True, bootstrapped=True)),
    )
    return workspace, remote


def test_a_wrong_confirmation_aborts_and_changes_nothing(populated):
    workspace, remote = populated
    before_branches = remote_branches(remote)
    before_log = remote_log(remote)

    with pytest.raises(errors.ConfirmationMismatch):
        reset_target(
            "demo",
            confirm_repo="o/wrong",
            tools=make_tools(workspace, remote, FakeGitHub(has_commits=True)),
        )

    assert remote_branches(remote) == before_branches
    assert remote_log(remote) == before_log


def test_an_empty_confirmation_aborts(populated):
    workspace, remote = populated
    with pytest.raises(errors.ConfirmationMismatch):
        reset_target(
            "demo",
            confirm_repo="",
            tools=make_tools(workspace, remote, FakeGitHub(has_commits=True)),
        )


def test_dry_run_reports_the_branches_it_would_delete_and_changes_nothing(populated):
    workspace, remote = populated
    before = remote_branches(remote)

    result = reset_target(
        "demo",
        confirm_repo="o/r",
        dry_run=True,
        tools=make_tools(workspace, remote, FakeGitHub(has_commits=True)),
    )

    assert result.reset_branch is False
    assert "qa/SCRUM-1-checkout" in result.deleted_branches
    assert "master" not in result.deleted_branches
    assert remote_branches(remote) == before


def test_dry_run_does_not_need_a_confirmation(populated):
    workspace, remote = populated
    result = reset_target(
        "demo",
        confirm_repo="",
        dry_run=True,
        tools=make_tools(workspace, remote, FakeGitHub(has_commits=True)),
    )
    assert result.reset_branch is False


def test_reset_empties_the_target_branch_and_deletes_the_others(populated):
    workspace, remote = populated

    result = reset_target(
        "demo",
        confirm_repo="o/r",
        tools=make_tools(workspace, remote, FakeGitHub(has_commits=True)),
    )

    assert result.reset_branch is True
    assert "qa/SCRUM-1-checkout" in result.deleted_branches
    assert remote_branches(remote) == {"master"}
    assert remote_files(remote) == set()  # files gone
    assert remote_log(remote) == [
        "chore: reset target repo for a fresh start (demo)"
    ]  # history gone too


def test_an_already_empty_repo_is_a_no_op(env):
    workspace, remote = env
    result = reset_target(
        "demo",
        confirm_repo="o/r",
        tools=make_tools(workspace, remote, FakeGitHub(has_commits=False)),
    )

    assert result.already_empty is True
    assert result.reset_branch is False
    assert "already empty" in result.message


def test_plan_reset_is_read_only(populated):
    workspace, remote = populated
    before = remote_branches(remote)

    plan = plan_reset("demo", tools=make_tools(workspace, remote, FakeGitHub(has_commits=True)))

    assert plan.already_empty is False
    assert remote_branches(remote) == before


def test_bootstrap_works_again_after_a_reset(populated):
    """The documented follow-up: reset, then bootstrap starts clean."""
    workspace, remote = populated
    reset_target(
        "demo",
        confirm_repo="o/r",
        tools=make_tools(workspace, remote, FakeGitHub(has_commits=True)),
    )

    result = bootstrap("demo", tools=make_tools(workspace, remote, FakeGitHub(has_commits=True)))

    assert result.pushed is True
    assert "playwright.config.ts" in remote_files(remote)
