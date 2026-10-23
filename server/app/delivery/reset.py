"""Reset an app's target repo to a fresh, empty state. DESTRUCTIVE.

Replaces <targetBranch> with a single empty commit (files AND history gone) and
deletes every other branch, which closes their PRs. The agent repo is untouched,
and this does not re-bootstrap.

reset-target.sh read a typed confirmation from a TTY. There is no TTY behind a
portal action, so the caller must echo the repo name back in `confirm_repo` --
the guard becomes part of the contract instead of being lost in the port
(DESIGN.md §11: portal-gated, double-confirm).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfirmationMismatch
from .render import resolve_target
from .tools import Tools, default_tools


@dataclass(frozen=True)
class ResetResult:
    app: str
    repo: str
    branch: str
    already_empty: bool
    reset_branch: bool
    deleted_branches: tuple[str, ...]
    failed_branches: tuple[str, ...]
    message: str


def plan_reset(app: str, *, tools: Tools | None = None) -> ResetResult:
    """What a reset would do, changing nothing (the --dry-run path)."""
    tools = tools or default_tools()
    target = resolve_target(app)

    if not tools.gh.repo_has_commits(target.repo):
        return ResetResult(
            app=app,
            repo=target.repo,
            branch=target.branch,
            already_empty=True,
            reset_branch=False,
            deleted_branches=(),
            failed_branches=(),
            message=f"already empty: {target.repo} has no commits.",
        )

    others = tuple(
        b
        for b in tools.git.ls_remote_heads(tools.clone_url(target.repo))
        if b != target.branch
    )
    return ResetResult(
        app=app,
        repo=target.repo,
        branch=target.branch,
        already_empty=False,
        reset_branch=False,
        deleted_branches=others,
        failed_branches=(),
        message=(
            f"(dry-run) would reset '{target.branch}' to a single empty commit and "
            f"delete {len(others)} other branch(es)."
        ),
    )


def reset_target(
    app: str,
    *,
    confirm_repo: str,
    dry_run: bool = False,
    tools: Tools | None = None,
) -> ResetResult:
    tools = tools or default_tools()
    target = resolve_target(app)

    if dry_run:
        return plan_reset(app, tools=tools)

    if confirm_repo != target.repo:
        raise ConfirmationMismatch(
            f"confirmation did not match; aborted. Expected {target.repo!r}, "
            f"got {confirm_repo!r}"
        )

    planned = plan_reset(app, tools=tools)
    if planned.already_empty:
        return planned

    tmp = Path(tempfile.mkdtemp(prefix="qa-reset-"))
    try:
        url = tools.clone_url(target.repo)
        work = tmp / "repo"
        repo_git = tools.git.clone(url, work, depth=1)

        # An empty orphan commit, force-pushed onto the target branch. This is
        # the one place a force-push is correct: the operator asked for the
        # repo's history to be destroyed.
        repo_git.checkout_orphan("fresh")
        repo_git.remove_all_cached()
        repo_git.commit(
            f"chore: reset target repo for a fresh start ({app})", allow_empty=True
        )
        repo_git.rename_branch(target.branch)
        repo_git.push("origin", target.branch, force=True)

        deleted: list[str] = []
        failed: list[str] = []
        for branch in planned.deleted_branches:
            if repo_git.delete_remote_branch("origin", branch):
                deleted.append(branch)
            else:
                failed.append(branch)  # protected, or the repo's default branch
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return ResetResult(
        app=app,
        repo=target.repo,
        branch=target.branch,
        already_empty=False,
        reset_branch=True,
        deleted_branches=tuple(deleted),
        failed_branches=tuple(failed),
        message=(
            f"reset: '{target.branch}' is now a single empty commit; "
            f"deleted {len(deleted)} branch(es)"
            + (f", could not delete {len(failed)}" if failed else "")
        ),
    )
