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
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from ..package_data import templates_dir
from ..target_config import TargetConfig
from .errors import DeliveryError

# A story heading: "# User Story: SCRUM-202 - Account Sign-up Form"
HEADING = re.compile(r"#\s*(?:User Story:\s*)?([A-Za-z]+-\d+)\s*[-–]\s*(.+)")
# A story file name is "<ID>-<slug>", where the ID itself contains a hyphen
# (SCRUM-201-auth -> id "SCRUM-201", slug "auth").
STORY_FILE = re.compile(r"^([A-Za-z]+-\d+)-(.+)$")

# The folders the agent's prompts name, and where the seed lands. One
# definition, because the prompts, the tracked tree and the delivered paths all
# have to agree about them.
STORIES_DIR = "user-stories"
PLANS_DIR = "specs"
TESTS_DIR = "tests"
SEED_DESTINATION = "seed.spec.ts"

# The infra templates and the seed, resolved from the installed package.
TEMPLATES_DIR = templates_dir()

# --- infra entries: (source, destination) ---------------------------------
#
# DESIGN.md decision 23. An entry's source is either a file under TEMPLATES_DIR
# or a **renderer** -- a function of the target's configuration. Its destination
# is the path in the hydrated worktree and in the customer's repo.
#
# Before P3 a template's source *was* its destination, which put
# `.github/workflows/playwright.yml` at a path GitHub Actions treats as a live
# workflow of this repository: a push to master made the harness install
# browsers and run customers' suites against live external sites. Splitting the
# two moves the source without changing a delivered byte.
#
# Do not neuter the `on:` triggers in the template instead of moving it: the
# delivered copy would inherit the dead trigger and never run in the customer's
# repo either, which is the exact failure the move prevents.

Renderer = Callable[[TargetConfig], str]


@dataclass(frozen=True)
class InfraEntry:
    """One infra file: where its bytes come from, and where they land."""

    destination: str
    template: str | None = None   # relative to TEMPLATES_DIR
    renderer: Renderer | None = None

    @property
    def generated(self) -> bool:
        """Whether this entry's bytes come from the target row rather than a file.

        Generated entries are re-rendered on every hydrate and re-rendered again
        before every ingest scan, which is what gives them exactly one author.
        """
        return self.renderer is not None

    def render(self, cfg: TargetConfig) -> str:
        if self.renderer is not None:
            return self.renderer(cfg)
        assert self.template is not None
        return (TEMPLATES_DIR / self.template).read_text()


def render_playwright_config(cfg: TargetConfig) -> str:
    """The target's `playwright.config.ts`, generated from its row.

    Single-target by construction, which is what makes the project names bare
    (`chromium`, not `<app>-chromium`) and what stops a project name or a test
    path from reaching another customer's tests. The same file is what the
    customer's CI runs, so it must not know about `apps/`.

    `baseURL` arrives from the database as operator input and is rendered into
    TypeScript source, so it goes through `json.dumps` rather than being
    interpolated: a quote in a base URL would otherwise be a code-injection
    point into the customer's repo.
    """
    base_url = json.dumps(cfg.base_url)
    return f"""// GENERATED FILE -- do not edit.
//
// Rendered from this target's configuration in Postgres on every hydrate, and
// re-rendered before every ingest, so edits here are discarded. Change the
// base URL in the portal instead; the change arrives as a tree diff and a new
// revision.
import {{ defineConfig, devices }} from '@playwright/test';

const baseURL = {base_url};

/* The orchestrator sets QA_RUN_DIR per run, so Playwright's output lands in the
 * run directory and never in this worktree -- the worktree is the tree a
 * revision is made of. */
const RUN_DIR = process.env.QA_RUN_DIR;
const outputPath = (name: string) => (RUN_DIR ? `${{RUN_DIR}}/${{name}}` : name);

export default defineConfig({{
  /* One target per worktree: the whole tree is this target's, seed included. */
  testDir: '.',
  outputDir: outputPath('test-results'),
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI
    ? 1
    : process.env.QA_WORKERS
      ? Number(process.env.QA_WORKERS)
      : undefined,
  /* open: 'never' so a failing local run does not block on the report server. */
  reporter: [
    ['list'],
    ['html', {{ open: 'never', outputFolder: outputPath('playwright-report') }}],
  ],
  use: {{
    /* Playwright's default is no limit; an agent driving the browser over MCP
     * would hang forever on a missing element. */
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    trace: 'on-first-retry',
  }},
  projects: [
    {{ name: 'chromium', use: {{ ...devices['Desktop Chrome'], baseURL }} }},
    {{ name: 'firefox', use: {{ ...devices['Desktop Firefox'], baseURL }} }},
    {{ name: 'webkit', use: {{ ...devices['Desktop Safari'], baseURL }} }},
    {{ name: 'mobile-chrome', use: {{ ...devices['Pixel 7'], baseURL }} }},
  ],
}});
"""


# The infra set that defines a runnable target repo (ports qa-lib.sh
# `qa_infra_files`). Shared on disk but **logically per-target**: each target's
# revision carries its own copy, which content addressing makes free.
INFRA_ENTRIES: tuple[InfraEntry, ...] = (
    InfraEntry("package.json", template="package.json"),
    InfraEntry("package-lock.json", template="package-lock.json"),
    InfraEntry("playwright.config.ts", renderer=render_playwright_config),
    # The template is `gitignore`, without the dot: a leading dot inside package
    # data is the kind of thing a packaging glob silently drops, and the
    # destination is what carries the name.
    InfraEntry(".gitignore", template="gitignore"),
    InfraEntry(".github/workflows/playwright.yml", template="workflows/playwright.yml"),
)

INFRA_DESTINATIONS: tuple[str, ...] = tuple(e.destination for e in INFRA_ENTRIES)
GENERATED_DESTINATIONS: tuple[str, ...] = tuple(
    e.destination for e in INFRA_ENTRIES if e.generated
)

# The seed a newly created target starts from, rendered into revision 1.
SEED_TEMPLATE = "seed.spec.ts"


def infra_entry(destination: str) -> InfraEntry:
    for entry in INFRA_ENTRIES:
        if entry.destination == destination:
            return entry
    raise KeyError(destination)


def write_infra(root: Path, cfg: TargetConfig, *, only_generated: bool = False) -> None:
    """Write the infra entries into `root` at their destination paths.

    `only_generated` is hydrate's render step and ingest's re-render: the
    generated entries overwrite whatever the revision held, while the template
    entries are revision content like any other file and are left alone.
    """
    for entry in INFRA_ENTRIES:
        if only_generated and not entry.generated:
            continue
        dest = root / entry.destination
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(entry.render(cfg))


# --- the tracked tree ------------------------------------------------------
#
# What a revision versions, for one target, inside a worktree root. P3 made it
# root-relative: the on-disk shape and the stored shape are the same shape, so
# the apps/<app>/ mapping function is gone. This is why P2 stored
# target-relative paths.

# The target's own tree content: single files, then directories with the glob
# that defines what counts inside them. The globs are not `**` by accident --
# stories and plans are markdown, and anything else that lands in those folders
# is somebody's scratch file, not something to version and hydrate back out.
TRACKED_APP_FILES: tuple[str, ...] = (SEED_DESTINATION,)
TRACKED_APP_TREES: tuple[tuple[str, str], ...] = (
    (STORIES_DIR, "*.md"),
    (PLANS_DIR, "*.md"),
    (TESTS_DIR, "**/*"),
)

# Never tree content wherever they turn up. artifacts.py skips .DS_Store for the
# same reason; a snapshot has more at stake, since a stray file here becomes
# versioned content that hydrate writes back into the next worktree.
UNTRACKED_NAMES: frozenset[str] = frozenset({".DS_Store", "Thumbs.db", ".gitkeep"})
UNTRACKED_SUFFIXES: tuple[str, ...] = ("~", ".swp", ".swo", ".orig", ".rej")

# Never tree content, even though they sit inside the worktree (DESIGN.md §4):
#   reports/      the agent's reports and evidence screenshots -- run output,
#                 which is why push.py already declines to deliver them;
#   the rest      run artifacts, keyed by run in the artifacts table instead.
#
# `app.json` left this list by ceasing to exist: config is a row now, rendered
# into the prompt and into the generated config, never a tree file.
UNTRACKED_APP_PATHS: frozenset[str] = frozenset(
    {
        "session.jsonl",
        "reports",
        "node_modules",
        "test-results",
        "playwright-report",
    }
)


def tracked_tree(root: Path) -> list[tuple[str, Path]]:
    """Every tracked file in `root`, as (root-relative path, path on disk).

    Sorted by path and free of directory iteration order, so two walks of the
    same tree agree. A tracked file that does not exist is omitted rather than
    an error: the tree describes what is there, and a worktree missing its
    workflow file is a hydrate problem, not a snapshot failure.
    """
    found: dict[str, Path] = {}

    for rel in INFRA_DESTINATIONS:
        path = root / rel
        if path.is_file():
            found[rel] = path

    for rel in TRACKED_APP_FILES:
        if not _is_untracked(rel) and (root / rel).is_file():
            found[rel] = root / rel

    for tree, pattern in TRACKED_APP_TREES:
        base = root / tree
        if not base.is_dir():
            continue
        for path in base.glob(pattern):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if _is_untracked(rel):
                continue
            found[rel] = path

    return sorted(found.items())


def _is_untracked(rel: str) -> bool:
    """Whether a root-relative path is excluded from the tracked tree.

    Checked per path segment rather than per prefix, so a `node_modules/`
    nested inside a test folder is excluded as surely as one at the top.
    """
    parts = rel.split("/")
    if any(part in UNTRACKED_APP_PATHS or part in UNTRACKED_NAMES for part in parts):
        return True
    return parts[-1].endswith(UNTRACKED_SUFFIXES)


def infra_files() -> tuple[str, ...]:
    """Every path bootstrap puts in the target repo, at its destination."""
    return INFRA_DESTINATIONS


@dataclass(frozen=True)
class TargetRef:
    """Where a target's tests are delivered. A projection of its row."""

    app: str
    repo: str
    branch: str


def target_ref(cfg: TargetConfig) -> TargetRef:
    """The delivery coordinates a target's configuration names.

    There is no validation here any more. An empty or placeholder target repo is
    refused on the **write** path (app/target_config.py), where the operator who
    typed it is still around to be told, rather than hours later when a delivery
    goes to read a file.
    """
    return TargetRef(app=cfg.app, repo=cfg.target_repo, branch=cfg.target_branch)


@dataclass(frozen=True)
class StoryRef:
    """One story's derived paths and names, all worktree-relative.

    P3 made them worktree-relative: `user-stories/...` rather than
    `apps/<app>/user-stories/...`. The stored shape, the hydrated shape and the
    delivered shape are now one shape, so the agent's prompts name folders
    rather than a path that encodes this repo's monorepo layout.
    """

    app: str
    story_id: str
    slug: str
    title: str
    branch: str
    pr_title: str
    story_rel: str
    plan_rel: str
    tests_rel: str
    seed_rel: str = SEED_DESTINATION


def story_filename(paths: Iterable[str], story_id: str) -> str:
    """The one tracked path that is this story's file.

    Exactly one `user-stories/<ID>-*.md` must match. That was a hard error in
    push-artifacts.sh and stays one: two files for one story means nobody knows
    which suite is being delivered, and picking either is worse than stopping.

    `paths` is a set of tracked paths -- a scan of the hydrated worktree for a
    run, a scan of the materialized head for delivery -- rather than a glob over
    a mounted directory. Both trees are built from `file_index` and nothing
    else, so the rule is unchanged but it now runs against truth rather than
    against whatever a long-lived mount happened to hold.
    """
    if not story_id:
        raise DeliveryError("a <STORY_ID> is required (e.g. SCRUM-201)")
    prefix = f"{STORIES_DIR}/{story_id}-"
    matches = sorted(
        path for path in paths if path.startswith(prefix) and path.endswith(".md")
    )
    if len(matches) != 1:
        raise DeliveryError(
            f"expected exactly one {STORIES_DIR}/{story_id}-*.md in the tree "
            f"(found {len(matches)})"
        )
    return matches[0]


def resolve_story(
    root: Path, story_id: str, *, paths: Iterable[str], app: str = ""
) -> StoryRef:
    """Derive every path and name from the story's filename.

    `paths` says which files the tree holds; `root` is where their bytes are, so
    the title can be read from the story's first heading. Callers pass both
    explicitly, because which tree they resolved against -- a run's worktree or
    delivery's materialized head -- is the thing P3 changed and should be
    visible at the call site.
    """
    story_path = story_filename(paths, story_id)
    base = Path(story_path).stem
    slug = base[len(story_id) + 1 :] if base.startswith(f"{story_id}-") else base
    title = _story_title(root / story_path) or slug
    return StoryRef(
        app=app,
        story_id=story_id,
        slug=slug,
        title=title,
        branch=f"qa/{story_id}-{slug}",
        pr_title=f"{story_id}: {title} E2E test suite",
        story_rel=f"{STORIES_DIR}/{base}.md",
        plan_rel=f"{PLANS_DIR}/{story_id}-{slug}-test-plan.md",
        tests_rel=f"{TESTS_DIR}/{slug}",
    )


def story_title(content: str) -> str | None:
    """The title from a story's first heading.

    Over bytes rather than a path, so delivery (which has a materialized file)
    and the portal (which has a blob) share one derivation. There is exactly one
    definition of "what a story is called" and this is it.

    push-artifacts.sh used ${heading#*- }; the HEADING regex gets the same
    answer and tolerates an en-dash, so it is preferred with the shell
    behaviour kept as the fallback.
    """
    for line in content.splitlines():
        if not line.startswith("#"):
            continue
        match = HEADING.match(line)
        if match:
            return match.group(2).strip()
        if "- " in line:
            return line.split("- ", 1)[1].strip() or None
        return line.lstrip("# ").strip() or None
    return None


def _story_title(path: Path) -> str | None:
    """`story_title` of a file that may not exist."""
    return story_title(path.read_text()) if path.is_file() else None


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
