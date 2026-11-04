"""The CLI that replaced the four shell entrypoints.

Exit codes are part of the contract: `check` exits 1 when a target is not
bootstrapped (run-stories.sh used to gate on exactly that), and anything else
that fails exits 2 rather than raising a traceback at an operator.

**The mutating commands write an audit row** (P5-07), so `bootstrap`, `push`
and `reset` need a database where the read-only commands do not -- they take
the `audit_db` fixture, which points the session the CLI opens for itself at
the fixture's engine. Without it `conftest._no_dev_database` fails them, which
is the point: the CLI opens its own session, so there is nothing for a test to
inject and the seam has to be substituted deliberately.
"""

from __future__ import annotations

import pytest

from app.delivery import __main__ as cli
from app.delivery import errors
from tests.delivery_helpers import (
    DictCatalog,
    FakeGitHub,
    make_bare_remote,
    make_tools,
    make_worktree,
)
from tests.target_helpers import CONFIG


@pytest.fixture()
def env(tmp_path, monkeypatch):
    source = make_worktree(tmp_path / "source")
    remote = make_bare_remote(tmp_path)
    monkeypatch.setenv("GITHUB_PAT", "t0ken")
    return source, remote


@pytest.fixture()
def audit_db(session, monkeypatch):
    """Point the session the CLI opens for itself at the test database.

    The CLI has no session to be handed -- it is a process, not a request -- so
    it resolves `app.db.SessionLocal` at call time. `conftest._no_dev_database`
    replaces that with a refusal; this puts a factory on the fixture's engine
    back in its place, which is the only way these tests can exercise the audit
    write at all.

    A factory built from `session.get_bind()` rather than the `session_factory`
    fixture: taking both that and `session` in one test deadlocks teardown,
    because each truncates on the way out.
    """
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False, future=True)
    monkeypatch.setattr("app.db.SessionLocal", factory)
    return session


def _audit_rows(session, action=None):
    from app import audit

    rows = audit.entries(session)
    return [r for r in rows if action is None or r.action is action]


def _stub_tools(monkeypatch, source, remote, gh, catalog=None):
    monkeypatch.setattr(
        cli, "default_tools", lambda: make_tools(source, remote, gh, catalog=catalog)
    )


def test_check_reports_delivered_once_something_has_been_delivered(
    env, monkeypatch, capsys
):
    source, remote = env
    catalog = DictCatalog(source, CONFIG)
    catalog.record_delivered("demo", "a" * 40)
    _stub_tools(monkeypatch, source, remote, FakeGitHub(), catalog)

    assert cli.main(["check", "demo"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Target: o/r (master)" in out
    assert "delivered (revision 1)" in out
    assert "a" * 40 in out


def test_check_exits_one_when_nothing_has_been_delivered(env, monkeypatch, capsys):
    """The gate the batch runner depended on, answered from the database."""
    source, remote = env
    _stub_tools(monkeypatch, source, remote, FakeGitHub())

    assert cli.main(["check", "demo"]) == cli.EXIT_NOT_BOOTSTRAPPED
    captured = capsys.readouterr()
    assert "never delivered" in captured.out
    assert "NOT bootstrapped" in captured.err


def test_bootstrap_prints_the_file_list_and_result(env, monkeypatch, capsys, audit_db):
    source, remote = env
    _stub_tools(monkeypatch, source, remote, FakeGitHub(has_commits=False))

    assert cli.main(["bootstrap", "demo"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "App:    demo" in out
    assert "playwright.config.ts" in out
    assert "done (bootstrap)" in out


def test_bootstrap_records_the_infra_sync(env, monkeypatch, capsys, audit_db):
    """This is the "infra re-sync" #37 names.

    The API's `sync_infra` flag only covers the *first* sync, at target
    creation; re-syncing an existing target is this command, and it went
    unrecorded in the first cut of the audit log.
    """
    from app.domain.audit import Action

    source, remote = env
    _stub_tools(monkeypatch, source, remote, FakeGitHub(has_commits=False))

    cli.main(["bootstrap", "demo"])

    (row,) = _audit_rows(audit_db, Action.INFRA_SYNC)
    assert row.target == "target:demo"
    assert row.after["via"] == "cli"
    assert row.after["repo"] == "o/r"
    # Nobody is logged in at a console, and the row says so rather than
    # inventing a user.
    assert row.actor == "system"


def test_a_bootstrap_dry_run_records_nothing(env, monkeypatch, capsys, audit_db):
    source, remote = env
    _stub_tools(monkeypatch, source, remote, FakeGitHub())

    cli.main(["bootstrap", "demo", "--dry-run"])

    assert _audit_rows(audit_db) == []


def test_bootstrap_dry_run_changes_nothing(env, monkeypatch, capsys):
    source, remote = env
    _stub_tools(monkeypatch, source, remote, FakeGitHub())

    assert cli.main(["bootstrap", "demo", "--dry-run"]) == cli.EXIT_OK
    assert "(dry-run)" in capsys.readouterr().out


def test_push_prints_the_pr_url(env, monkeypatch, capsys, audit_db):
    workspace, remote = env
    gh = FakeGitHub(has_commits=False)
    _stub_tools(monkeypatch, workspace, remote, gh)
    cli.main(["bootstrap", "demo"])

    gh.has_commits = True
    gh.bootstrapped = True
    assert cli.main(["push", "demo", "SCRUM-1"]) == cli.EXIT_OK
    assert "PR: https://github.com/o/r/pull/1" in capsys.readouterr().out


def test_a_cli_push_is_recorded_in_the_audit_log(env, monkeypatch, capsys, audit_db):
    """`make deliver` pushes a commit into a customer's repo.

    The first cut of P5-07 audited only the HTTP route, so this path -- which
    the Makefile documents as the CLI-only way to deliver -- wrote into a
    customer's repo and left no trail. That is exactly the question #37 exists
    to answer, asked of the path most likely to be used by an operator in a
    hurry.
    """
    from app.domain.audit import Action

    workspace, remote = env
    gh = FakeGitHub(has_commits=False)
    _stub_tools(monkeypatch, workspace, remote, gh)
    cli.main(["bootstrap", "demo"])
    gh.has_commits = True
    gh.bootstrapped = True

    cli.main(["push", "demo", "SCRUM-1"])

    (row,) = _audit_rows(audit_db, Action.DELIVERY_APPROVE)
    assert row.target == "target:demo"
    assert row.after["story_id"] == "SCRUM-1"
    assert row.after["via"] == "cli"
    assert row.after["pr_url"].endswith("/pull/1")
    assert row.actor == "system"


def test_a_delivery_error_exits_two_with_a_message_not_a_traceback(env, monkeypatch, capsys):
    source, remote = env
    _stub_tools(monkeypatch, source, remote, FakeGitHub(has_commits=True))

    assert cli.main(["push", "demo", "SCRUM-999"]) == cli.EXIT_ERROR
    assert "expected exactly one" in capsys.readouterr().err


def test_reset_without_a_confirmation_refuses(env, monkeypatch, capsys):
    source, remote = env
    _stub_tools(monkeypatch, source, remote, FakeGitHub(has_commits=True))

    assert cli.main(["reset", "demo"]) == cli.EXIT_ERROR
    assert "--confirm-repo" in capsys.readouterr().err


def test_reset_with_a_wrong_confirmation_exits_two(env, monkeypatch, capsys):
    source, remote = env
    _stub_tools(monkeypatch, source, remote, FakeGitHub(has_commits=True))

    assert cli.main(["reset", "demo", "--confirm-repo", "o/nope"]) == cli.EXIT_ERROR
    assert "did not match" in capsys.readouterr().err


def test_reset_dry_run_needs_no_confirmation(env, monkeypatch, capsys):
    source, remote = env
    _stub_tools(monkeypatch, source, remote, FakeGitHub(has_commits=True))

    assert cli.main(["reset", "demo", "--dry-run"]) == cli.EXIT_OK


def test_an_unknown_command_is_rejected_by_argparse(env):
    with pytest.raises(SystemExit):
        cli.main(["frobnicate", "demo"])


def test_a_missing_credential_is_reported_as_an_error(env, monkeypatch, capsys):
    """A credential failure must reach the operator as a message, not a traceback.

    P5-03 moved *where* that failure comes from: it used to be `default_tools()`
    finding no `GITHUB_PAT` in the environment, and it is now binding the seam
    to a target whose row carries no sealed PAT. Both arrive here as the same
    `CredentialError` through the same `except`, which is why this test is
    unchanged apart from its name -- and why the CLI needed no change at all.
    """

    def boom():
        raise errors.CredentialError("no GitHub token")

    monkeypatch.setattr(cli, "default_tools", boom)
    assert cli.main(["check", "demo"]) == cli.EXIT_ERROR
    assert "no GitHub token" in capsys.readouterr().err
