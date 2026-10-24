"""Bootstrap (or re-bootstrap) a target repo's infra. SYNC mode: the harness is
the source of truth, and files only ever move outward (DESIGN.md invariant 2).

Pushes the infra entries so the target repo is a runnable Playwright project
before any story lands in it. An empty target repo gets its first commit on its
branch; an existing one gets only the files that differ, and nothing at all when
already in sync. Story artifacts are not touched -- that is push.py.

DESIGN.md §7 folds this into the first delivery under the same approval, which
is why `ensure_bootstrapped` exists as a separate, callable step.

**"Bootstrapped" is a Postgres query now.** It used to be two REST calls asking
GitHub whether the branch carried an `app.json` and a `playwright.config.ts`. It
is `any revision of this target carries a delivered_sha`, which is the same
answer for everyone and does not depend on the network. If a customer wipes
their repo it stays true and the next delivery appends over the drift: customer
drift is a non-event, and its deliberate repair is the "re-sync infra" action
(DESIGN.md §7), not a silent re-bootstrap.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .render import INFRA_DESTINATIONS, INFRA_ENTRIES, TargetRef, target_ref
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
    """Read-only, and read from the database. Never writes, never dials out."""
    tools = tools or default_tools()
    ref = target_ref(tools.catalog.config(app))
    return tools.state(app).bootstrapped, ref


def ensure_bootstrapped(app: str, *, tools: Tools | None = None) -> BootstrapResult | None:
    """Bootstrap only if we have never delivered to this repo; None otherwise.

    This is what makes one approval mean "set the repo up and deliver this
    story" (DESIGN.md decision 16).
    """
    tools = tools or default_tools()
    if tools.state(app).bootstrapped:
        return None
    return bootstrap(app, tools=tools)


def bootstrap(app: str, *, dry_run: bool = False, tools: Tools | None = None) -> BootstrapResult:
    tools = tools or default_tools()
    cfg = tools.catalog.config(app)
    target = target_ref(cfg)
    files = INFRA_DESTINATIONS

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

        # Every entry from its source: a template in this package, or the
        # renderer that reads the target's row. Nothing is read off a mount.
        for entry in INFRA_ENTRIES:
            dest = work / entry.destination
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(entry.render(cfg))

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
