"""Deliver a story's suite to its target repo as a PR, from the head revision.

The approved push materializes the target's **head revision** into a temporary
tree, writes it onto branch `qa/<STORY_ID>-<slug>`, squashes it into one commit,
opens or updates a PR into the target branch, and records `delivered_sha` on the
revision it delivered. "What exactly did we push, and from what?" is a row.

Three properties are deliberate and must not be "simplified" away:

  - **the branch is appended to, never force-pushed** (DESIGN.md decision 10) --
    force-pushing a customer's branch destroys PR review threads;
  - **the story's tests folder is replaced wholesale**, so a test deleted in the
    harness disappears from the branch. Everything else is written, not
    replaced: wiping paths the revision does not name would delete whatever a
    customer added, and customer drift is a non-event (DESIGN.md §7), not
    something a delivery should silently clean up;
  - **infra is not pushed here** (that is bootstrap.py), though the materialized
    tree carries it, so the bytes agree either way.

What we push is provably the revision we record, because the tree is built from
that revision rather than read off a mount that may have moved since.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import DeliveryError
from .render import (
    StoryRef,
    commit_message,
    pr_body,
    resolve_story,
    target_ref,
    tracked_tree,
)
from .tools import Tools, default_tools


@dataclass(frozen=True)
class PushResult:
    app: str
    story_id: str
    repo: str
    branch: str
    committed: bool
    delivered_sha: str
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
    cfg = tools.catalog.config(app)
    target = target_ref(cfg)

    with tools.catalog.materialize(app) as source:
        paths = [path for path, _on_disk in tracked_tree(source)]
        story = resolve_story(source, story_id, paths=paths, app=app)

        if not (source / story.tests_rel).is_dir():
            raise DeliveryError(
                f"no test suite at {story.tests_rel} in the head revision - run the "
                f"QA flow (steps 4-5) first"
            )

        if dry_run:
            return PushResult(
                app=app,
                story_id=story_id,
                repo=target.repo,
                branch=story.branch,
                committed=False,
                delivered_sha="",
                pr_url="",
                pr_number=None,
                pr_created=False,
                message=(
                    f"(dry-run) would push revision {tools.catalog.state(app).rev} onto "
                    f"{story.branch} and open/update a PR into {target.branch} "
                    f'titled "{story.pr_title}"'
                ),
            )

        tmp = Path(tempfile.mkdtemp(prefix="qa-push-"))
        try:
            url = tools.clone_url(target.repo)
            work = tmp / "repo"
            repo_git = tools.git.clone(url, work, branch=target.branch, depth=1)

            # Start the story branch from its remote state if it exists, else
            # from the target branch. This is what makes re-delivery an append.
            if repo_git.remote_branch_exists("origin", story.branch):
                repo_git.fetch_branch("origin", story.branch, depth=1)
                repo_git.checkout_new(story.branch, "FETCH_HEAD")
            else:
                repo_git.checkout_new(story.branch)

            _write_revision(source, work, paths, story)

            repo_git.add_all()
            committed = repo_git.has_staged_changes()
            if committed:
                repo_git.commit(commit_message(story, run_id))
                repo_git.push("origin", story.branch, set_upstream=True)
            # The sha of the delivered bytes, whether or not we made a commit:
            # "delivered" is about the bytes, not about whether the branch
            # happened to already hold them.
            delivered_sha = repo_git.head_sha()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    tools.catalog.record_delivered(app, delivered_sha)

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
        delivered_sha=delivered_sha,
        pr_url=pr.url,
        pr_number=pr.number,
        pr_created=created,
        message=(
            f"PR: {pr.url}"
            if committed
            else f"branch already matches the head revision - no new commit. PR: {pr.url}"
        ),
    )


def _write_revision(
    source: Path, work: Path, paths: list[str], story: StoryRef
) -> None:
    """Write every file of the materialized revision into the clone.

    The story's tests directory is removed first so a deleted test disappears
    from the branch -- the one wholesale replacement, and the one the harness
    actually authors. Nothing else is deleted: a path the revision does not name
    is either infra bootstrap put there or something the customer added, and
    neither is a delivery's to remove.
    """
    shutil.rmtree(work / story.tests_rel, ignore_errors=True)

    for rel in paths:
        dest = work / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / rel, dest)


def _resolve_body(
    story: StoryRef, body: str | None, body_file: Path | None, run_id: str | None
) -> str:
    if body:
        return body
    if body_file is not None and body_file.is_file():
        return body_file.read_text()
    return pr_body(story, run_id)
