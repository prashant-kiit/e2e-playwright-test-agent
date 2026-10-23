"""Resolve what gets delivered: targets, stories and the infra file list.

This module owns the naming contract the whole harness is built on -- the
derivations that scripts/qa-lib.sh and scripts/push-artifacts.sh did with jq and
shell parameter expansion. app/apphub.py imports the regexes from here so there
is exactly one definition of "what a story file is called".

P2's tracked tree lives here for the same reason: snapshotting and delivery must
not drift about what the product versions, and this module already owns the
infra list and the story-file naming both of them need.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .. import config
from .errors import DeliveryError

# A story heading: "# User Story: SCRUM-202 - Account Sign-up Form"
HEADING = re.compile(r"#\s*(?:User Story:\s*)?([A-Za-z]+-\d+)\s*[-–]\s*(.+)")
# A story file name is "<ID>-<slug>", where the ID itself contains a hyphen
# (SCRUM-201-auth -> id "SCRUM-201", slug "auth").
STORY_FILE = re.compile(r"^([A-Za-z]+-\d+)-(.+)$")
APP_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# The placeholder apps/_template/app.json ships with; never a real target.
PLACEHOLDER_REPO = "owner/repo-that-receives-the-tests"
DEFAULT_BRANCH = "master"

# Infra files that define a runnable target repo, workspace-relative and pushed
# at the same path. The single list used by bootstrap and the bootstrapped check
# (ports qa-lib.sh `qa_infra_files`).
INFRA_COMMON: tuple[str, ...] = (
    "package.json",
    "package-lock.json",
    "playwright.config.ts",
    ".gitignore",
    ".github/workflows/playwright.yml",
)


def infra_files(app: str) -> tuple[str, ...]:
    return INFRA_COMMON + (f"apps/{app}/app.json", f"apps/{app}/seed.spec.ts")


# --- the tracked tree (P2) ----------------------------------------------
#
# What a revision versions, for one target. The infra files above are shared on
# disk across every app but are **logically per-target**: each target's revision
# carries its own copy, which content addressing makes free.

# The app's own tree content, target-relative: single files, then directories
# with the glob that defines what counts inside them. The globs are not `**`
# by accident -- stories and plans are markdown, and anything else that lands
# in those folders is somebody's scratch file, not something to version and
# (in P3) hydrate back into a worktree.
TRACKED_APP_FILES: tuple[str, ...] = ("seed.spec.ts",)
TRACKED_APP_TREES: tuple[tuple[str, str], ...] = (
    ("user-stories", "*.md"),
    ("specs", "*.md"),
    ("tests", "**/*"),
)

# Never tree content wherever they turn up. artifacts.py skips .DS_Store for the
# same reason; a snapshot has more at stake, since a stray file here becomes
# versioned content that a later phase writes back out.
UNTRACKED_NAMES: frozenset[str] = frozenset({".DS_Store", "Thumbs.db", ".gitkeep"})
UNTRACKED_SUFFIXES: tuple[str, ...] = ("~", ".swp", ".swo", ".orig", ".rej")

# Never tree content, even though they sit inside apps/<app>/ (DESIGN.md §4):
#   app.json      SaaS-internal config, rendered from Postgres in P3, and it
#                 must never become something a revision delivers;
#   reports/      the agent's reports and evidence screenshots -- run output,
#                 which is why push.py already declines to deliver them;
#   the rest      run artifacts, keyed by run in the artifacts table instead.
UNTRACKED_APP_PATHS: frozenset[str] = frozenset(
    {
        "app.json",
        "session.jsonl",
        "reports",
        "node_modules",
        "test-results",
        "playwright-report",
    }
)


def app_dir(app: str) -> Path:
    return config.repo_root() / "apps" / app


def tracked_path_on_disk(app: str, path: str) -> Path:
    """Where a target-relative tracked path lives in today's monorepo layout.

    The one mapping function between the stored shape and the on-disk shape --
    and the same one P3's hydrate needs, run the other way. Stored paths are
    target-relative on purpose: the revision is a whole-worktree snapshot of one
    target, so baking this repo's apps/<app>/ layout into the durable record
    would put a path migration in front of P3.
    """
    if path in INFRA_COMMON:
        return config.repo_root() / path
    return app_dir(app) / path


def tracked_tree(app: str) -> list[tuple[str, Path]]:
    """Every tracked file for `app`, as (target-relative path, path on disk).

    Sorted by path and free of directory iteration order, so two walks of the
    same tree agree. A tracked file that does not exist is omitted rather than
    an error: the tree describes what is there, and a target missing its
    workflow file is a bootstrap problem, not a snapshot failure.
    """
    found: dict[str, Path] = {}

    for rel in INFRA_COMMON:
        path = config.repo_root() / rel
        if path.is_file():
            found[rel] = path

    base = app_dir(app)
    for rel in TRACKED_APP_FILES:
        if not _is_untracked(rel) and (base / rel).is_file():
            found[rel] = tracked_path_on_disk(app, rel)

    for tree, pattern in TRACKED_APP_TREES:
        root = base / tree
        if not root.is_dir():
            continue
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if _is_untracked(rel):
                continue
            found[rel] = tracked_path_on_disk(app, rel)

    return sorted(found.items())


def _is_untracked(rel: str) -> bool:
    """Whether a target-relative path is excluded from the tracked tree.

    Checked per path segment rather than per prefix, so a `node_modules/`
    nested inside a test folder is excluded as surely as one at the top.
    """
    parts = rel.split("/")
    if any(part in UNTRACKED_APP_PATHS or part in UNTRACKED_NAMES for part in parts):
        return True
    return parts[-1].endswith(UNTRACKED_SUFFIXES)


def app_json_path(app: str) -> Path:
    return config.repo_root() / "apps" / app / "app.json"


def read_app_json(app: str) -> dict:
    path = app_json_path(app)
    if not path.exists():
        raise DeliveryError(f"no such app: apps/{app}/app.json not found")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise DeliveryError(f"apps/{app}/app.json is not valid JSON: {exc}") from exc


@dataclass(frozen=True)
class TargetRef:
    app: str
    repo: str
    branch: str


def resolve_target(app: str) -> TargetRef:
    """Ports `qa_resolve`, including its refusal to act on the placeholder."""
    if not app:
        raise DeliveryError("an <app> is required (a folder under apps/)")
    data = read_app_json(app)
    repo = (data.get("targetRepo") or "").strip()
    branch = (data.get("targetBranch") or "").strip() or DEFAULT_BRANCH
    if not repo or repo == PLACEHOLDER_REPO:
        raise DeliveryError(f'apps/{app}/app.json: set a real "targetRepo" (owner/repo)')
    if "/" not in repo:
        raise DeliveryError(f'apps/{app}/app.json: "targetRepo" must be owner/repo, got {repo!r}')
    return TargetRef(app=app, repo=repo, branch=branch)


@dataclass(frozen=True)
class StoryRef:
    app: str
    story_id: str
    slug: str
    title: str
    branch: str
    pr_title: str
    story_rel: str
    plan_rel: str
    tests_rel: str


def resolve_story(app: str, story_id: str) -> StoryRef:
    """Derive every delivered path from the story's filename.

    Exactly one apps/<app>/user-stories/<ID>-*.md must match -- an ambiguous
    glob was a hard error in push-artifacts.sh and stays one here.
    """
    if not story_id:
        raise DeliveryError("a <STORY_ID> is required (e.g. SCRUM-201)")
    stories_dir = config.repo_root() / "apps" / app / "user-stories"
    matches = sorted(stories_dir.glob(f"{story_id}-*.md")) if stories_dir.exists() else []
    if len(matches) != 1:
        raise DeliveryError(
            f"expected exactly one apps/{app}/user-stories/{story_id}-*.md "
            f"(found {len(matches)})"
        )
    story_file = matches[0]
    base = story_file.stem
    slug = base[len(story_id) + 1 :] if base.startswith(f"{story_id}-") else base
    title = _story_title(story_file) or slug
    return StoryRef(
        app=app,
        story_id=story_id,
        slug=slug,
        title=title,
        branch=f"qa/{story_id}-{slug}",
        pr_title=f"{story_id}: {title} E2E test suite",
        story_rel=f"apps/{app}/user-stories/{base}.md",
        plan_rel=f"apps/{app}/specs/{story_id}-{slug}-test-plan.md",
        tests_rel=f"apps/{app}/tests/{slug}",
    )


def _story_title(path: Path) -> str | None:
    """The title from the story's first heading.

    push-artifacts.sh used ${heading#*- }; the HEADING regex gets the same
    answer and tolerates an en-dash, so it is preferred with the shell
    behaviour kept as the fallback.
    """
    for line in path.read_text().splitlines():
        if not line.startswith("#"):
            continue
        match = HEADING.match(line)
        if match:
            return match.group(2).strip()
        if "- " in line:
            return line.split("- ", 1)[1].strip() or None
        return line.lstrip("# ").strip() or None
    return None


def pr_body(story: StoryRef, run_id: str | None = None) -> str:
    suffix = f" Run-ID: {run_id}" if run_id else ""
    return (
        f"Automated E2E tests for {story.story_id} ({story.title}).{suffix}\n\n"
        "Results report is generated by CI (the run's Job Summary and the "
        "playwright-report artifact)."
    )


def commit_message(story: StoryRef, run_id: str | None = None) -> str:
    run_line = f"\nRun-ID: {run_id}" if run_id else ""
    return (
        f"feat(tests): {story.story_id} {story.title}\n\n"
        f"Sync story, test plan and test suite from the QA agent repo.{run_line}\n\n"
        f"Resolves {story.story_id}"
    )
