"""A target's configuration is a row, validated where it is written.

P3's first move: `baseURL`, `locators`, `agentNotes`, `targetRepo` and
`targetBranch` stop being a file in this repo and become columns. The refusal
that target resolution used to perform at read time -- an empty or placeholder
target repo, a base URL that is not an absolute http(s) URL -- moves here, to
the write path, where the operator who typed it is still around to be told.
"""

from __future__ import annotations

import pytest

from app import repo, target_config
from tests.target_helpers import create_target


def _project(session):
    return repo.create_project(session, name="demo")


# --- the configuration round-trips ---------------------------------------

def test_a_targets_configuration_round_trips_through_its_row(session):
    project = _project(session)
    target = create_target(
        session,
        project.id,
        app="demo",
        base_url="https://demo.example.com",
        target_repo="owner/tests",
        target_branch="main",
        locators="data-test attributes",
        agent_notes=["the seed logs in", "firefox is flaky"],
    )

    session.expire_all()
    stored = repo.get_target(session, target.id)
    assert stored.base_url == "https://demo.example.com"
    assert stored.target_repo == "owner/tests"
    assert stored.target_branch == "main"
    assert stored.locators == "data-test attributes"
    assert stored.agent_notes == ["the seed logs in", "firefox is flaky"]


def test_the_branch_defaults_to_master_at_the_application_layer(session):
    project = _project(session)
    target = create_target(session, project.id, target_branch=None)
    assert target.target_branch == target_config.DEFAULT_BRANCH == "master"


# --- validation at save --------------------------------------------------

@pytest.mark.parametrize(
    "bad",
    ["", "   ", "demo.example.com", "/relative/path", "ftp://demo.example.com",
     "https://", "javascript:alert(1)"],
)
def test_a_base_url_that_is_not_an_absolute_http_url_is_refused(session, bad):
    project = _project(session)
    with pytest.raises(target_config.ConfigError):
        create_target(session, project.id, base_url=bad)


@pytest.mark.parametrize(
    "good",
    ["https://demo.example.com", "http://localhost:3000", "https://a.b.c/sub/path"],
)
def test_an_absolute_http_url_is_accepted(session, good):
    project = _project(session)
    assert create_target(session, project.id, base_url=good).base_url == good


@pytest.mark.parametrize("bad", ["", "   ", "justrepo", "owner/", "/repo", "a/b/c"])
def test_a_target_repo_that_is_not_owner_slash_repo_is_refused(session, bad):
    project = _project(session)
    with pytest.raises(target_config.ConfigError):
        create_target(session, project.id, target_repo=bad)


def test_the_template_placeholder_target_repo_is_refused(session):
    """The refusal `resolve_target` performed at read time, moved to the write
    path: apps/_template's placeholder is never a real target."""
    project = _project(session)
    with pytest.raises(target_config.ConfigError):
        create_target(session, project.id, target_repo=target_config.PLACEHOLDER_REPO)


def test_agent_notes_is_a_list_of_strings(session):
    """It is a list today and is injected into the prompt as a list."""
    project = _project(session)
    with pytest.raises(target_config.ConfigError):
        create_target(session, project.id, agent_notes="one note, not a list")


def test_a_refused_write_leaves_no_target_behind(session):
    """Validation happens before the insert, not after it."""
    project = _project(session)
    with pytest.raises(target_config.ConfigError):
        create_target(session, project.id, app="never", base_url="nope")
    assert [t.app for t in repo.list_targets(session)] == []
