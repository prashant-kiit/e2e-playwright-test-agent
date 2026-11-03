"""Prompts, settings, and the optional infra sync (no database, no network)."""

from __future__ import annotations

import pytest

from app import apphub
from app.delivery import render
from tests.delivery_helpers import (
    FakeGitHub,
    make_bare_remote,
    make_tools,
    make_worktree,
)

# --- prompts: rows, seeded from the package (P5-06) -----------------------

def test_prompts_are_served_as_this_tenants_rows(session, tmp_path, monkeypatch):
    """What the portal shows is what the agent is sent -- a row now, seeded
    from the shipped file, and still found without a mounted repo."""
    monkeypatch.chdir(tmp_path)

    served = apphub.read_prompts(session)
    names = [p["name"] for p in served]

    assert "qa_system_prompt.md" in names
    assert "steps/_context.md" in names
    assert all(p["content"] for p in served)
    # Seeded on this first read, so every prompt is at the default revision.
    assert {p["rev"] for p in served} == {1}


def test_the_step_prompts_are_listed_in_order(session):
    names = [
        p["name"] for p in apphub.read_prompts(session) if p["name"].startswith("steps/")
    ]
    assert names == sorted(names)


def test_the_page_shows_an_override_and_its_revision(session):
    """The page is the authoring surface, so it shows what a customer would
    edit rather than the bytes the package shipped."""
    apphub.save_prompt(session, "steps/2-plan.md", "Plan it my way.\n")

    shown = {p["name"]: p for p in apphub.read_prompts(session)}

    assert shown["steps/2-plan.md"]["content"] == "Plan it my way.\n"
    assert shown["steps/2-plan.md"]["rev"] == 2
    assert shown["steps/3-explore.md"]["rev"] == 1


def test_saving_a_prompt_the_package_never_shipped_is_refused(session):
    """A typo must not create a row nothing resolves -- a prompt a customer
    could tune carefully and never have sent."""
    from app import prompt_store

    with pytest.raises(prompt_store.PromptNotFound):
        apphub.save_prompt(session, "steps/99-invented.md", "hi\n")


# --- settings: no repo root -----------------------------------------------

def test_settings_report_the_runner_and_the_scratch_directories():
    s = apphub.settings()
    assert s["runner"] in ("fake", "claude")
    assert s["runs_dir"]
    assert s["worktrees_dir"]


def test_settings_do_not_report_a_repo_root():
    """P3 removed the shared authoritative mount; a UI still reporting one would
    be describing a disk that does not exist."""
    assert "repo_root" not in apphub.settings()


def test_the_worktrees_directory_is_not_inside_the_runs_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.delenv("QA_WORKTREES_DIR", raising=False)

    s = apphub.settings()
    assert not s["worktrees_dir"].startswith(s["runs_dir"])


# --- the optional infra sync ----------------------------------------------

@pytest.fixture()
def env(tmp_path):
    return make_worktree(tmp_path / "source"), make_bare_remote(tmp_path)


def test_a_successful_sync_reports_what_it_pushed(env):
    source, remote = env

    outcome = apphub.run_bootstrap(
        "demo", tools=make_tools(source, remote, FakeGitHub(has_commits=False))
    )

    assert outcome.ok is True
    assert "o/r (master)" in outcome.output
    assert "done (bootstrap)" in outcome.output


def test_a_failed_sync_is_an_outcome_not_an_exception(env):
    """The target and its revision 1 exist either way, so the form shows why the
    sync did not land rather than losing the target to a 500."""
    source, remote = env

    outcome = apphub.run_bootstrap(
        "ghost", tools=make_tools(source, remote, FakeGitHub(has_commits=False))
    )

    assert outcome.ok is False
    assert "ghost" in outcome.output


def test_the_sync_pushes_the_infra_entries(env):
    from tests.delivery_helpers import remote_files

    source, remote = env
    apphub.run_bootstrap(
        "demo", tools=make_tools(source, remote, FakeGitHub(has_commits=False))
    )

    assert remote_files(remote) == set(render.INFRA_DESTINATIONS)
