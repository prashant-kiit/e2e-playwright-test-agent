"""Bootstrap (or re-bootstrap) an app's target repo. SYNC mode: this repo is the
source of truth, and files only ever move outward (DESIGN.md invariant 2).

Pushes the infra files so the target matches the agent repo exactly. An empty
target repo gets its first commit on <targetBranch>; an existing one gets only
the files that differ, and nothing at all when already in sync. Story artifacts
are not touched -- that is push.py.

DESIGN.md §7 folds this into the first delivery under the same approval, which
is why `ensure_bootstrapped` exists as a separate, callable step.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import DeliveryError, NotBootstrapped
from .render import (
    INFRA_ENTRIES,
    TargetRef,
    infra_files,
    read_target_config,
    resolve_target,
)
from .tools import Tools, default_tools


@dataclass(frozen=True)
class BootstrapResult:
    app: str
    repo: str
    branch: str
    mode: str  # "bootstrap" | "re-bootstrap" | "in-sync" | "dry-run"
    files: tuple[str, ...]
    changes: str
    pushed: bool
    message: str


def is_bootstrapped(app: str, *, tools: Tools | None = None) -> tuple[bool, TargetRef]:
    """Read-only check (ports check-bootstrapped.sh). Never writes."""
    tools = tools or default_tools()
    target = resolve_target(app)
    return tools.gh.is_bootstrapped(target.repo, target.app, target.branch), target


def ensure_bootstrapped(app: str, *, tools: Tools | None = None) -> BootstrapResult | None:
    """Bootstrap only if the target branch lacks infra; None when already ready."""
    tools = tools or default_tools()
    ready, _ = is_bootstrapped(app, tools=tools)
    if ready:
        return None
    return bootstrap(app, tools=tools)


def require_bootstrapped(app: str, *, tools: Tools | None = None) -> TargetRef:
    ready, target = is_bootstrapped(app, tools=tools)
    if not ready:
        raise NotBootstrapped(target.repo, target.branch, target.app)
    return target


def bootstrap(app: str, *, dry_run: bool = False, tools: Tools | None = None) -> BootstrapResult:
    tools = tools or default_tools()
    target = resolve_target(app)
    files = infra_files(app)

    if dry_run:
        return BootstrapResult(
            app=app,
            repo=target.repo,
            branch=target.branch,
            mode="dry-run",
            files=files,
            changes="",
            pushed=False,
            message=(
                f"(dry-run) would sync {len(files)} infra files into "
                f"{target.repo}@{target.branch}"
            ),
        )

    # The infra entries come from the templates in this package and from the
    # generated config's renderer; only the two app-scoped files still come off
    # the workspace. Fail before cloning if one of those is missing.
    cfg = read_target_config(app)
    workspace_files = tuple(f for f in files if f.startswith(f"apps/{app}/"))
    for rel in workspace_files:
        if not (tools.workspace / rel).is_file():
            raise DeliveryError(f"missing workspace file: {rel}")

    tmp = Path(tempfile.mkdtemp(prefix="qa-bootstrap-"))
    try:
        url = tools.clone_url(target.repo)
        work = tmp / "repo"

        if tools.gh.repo_has_commits(target.repo):
            mode = "re-bootstrap"
            repo_git = tools.git.clone(url, work, branch=target.branch, depth=1)
        else:
            mode = "bootstrap"
            repo_git = tools.git.clone(url, work, depth=1)
            repo_git.checkout_new(target.branch)

        for entry in INFRA_ENTRIES:
            dest = work / entry.destination
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(entry.render(cfg))

        for rel in workspace_files:
            dest = work / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tools.workspace / rel, dest)

        repo_git.add_all()
        if not repo_git.has_staged_changes():
            return BootstrapResult(
                app=app,
                repo=target.repo,
                branch=target.branch,
                mode="in-sync",
                files=files,
                changes="",
                pushed=False,
                message="already in sync - nothing to push.",
            )

        changes = repo_git.diff_cached_name_status()
        repo_git.commit(f"chore: {mode} Playwright project ({app})")
        repo_git.push("origin", target.branch, set_upstream=True)
        return BootstrapResult(
            app=app,
            repo=target.repo,
            branch=target.branch,
            mode=mode,
            files=files,
            changes=changes,
            pushed=True,
            message=f"done ({mode}): pushed to {target.repo}@{target.branch}",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
