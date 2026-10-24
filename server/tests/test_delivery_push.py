"""push-artifacts.sh, ported.

The properties worth protecting are the ones a customer would notice:
delivery appends (never force-pushes), and a test deleted in the agent repo
disappears from the branch.

P3 made the delivered paths **root-relative** -- `user-stories/...`, not
`apps/<app>/user-stories/...`. The stored shape, the hydrated shape and the
delivered shape are one shape now, which is what lets the generated
single-target config find the suite it ships beside.
"""

from __future__ import annotations

import pytest

from app.delivery import errors
from app.delivery.bootstrap import bootstrap
from app.delivery.push import push_artifacts
from tests.delivery_helpers import (
    FakeGitHub,
    make_bare_remote,
    make_tools,
    make_workspace,
    remote_branches,
    remote_files,
    remote_log,
)

BRANCH = "qa/SCRUM-1-checkout"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A workspace whose remote is already bootstrapped on master."""
    workspace = make_workspace(tmp_path / "ws")
    remote = make_bare_remote(tmp_path)
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))
    bootstrap("demo", tools=make_tools(workspace, remote, FakeGitHub(has_commits=False)))
    return workspace, remote


def ready_tools(workspace, remote, gh=None):
    return make_tools(workspace, remote, gh or FakeGitHub(has_commits=True, bootstrapped=True))


def test_delivery_pushes_the_story_plan_and_tests_and_opens_a_pr(env):
    workspace, remote = env
    gh = FakeGitHub(has_commits=True, bootstrapped=True)
    result = push_artifacts("demo", "SCRUM-1", tools=ready_tools(workspace, remote, gh))

    assert result.committed is True
    assert result.pr_created is True
    assert result.branch == BRANCH
    assert gh.created == [BRANCH]
    assert gh.prs[BRANCH].title == "SCRUM-1: Checkout Flow E2E test suite"
    assert gh.prs[BRANCH].base == "master"

    files = remote_files(remote, BRANCH)
    assert "user-stories/SCRUM-1-checkout.md" in files
    assert "specs/SCRUM-1-checkout-test-plan.md" in files
    assert "tests/checkout/cart.spec.ts" in files
    assert "tests/checkout/pay.spec.ts" in files
    # Infra is bootstrap's job, and it is already there from the fixture.
    assert "playwright.config.ts" in files


def test_re_delivery_appends_a_commit_and_updates_the_pr(env):
    """DESIGN.md decision 10: append, never force-push -- a force-push into a
    customer's branch destroys the PR's review threads."""
    workspace, remote = env
    gh = FakeGitHub(has_commits=True, bootstrapped=True)
    push_artifacts("demo", "SCRUM-1", tools=ready_tools(workspace, remote, gh))
    first = remote_log(remote, BRANCH)

    (workspace / "apps/demo/tests/checkout/cart.spec.ts").write_text("// cart v2\n")
    result = push_artifacts("demo", "SCRUM-1", tools=ready_tools(workspace, remote, gh))

    second = remote_log(remote, BRANCH)
    assert result.pr_created is False
    assert gh.updated == [1]
    assert len(second) == len(first) + 1
    assert second[1:] == first  # history preserved, nothing rewritten


def test_a_deleted_test_disappears_from_the_branch(env):
    workspace, remote = env
    gh = FakeGitHub(has_commits=True, bootstrapped=True)
    push_artifacts("demo", "SCRUM-1", tools=ready_tools(workspace, remote, gh))
    assert "tests/checkout/pay.spec.ts" in remote_files(remote, BRANCH)

    (workspace / "apps/demo/tests/checkout/pay.spec.ts").unlink()
    push_artifacts("demo", "SCRUM-1", tools=ready_tools(workspace, remote, gh))

    files = remote_files(remote, BRANCH)
    assert "tests/checkout/pay.spec.ts" not in files
    assert "tests/checkout/cart.spec.ts" in files


def test_unchanged_artifacts_make_no_new_commit_but_still_sync_the_pr(env):
    workspace, remote = env
    gh = FakeGitHub(has_commits=True, bootstrapped=True)
    push_artifacts("demo", "SCRUM-1", tools=ready_tools(workspace, remote, gh))
    before = remote_log(remote, BRANCH)

    result = push_artifacts("demo", "SCRUM-1", tools=ready_tools(workspace, remote, gh))

    assert result.committed is False
    assert "no new commit" in result.message
    assert remote_log(remote, BRANCH) == before
    assert gh.updated == [1]


def test_run_id_lands_in_the_commit_and_the_pr_body(env):
    workspace, remote = env
    gh = FakeGitHub(has_commits=True, bootstrapped=True)
    push_artifacts(
        "demo", "SCRUM-1", run_id="20261023-run-7", tools=ready_tools(workspace, remote, gh)
    )

    message = remote_log(remote, BRANCH)[0]
    assert message == "feat(tests): SCRUM-1 Checkout Flow"
    assert "Run-ID: 20261023-run-7" in gh.last_body


def test_a_body_file_overrides_the_default_pr_body(env, tmp_path):
    workspace, remote = env
    body = tmp_path / "body.md"
    body.write_text("Custom report body.\n")
    gh = FakeGitHub(has_commits=True, bootstrapped=True)

    push_artifacts(
        "demo", "SCRUM-1", body_file=body, tools=ready_tools(workspace, remote, gh)
    )
    assert gh.last_body == "Custom report body.\n"


def test_delivery_without_a_test_suite_is_refused(env):
    workspace, remote = env
    import shutil

    shutil.rmtree(workspace / "apps/demo/tests/checkout")

    with pytest.raises(errors.DeliveryError, match="no test suite"):
        push_artifacts("demo", "SCRUM-1", tools=ready_tools(workspace, remote))
    assert BRANCH not in remote_branches(remote)


def test_delivery_to_an_unbootstrapped_target_is_refused(env):
    workspace, remote = env
    gh = FakeGitHub(has_commits=True, bootstrapped=False)

    with pytest.raises(errors.NotBootstrapped):
        push_artifacts("demo", "SCRUM-1", tools=ready_tools(workspace, remote, gh))
    assert BRANCH not in remote_branches(remote)


def test_dry_run_neither_pushes_nor_opens_a_pr(env):
    workspace, remote = env
    gh = FakeGitHub(has_commits=True, bootstrapped=True)
    result = push_artifacts(
        "demo", "SCRUM-1", dry_run=True, tools=ready_tools(workspace, remote, gh)
    )

    assert result.committed is False
    assert result.pr_url == ""
    assert gh.created == []
    assert BRANCH not in remote_branches(remote)


def test_a_story_with_no_plan_still_delivers(env):
    """The plan is optional: push-artifacts.sh copied it only when present."""
    workspace, remote = env
    (workspace / "apps/demo/specs/SCRUM-1-checkout-test-plan.md").unlink()
    gh = FakeGitHub(has_commits=True, bootstrapped=True)

    push_artifacts("demo", "SCRUM-1", tools=ready_tools(workspace, remote, gh))

    files = remote_files(remote, BRANCH)
    assert "specs/SCRUM-1-checkout-test-plan.md" not in files
    assert "tests/checkout/cart.spec.ts" in files
