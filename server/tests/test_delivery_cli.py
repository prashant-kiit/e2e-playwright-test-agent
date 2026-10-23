"""The CLI that replaced the four shell entrypoints.

Exit codes are part of the contract: `check` exits 1 when a target is not
bootstrapped (run-stories.sh used to gate on exactly that), and anything else
that fails exits 2 rather than raising a traceback at an operator.
"""

from __future__ import annotations

import pytest

from app.delivery import __main__ as cli
from app.delivery import errors
from tests.delivery_helpers import FakeGitHub, make_bare_remote, make_tools, make_workspace


@pytest.fixture()
def env(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path / "ws")
    remote = make_bare_remote(tmp_path)
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))
    monkeypatch.setenv("GITHUB_PAT", "t0ken")
    return workspace, remote


def _stub_tools(monkeypatch, workspace, remote, gh):
    monkeypatch.setattr(cli, "default_tools", lambda: make_tools(workspace, remote, gh))


def test_check_exits_zero_when_bootstrapped(env, monkeypatch, capsys):
    workspace, remote = env
    _stub_tools(monkeypatch, workspace, remote, FakeGitHub(bootstrapped=True))

    assert cli.main(["check", "demo"]) == cli.EXIT_OK
    assert "bootstrapped: o/r" in capsys.readouterr().out


def test_check_exits_one_when_not_bootstrapped(env, monkeypatch, capsys):
    """The gate the batch runner depended on."""
    workspace, remote = env
    _stub_tools(monkeypatch, workspace, remote, FakeGitHub(bootstrapped=False))

    assert cli.main(["check", "demo"]) == cli.EXIT_NOT_BOOTSTRAPPED
    err = capsys.readouterr().err
    assert "NOT bootstrapped" in err
    assert "python -m app.delivery bootstrap demo" in err


def test_bootstrap_prints_the_file_list_and_result(env, monkeypatch, capsys):
    workspace, remote = env
    _stub_tools(monkeypatch, workspace, remote, FakeGitHub(has_commits=False))

    assert cli.main(["bootstrap", "demo"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "App:    demo" in out
    assert "playwright.config.ts" in out
    assert "done (bootstrap)" in out


def test_bootstrap_dry_run_changes_nothing(env, monkeypatch, capsys):
    workspace, remote = env
    _stub_tools(monkeypatch, workspace, remote, FakeGitHub())

    assert cli.main(["bootstrap", "demo", "--dry-run"]) == cli.EXIT_OK
    assert "(dry-run)" in capsys.readouterr().out


def test_push_prints_the_pr_url(env, monkeypatch, capsys):
    workspace, remote = env
    gh = FakeGitHub(has_commits=False)
    _stub_tools(monkeypatch, workspace, remote, gh)
    cli.main(["bootstrap", "demo"])

    gh.has_commits = True
    gh.bootstrapped = True
    assert cli.main(["push", "demo", "SCRUM-1"]) == cli.EXIT_OK
    assert "PR: https://github.com/o/r/pull/1" in capsys.readouterr().out


def test_a_delivery_error_exits_two_with_a_message_not_a_traceback(env, monkeypatch, capsys):
    workspace, remote = env
    _stub_tools(monkeypatch, workspace, remote, FakeGitHub(bootstrapped=True))

    assert cli.main(["push", "demo", "SCRUM-999"]) == cli.EXIT_ERROR
    assert "expected exactly one" in capsys.readouterr().err


def test_reset_without_a_confirmation_refuses(env, monkeypatch, capsys):
    workspace, remote = env
    _stub_tools(monkeypatch, workspace, remote, FakeGitHub(has_commits=True))

    assert cli.main(["reset", "demo"]) == cli.EXIT_ERROR
    assert "--confirm-repo" in capsys.readouterr().err


def test_reset_with_a_wrong_confirmation_exits_two(env, monkeypatch, capsys):
    workspace, remote = env
    _stub_tools(monkeypatch, workspace, remote, FakeGitHub(has_commits=True))

    assert cli.main(["reset", "demo", "--confirm-repo", "o/nope"]) == cli.EXIT_ERROR
    assert "did not match" in capsys.readouterr().err


def test_reset_dry_run_needs_no_confirmation(env, monkeypatch, capsys):
    workspace, remote = env
    _stub_tools(monkeypatch, workspace, remote, FakeGitHub(has_commits=True))

    assert cli.main(["reset", "demo", "--dry-run"]) == cli.EXIT_OK


def test_an_unknown_command_is_rejected_by_argparse(env):
    with pytest.raises(SystemExit):
        cli.main(["frobnicate", "demo"])


def test_a_missing_token_is_reported_as_an_error(env, monkeypatch, capsys):
    """default_tools() resolves the PAT; without one the CLI must not traceback."""
    monkeypatch.delenv("GITHUB_PAT", raising=False)

    def boom():
        raise errors.CredentialError("no GitHub token")

    monkeypatch.setattr(cli, "default_tools", boom)
    assert cli.main(["check", "demo"]) == cli.EXIT_ERROR
    assert "no GitHub token" in capsys.readouterr().err
