"""Deliver one story's artifacts to its app's target repo as a PR.

SYNC mode: the story, test plan and test suite are copied from this repo onto
branch qa/<STORY_ID>-<slug>, then a PR is opened or updated into <targetBranch>.
The story's tests folder is replaced wholesale so deletions propagate.

Two properties are deliberate and must not be "simplified" away:
  - the branch is appended to, never force-pushed (DESIGN.md decision 10) --
    force-pushing a customer's branch destroys PR review threads;
  - infra is not pushed here (that is bootstrap.py).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .bootstrap import require_bootstrapped
from .errors import DeliveryError
from .render import StoryRef, commit_message, pr_body, resolve_story
from .tools import Tools, default_tools


@dataclass(frozen=True)
class PushResult:
    app: str
    story_id: str
    repo: str
    branch: str
    committed: bool
    pr_url: str
    pr_number: int | None
    pr_created: bool
    message: str


def push_artifacts(
    app: str,
    story_id: str,
    *,
    body: str | None = None,
    body_file: Path | None = None,
    run_id: str | None = None,
    dry_run: bool = False,
    tools: Tools | None = None,
) -> PushResult:
    tools = tools or default_tools()
    story = resolve_story(app, story_id)

    tests_src = tools.workspace / story.tests_rel
    if not tests_src.is_dir():
        raise DeliveryError(
            f"no test suite at {story.tests_rel} - run the QA flow (steps 4-5) first"
        )

    target = require_bootstrapped(app, tools=tools)

    if dry_run:
        return PushResult(
            app=app,
            story_id=story_id,
            repo=target.repo,
            branch=story.branch,
            committed=False,
            pr_url="",
            pr_number=None,
            pr_created=False,
            message=(
                f"(dry-run) would push {story.story_rel}, {story.plan_rel} and "
                f"{story.tests_rel}/ onto {story.branch} and open/update a PR into "
                f'{target.branch} titled "{story.pr_title}"'
            ),
        )

    tmp = Path(tempfile.mkdtemp(prefix="qa-push-"))
    try:
        url = tools.clone_url(target.repo)
        work = tmp / "repo"
        repo_git = tools.git.clone(url, work, branch=target.branch, depth=1)

        # Start the story branch from its remote state if it exists, else from
        # the target branch. This is what makes re-delivery an append.
        if repo_git.remote_branch_exists("origin", story.branch):
            repo_git.fetch_branch("origin", story.branch, depth=1)
            repo_git.checkout_new(story.branch, "FETCH_HEAD")
        else:
            repo_git.checkout_new(story.branch)

        _sync_story_files(tools.workspace, work, story)

        repo_git.add_all()
        committed = repo_git.has_staged_changes()
        if committed:
            repo_git.commit(commit_message(story, run_id))
            repo_git.push("origin", story.branch, set_upstream=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    text = _resolve_body(story, body, body_file, run_id)
    existing = tools.gh.find_pr(target.repo, story.branch)
    if existing is not None:
        pr = tools.gh.update_pr(
            target.repo, existing.number, title=story.pr_title, body=text
        )
        created = False
    else:
        pr = tools.gh.create_pr(
            target.repo,
            head=story.branch,
            base=target.branch,
            title=story.pr_title,
            body=text,
        )
        created = True

    return PushResult(
        app=app,
        story_id=story_id,
        repo=target.repo,
        branch=story.branch,
        committed=committed,
        pr_url=pr.url,
        pr_number=pr.number,
        pr_created=created,
        message=(
            f"PR: {pr.url}"
            if committed
            else f"branch already matches the agent repo - no new commit. PR: {pr.url}"
        ),
    )


def _sync_story_files(workspace: Path, work: Path, story: StoryRef) -> None:
    """Replace the story's files wholesale, so anything removed in the agent
    repo is removed on the branch too."""
    shutil.rmtree(work / story.tests_rel, ignore_errors=True)
    (work / story.plan_rel).unlink(missing_ok=True)

    for rel in (story.story_rel, story.plan_rel):
        (work / rel).parent.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(workspace / story.story_rel, work / story.story_rel)

    plan_src = workspace / story.plan_rel
    if plan_src.is_file():
        shutil.copyfile(plan_src, work / story.plan_rel)

    shutil.copytree(workspace / story.tests_rel, work / story.tests_rel)


def _resolve_body(
    story: StoryRef, body: str | None, body_file: Path | None, run_id: str | None
) -> str:
    if body:
        return body
    if body_file is not None and body_file.is_file():
        return body_file.read_text()
    return pr_body(story, run_id)
