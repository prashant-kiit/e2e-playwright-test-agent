"""push-artifacts.sh, ported, and then flipped onto the database.

The properties worth protecting are the ones a customer would notice: delivery
appends (never force-pushes), and a test deleted in the harness disappears from
the branch. Only the REST boundary and the database are faked -- git, the
filesystem and the infra templates are all real, so clone/branch/commit/push and
the wholesale-replace semantics are exercised for real.

What P3 changed:

- **The source is a materialized head revision**, not a mount. The delivered
  paths are the stored paths, root-relative, which is what lets the generated
  single-target config find the suite it ships beside.
- **`delivered_sha` is recorded** on the revision that was pushed, by delivery
  and by nothing else, so "what exactly did we push, and from what?" is a row.
- When the branch already held the bytes, the **existing sha is recorded
  anyway**: "delivered" is about the bytes, not about whether we happened to
  create a commit.
"""

from __future__ import annotations

import pytest

from app.delivery import errors
from app.delivery.bootstrap import bootstrap
from app.delivery.push import push_artifacts
from tests.delivery_helpers import (
    DictCatalog,
    FakeGitHub,
    make_bare_remote,
    make_tools,
    make_worktree,
    remote_branches,
    remote_commit_messages,
    remote_files,
    remote_log,
)
from tests.target_helpers import CONFIG

BRANCH = "qa/SCRUM-1-checkout"


@pytest.fixture()
def env(tmp_path):
    """A head-revision-shaped source whose remote is bootstrapped on master."""
    source = make_worktree(tmp_path / "source")
    remote = make_bare_remote(tmp_path)
    bootstrap("demo", tools=make_tools(source, remote, FakeGitHub(has_commits=False)))
    return source, remote


def ready_tools(source, remote, gh=None, catalog=None):
    return make_tools(
        source, remote, gh or FakeGitHub(has_commits=True), catalog=catalog
    )


def test_delivery_pushes_the_head_revision_and_opens_a_pr(env):
    source, remote = env
    gh = FakeGitHub(has_commits=True)
    result = push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, gh))

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
    assert "seed.spec.ts" in files
    assert "playwright.config.ts" in files
    assert not any(f.startswith("apps/") for f in files)


def test_the_delivered_commit_is_recorded_on_the_revision(env):
    source, remote = env
    catalog = DictCatalog(source, CONFIG)

    result = push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, catalog=catalog))

    assert len(result.delivered_sha) == 40
    assert catalog.delivered == [result.delivered_sha]
    assert catalog.state("demo").delivered is True


def test_the_workspace_is_materialized_per_operation(env):
    """Created and removed per push, so what we push is provably the revision we
    record rather than whatever a long-lived mount happened to hold."""
    source, remote = env
    catalog = DictCatalog(source, CONFIG)

    push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, catalog=catalog))
    push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, catalog=catalog))

    assert catalog.materialized == 2


def test_re_delivery_appends_a_commit_and_updates_the_pr(env):
    """Never a force-push: it would destroy the PR's review threads."""
    source, remote = env
    gh = FakeGitHub(has_commits=True)
    push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, gh))
    first_log = remote_log(remote, BRANCH)

    (source / "tests" / "checkout" / "cart.spec.ts").write_text("// cart v2\n")
    result = push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, gh))

    assert result.pr_created is False
    assert gh.updated == [1]
    log = remote_log(remote, BRANCH)
    assert len(log) == len(first_log) + 1
    assert log[-len(first_log) :] == first_log, "history was appended to, not rewritten"


def test_a_deleted_test_disappears_from_the_branch(env):
    """The story's tests folder is replaced wholesale, so a removal propagates."""
    source, remote = env
    gh = FakeGitHub(has_commits=True)
    push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, gh))
    assert "tests/checkout/pay.spec.ts" in remote_files(remote, BRANCH)

    (source / "tests" / "checkout" / "pay.spec.ts").unlink()
    push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, gh))

    files = remote_files(remote, BRANCH)
    assert "tests/checkout/pay.spec.ts" not in files
    assert "tests/checkout/cart.spec.ts" in files


def test_a_file_the_revision_does_not_name_is_left_alone(env):
    """Customer drift is a non-event (DESIGN.md §7): a delivery writes what the
    revision holds and does not wipe what it does not."""
    source, remote = env
    gh = FakeGitHub(has_commits=True)
    push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, gh))

    # Something the customer added, on the story branch.
    import subprocess

    subprocess.run(
        ["git", "clone", "--branch", BRANCH, str(remote), "clone"],
        cwd=str(source.parent), check=True, capture_output=True,
    )
    clone = source.parent / "clone"
    (clone / "CONTRIBUTING.md").write_text("# ours\n")
    for args in (
        ["add", "-A"],
        ["-c", "user.name=c", "-c", "user.email=c@e", "commit", "-m", "theirs"],
        ["push", "origin", BRANCH],
    ):
        subprocess.run(["git", *args], cwd=str(clone), check=True, capture_output=True)

    (source / "tests" / "checkout" / "cart.spec.ts").write_text("// cart v3\n")
    push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, gh))

    assert "CONTRIBUTING.md" in remote_files(remote, BRANCH)


def test_unchanged_artifacts_make_no_new_commit_but_still_sync_the_pr(env):
    source, remote = env
    gh = FakeGitHub(has_commits=True)
    push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, gh))
    before = remote_log(remote, BRANCH)

    result = push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, gh))

    assert result.committed is False
    assert "no new commit" in result.message
    assert remote_log(remote, BRANCH) == before
    assert gh.updated == [1], "the PR is still synced"


def test_an_unchanged_delivery_records_the_same_sha(env):
    """"Delivered" is about the bytes, not about whether we created a commit."""
    source, remote = env
    catalog = DictCatalog(source, CONFIG)
    gh = FakeGitHub(has_commits=True)

    first = push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, gh, catalog))
    second = push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, gh, catalog))

    assert second.committed is False
    assert second.delivered_sha == first.delivered_sha
    assert catalog.delivered == [first.delivered_sha, first.delivered_sha]


def test_run_id_lands_in_the_commit_and_the_pr_body(env):
    source, remote = env
    gh = FakeGitHub(has_commits=True)
    push_artifacts(
        "demo", "SCRUM-1", run_id="run-42", tools=ready_tools(source, remote, gh)
    )

    assert remote_log(remote, BRANCH)[0] == "feat(tests): SCRUM-1 Checkout Flow"
    assert "Run-ID: run-42" in remote_commit_messages(remote, BRANCH)
    assert "Run-ID: run-42" in gh.last_body


def test_a_body_file_overrides_the_default_pr_body(env, tmp_path):
    source, remote = env
    gh = FakeGitHub(has_commits=True)
    body = tmp_path / "body.md"
    body.write_text("Custom body.\n")

    push_artifacts(
        "demo", "SCRUM-1", body_file=body, tools=ready_tools(source, remote, gh)
    )

    assert gh.last_body == "Custom body.\n"


def test_delivery_without_a_test_suite_is_refused(env):
    """Nothing to deliver is an error, not an empty commit."""
    import shutil

    source, remote = env
    shutil.rmtree(source / "tests" / "checkout")

    with pytest.raises(errors.DeliveryError, match="no test suite"):
        push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote))


def test_delivery_of_an_unknown_story_is_refused(env):
    source, remote = env
    with pytest.raises(errors.DeliveryError, match="exactly one"):
        push_artifacts("demo", "SCRUM-999", tools=ready_tools(source, remote))


def test_delivery_from_a_target_with_no_revision_is_refused(env):
    source, remote = env
    catalog = DictCatalog(source, CONFIG, rev=None)

    with pytest.raises(errors.DeliveryError, match="no head revision"):
        push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote, catalog=catalog))


def test_dry_run_neither_pushes_nor_opens_a_pr(env):
    source, remote = env
    gh = FakeGitHub(has_commits=True)
    before = remote_branches(remote)

    result = push_artifacts(
        "demo", "SCRUM-1", dry_run=True, tools=ready_tools(source, remote, gh)
    )

    assert result.committed is False
    assert result.delivered_sha == ""
    assert "(dry-run)" in result.message
    assert remote_branches(remote) == before
    assert gh.created == []


def test_a_dry_run_records_nothing(env):
    source, remote = env
    catalog = DictCatalog(source, CONFIG)

    push_artifacts(
        "demo", "SCRUM-1", dry_run=True, tools=ready_tools(source, remote, catalog=catalog)
    )

    assert catalog.delivered == []


def test_a_story_with_no_plan_still_delivers(env):
    """A plan is step 2's output; a story delivered without one is incomplete,
    not broken."""
    source, remote = env
    (source / "specs" / "SCRUM-1-checkout-test-plan.md").unlink()

    result = push_artifacts("demo", "SCRUM-1", tools=ready_tools(source, remote))

    files = remote_files(remote, BRANCH)
    assert result.committed is True
    assert "specs/SCRUM-1-checkout-test-plan.md" not in files
    assert "tests/checkout/cart.spec.ts" in files


def test_no_delivery_function_reads_config_or_a_credential_outside_tools(env):
    """Structural: the seam is the only way in. A function reaching for
    `os.environ` or `config.repo_root()` would be reaching around it."""
    from pathlib import Path

    from app.delivery import bootstrap as bootstrap_mod
    from app.delivery import push as push_mod
    from app.delivery import render as render_mod
    from app.delivery import reset as reset_mod

    for module in (push_mod, bootstrap_mod, reset_mod, render_mod):
        source_text = Path(module.__file__).read_text()
        assert "os.environ" not in source_text, module.__name__
        assert "repo_root" not in source_text, module.__name__
        assert "token_from_env" not in source_text, module.__name__
