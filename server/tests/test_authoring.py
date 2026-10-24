"""Operator writes: creating a target, and editing its stories and config.

With the mount gone the portal is not a nicety -- it is the only way a story
gets in. Every write commits a revision authored by the operator, so who changed
what and when is answerable from the same history that records agent work, and a
configuration change is as reviewable as a code change.

Writes are **refused while the target has a live run**. A live run hydrated from
an older head; its next ingest would commit a tree that does not contain the
operator's edit, silently reverting it. Resolving that would need merge logic,
and there is no merge logic anywhere in this system (invariant 2). The write is
refused, not queued.
"""

from __future__ import annotations

import pytest

from app import authoring, repo, revisions
from app.delivery import render
from tests.storage_helpers import FakeStorage
from tests.target_helpers import BASE_URL, TARGET_REPO


@pytest.fixture()
def store():
    return FakeStorage()


@pytest.fixture()
def project(session):
    return repo.create_project(session, name="demo")


@pytest.fixture()
def target(session, store, project):
    target, _rev = authoring.create_target(
        session,
        store,
        project_id=project.id,
        app="demo",
        name="Demo",
        base_url=BASE_URL,
        target_repo=TARGET_REPO,
    )
    return target


def _paths(session, target):
    head = revisions.head_revision(session, target.id)
    return {row.path for row in revisions.list_files(session, head.id)}


def _content(session, store, target, path):
    head = revisions.head_revision(session, target.id)
    row = revisions.get_file(session, head.id, path)
    assert row is not None, f"{path} is not in revision {head.rev}"
    return store.objects[row.blob_key][0].decode()


def _revs(session, target):
    return [rev for rev, _n in revisions.list_revisions_with_file_counts(session, target.id)]


# --- creating a target ----------------------------------------------------

def test_creating_a_target_commits_revision_one_from_the_templates(
    session, store, project
):
    """A new target has a tree to hydrate and a history to show before its
    first run, which is also why the baseline-from-disk hook could go."""
    target, rev = authoring.create_target(
        session,
        store,
        project_id=project.id,
        app="fresh",
        name="Fresh",
        base_url=BASE_URL,
        target_repo=TARGET_REPO,
    )

    assert rev.rev == 1
    assert rev.parent_rev is None
    assert rev.author == "operator"
    assert rev.produced_by_run_id is None
    assert _paths(session, target) == {
        "seed.spec.ts",
        *render.INFRA_DESTINATIONS,
    }


def test_revision_one_carries_the_generated_config_rendered_from_the_row(
    session, store, project
):
    target, _rev = authoring.create_target(
        session,
        store,
        project_id=project.id,
        app="fresh",
        name="Fresh",
        base_url="https://fresh.example.com",
        target_repo=TARGET_REPO,
    )

    config = _content(session, store, target, "playwright.config.ts")
    assert "https://fresh.example.com" in config
    assert "name: 'chromium'" in config


def test_a_new_target_can_be_hydrated_immediately(session, store, target, tmp_path):
    """Revision 1 is the whole point: there is no disk to baseline from."""
    from app.sandbox import hydrate as hyd

    result = hyd.hydrate(
        session, target, store, tmp_path / "wt", emit=lambda line: None, install=False
    )

    assert result.rev == 1
    assert (tmp_path / "wt" / "seed.spec.ts").is_file()


def test_an_invalid_configuration_creates_neither_a_row_nor_a_revision(
    session, store, project
):
    from app import target_config

    with pytest.raises(target_config.ConfigError):
        authoring.create_target(
            session,
            store,
            project_id=project.id,
            app="bad",
            name="Bad",
            base_url="not-a-url",
            target_repo=TARGET_REPO,
        )

    assert [t.app for t in repo.list_targets(session)] == []
    assert list(session.scalars(repo.select(revisions.Revision))) == []


# --- story authoring ------------------------------------------------------

def test_writing_a_story_commits_one_revision_containing_it(session, store, target):
    rev = authoring.write_story(
        session,
        store,
        target,
        story_id="SCRUM-9",
        slug="signup",
        content="# User Story: SCRUM-9 - Sign-up\n\nAs a user...\n",
    )

    assert rev.rev == 2
    assert rev.parent_rev == 1
    assert rev.author == "operator"
    assert "user-stories/SCRUM-9-signup.md" in _paths(session, target)
    assert [r.rev for r in _revs(session, target)] == [2, 1]


def test_editing_a_story_commits_one_revision(session, store, target):
    authoring.write_story(
        session, store, target, story_id="SCRUM-9", slug="signup", content="# one\n"
    )

    rev = authoring.write_story(
        session, store, target, story_id="SCRUM-9", slug="signup", content="# two\n"
    )

    assert rev.rev == 3
    assert _content(session, store, target, "user-stories/SCRUM-9-signup.md") == "# two\n"
    assert [r.rev for r in _revs(session, target)] == [3, 2, 1]


def test_renaming_a_storys_slug_is_one_revision_not_two(session, store, target):
    authoring.write_story(
        session, store, target, story_id="SCRUM-9", slug="signup", content="# one\n"
    )

    authoring.write_story(
        session, store, target, story_id="SCRUM-9", slug="registration", content="# one\n"
    )

    paths = _paths(session, target)
    assert "user-stories/SCRUM-9-registration.md" in paths
    assert "user-stories/SCRUM-9-signup.md" not in paths
    assert [r.rev for r in _revs(session, target)] == [3, 2, 1]


def test_an_unchanged_story_write_commits_nothing(session, store, target):
    """`rev` counts real changes. Saving a form without editing it is not one."""
    authoring.write_story(
        session, store, target, story_id="SCRUM-9", slug="signup", content="# one\n"
    )

    again = authoring.write_story(
        session, store, target, story_id="SCRUM-9", slug="signup", content="# one\n"
    )

    assert again is None
    assert [r.rev for r in _revs(session, target)] == [2, 1]


def test_deleting_a_story_commits_one_revision_without_it(session, store, target):
    authoring.write_story(
        session, store, target, story_id="SCRUM-9", slug="signup", content="# one\n"
    )

    rev = authoring.delete_story(session, store, target, story_id="SCRUM-9")

    assert rev.rev == 3
    assert "user-stories/SCRUM-9-signup.md" not in _paths(session, target)


def test_deleting_a_story_that_is_not_there_is_refused(session, store, target):
    with pytest.raises(authoring.NoSuchStory, match="SCRUM-404"):
        authoring.delete_story(session, store, target, story_id="SCRUM-404")


def test_deleting_a_story_leaves_its_plan_and_suite_alone(session, store, target):
    """An operator deleting a story has not asked us to destroy a healed suite.
    The history still holds it either way, and removing the tests as well is a
    deliberate second act."""
    authoring.write_story(
        session, store, target, story_id="SCRUM-9", slug="signup", content="# one\n"
    )
    authoring.write_file(
        session, store, target, path="tests/signup/a.spec.ts", content="// a\n"
    )

    authoring.delete_story(session, store, target, story_id="SCRUM-9")

    assert "tests/signup/a.spec.ts" in _paths(session, target)


def test_an_invalid_story_id_is_refused(session, store, target):
    with pytest.raises(authoring.InvalidStory):
        authoring.write_story(
            session, store, target, story_id="not a story id", slug="x", content="# x\n"
        )


def test_a_story_slug_cannot_escape_the_stories_directory(session, store, target):
    """The path is built from operator input, so it is validated rather than
    interpolated: `../../` in a slug would write outside the tree."""
    with pytest.raises(authoring.InvalidStory):
        authoring.write_story(
            session, store, target, story_id="SCRUM-9", slug="../../etc/passwd",
            content="# x\n",
        )


def test_listing_stories_reads_the_head_revision(session, store, target):
    authoring.write_story(
        session,
        store,
        target,
        story_id="SCRUM-9",
        slug="signup",
        content="# User Story: SCRUM-9 - Account Sign-up\n",
    )

    stories = authoring.list_stories(session, store, target)

    assert [(s["story_id"], s["slug"], s["title"]) for s in stories] == [
        ("SCRUM-9", "signup", "Account Sign-up")
    ]


# --- config authoring -----------------------------------------------------

def test_changing_the_base_url_commits_a_revision_with_the_new_config(
    session, store, target
):
    """A configuration change is a tree diff, which is a revision, which is as
    reviewable as a code change."""
    _t, rev = authoring.update_config(
        session, store, target, base_url="https://moved.example.com"
    )

    assert rev is not None and rev.rev == 2
    config = _content(session, store, target, "playwright.config.ts")
    assert "https://moved.example.com" in config


def test_changing_config_that_does_not_reach_the_tree_commits_no_revision(
    session, store, target
):
    """`locators` is injected into the prompt, not into a tracked file, so there
    is no tree diff to record."""
    _t, rev = authoring.update_config(
        session, store, target, locators="data-qa attributes"
    )

    assert rev is None
    assert [r.rev for r in _revs(session, target)] == [1]
    session.expire_all()
    assert repo.get_target(session, target.id).locators == "data-qa attributes"


def test_an_invalid_config_edit_changes_neither_the_row_nor_the_tree(
    session, store, target
):
    from app import target_config

    with pytest.raises(target_config.ConfigError):
        authoring.update_config(session, store, target, base_url="nonsense")

    session.expire_all()
    assert repo.get_target(session, target.id).base_url == BASE_URL
    assert [r.rev for r in _revs(session, target)] == [1]


# --- refused while a run is live ------------------------------------------

def _start_run(session, target):
    return repo.start_run(session, target_id=target.id, story_id="SCRUM-1", mode="full")


def test_a_story_write_is_refused_while_a_run_is_live(session, store, target):
    _start_run(session, target)

    with pytest.raises(repo.RunConflict) as exc:
        authoring.write_story(
            session, store, target, story_id="SCRUM-9", slug="signup", content="# x\n"
        )

    assert "live run" in str(exc.value)
    assert [r.rev for r in _revs(session, target)] == [1]


def test_a_story_delete_is_refused_while_a_run_is_live(session, store, target):
    authoring.write_story(
        session, store, target, story_id="SCRUM-9", slug="signup", content="# x\n"
    )
    _start_run(session, target)

    with pytest.raises(repo.RunConflict):
        authoring.delete_story(session, store, target, story_id="SCRUM-9")


def test_a_config_edit_is_refused_while_a_run_is_live(session, store, target):
    _start_run(session, target)

    with pytest.raises(repo.RunConflict):
        authoring.update_config(session, store, target, base_url="https://moved.example.com")

    session.expire_all()
    assert repo.get_target(session, target.id).base_url == BASE_URL


def test_a_write_is_allowed_again_once_the_run_is_over(session, store, target):
    run = _start_run(session, target)
    repo.request_stop(session, run.id)  # a pending run stops at once

    rev = authoring.write_story(
        session, store, target, story_id="SCRUM-9", slug="signup", content="# x\n"
    )
    assert rev.rev == 2


def test_the_refusal_names_the_run_that_holds_the_target(session, store, target):
    """The operator's next move is to wait for it, or pause it -- so say which."""
    run = _start_run(session, target)

    with pytest.raises(repo.RunConflict) as exc:
        authoring.write_story(
            session, store, target, story_id="SCRUM-9", slug="signup", content="# x\n"
        )

    assert str(run.id) in str(exc.value)
