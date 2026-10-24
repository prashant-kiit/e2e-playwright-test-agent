"""A throwaway workspace + a local bare repo standing in for GitHub.

The delivery tools are mostly git plumbing, so faking git would test the fake.
Instead the git side is real -- a bare repo on disk as `origin` -- and only the
GitHub REST calls are faked. That exercises clone/branch/commit/push and the
wholesale-replace semantics for real, with no network and no credentials.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.delivery.catalog import DeliveryState
from app.delivery.errors import DeliveryError
from app.delivery.git import Git
from app.delivery.github import PullRequest
from app.delivery.render import write_infra
from app.delivery.tools import Tools
from app.target_config import TargetConfig

INFRA_CONTENT = {
    "package.json": '{"name": "qa"}\n',
    "package-lock.json": '{"lockfileVersion": 3}\n',
    "playwright.config.ts": "export default {};\n",
    ".gitignore": "node_modules/\n",
    ".github/workflows/playwright.yml": "name: Playwright Tests\n",
}


def make_workspace(tmp_path: Path, app: str = "demo", *, repo: str = "o/r") -> Path:
    """A minimal agent repo: infra files plus one app with one ready story."""
    for rel, text in INFRA_CONTENT.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    app_dir = tmp_path / "apps" / app
    (app_dir / "user-stories").mkdir(parents=True)
    (app_dir / "specs").mkdir()
    (app_dir / "tests" / "checkout").mkdir(parents=True)
    (app_dir / "app.json").write_text(
        json.dumps(
            {
                "name": "Demo",
                "baseURL": "https://demo.example.com",
                "targetRepo": repo,
                "targetBranch": "master",
                "locators": "data-testid",
                "agentNotes": [],
            },
            indent=2,
        )
        + "\n"
    )
    (app_dir / "seed.spec.ts").write_text("// seed\n")
    (app_dir / "user-stories" / "SCRUM-1-checkout.md").write_text(
        "# User Story: SCRUM-1 - Checkout Flow\n\nAs a user...\n"
    )
    (app_dir / "specs" / "SCRUM-1-checkout-test-plan.md").write_text("# Plan\n")
    (app_dir / "tests" / "checkout" / "cart.spec.ts").write_text("// cart\n")
    (app_dir / "tests" / "checkout" / "pay.spec.ts").write_text("// pay\n")
    return tmp_path


def make_bare_remote(tmp_path: Path, name: str = "origin.git") -> Path:
    bare = tmp_path / name
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=master", str(bare)],
        check=True,
        capture_output=True,
    )
    return bare


@dataclass(frozen=True)
class LocalTools(Tools):
    """Tools whose clone URL points at a bare repo on disk."""

    remote: Path | None = None

    def clone_url(self, repo: str) -> str:
        assert self.remote is not None
        return str(self.remote)


class DictCatalog:
    """A Catalog backed by a directory and a config value.

    The delivery seam's fourth field, faked the way the other three are: one
    more object on the double, no database. The source directory stands in for a
    materialized head revision, so git and the filesystem stay real and only the
    things that genuinely need a database are substituted.
    """

    def __init__(self, source: Path, cfg: TargetConfig, *, rev: int | None = 1) -> None:
        self.source = source
        self.cfg = cfg
        self.rev = rev
        self.delivered: list[str] = []
        self.materialized = 0

    def config(self, app: str) -> TargetConfig:
        if app != self.cfg.app:
            raise DeliveryError(f"no such target: {app!r}")
        return self.cfg

    @contextmanager
    def materialize(self, app: str) -> Iterator[Path]:
        """A copy, removed afterwards -- like the real one, so a test that
        mutates the workspace cannot quietly edit the fixture."""
        self.config(app)
        if self.rev is None:
            raise DeliveryError(f"target {app!r} has no head revision")
        self.materialized += 1
        tmp = Path(tempfile.mkdtemp(prefix="fake-delivery-"))
        try:
            root = tmp / "workspace"
            shutil.copytree(self.source, root)
            yield root
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def state(self, app: str) -> DeliveryState:
        self.config(app)
        return DeliveryState(
            rev=self.rev,
            tree_hash=None,
            delivered_sha=self.delivered[-1] if self.delivered else None,
            revisions_ahead=0 if self.delivered else (self.rev or 0),
            ever_delivered=bool(self.delivered),
        )

    def record_delivered(self, app: str, sha: str) -> None:
        self.config(app)
        self.delivered.append(sha)


class FakeGitHub:
    """Only the operations the delivery tools call, with recorded state.

    `is_bootstrapped`/`file_exists` are gone: "has anything been delivered to
    this repo?" is a Postgres query now, so it is the catalog that answers it.
    """

    def __init__(self, *, has_commits: bool = False) -> None:
        self.has_commits = has_commits
        self.prs: dict[str, PullRequest] = {}
        self.created: list[str] = []
        self.updated: list[int] = []
        self._next_number = 1

    def repo_has_commits(self, repo: str) -> bool:
        return self.has_commits

    def branch_exists(self, repo: str, branch: str) -> bool:
        return branch in self.prs

    def find_pr(self, repo: str, head_branch: str) -> PullRequest | None:
        return self.prs.get(head_branch)

    def create_pr(self, repo, *, head, base, title, body) -> PullRequest:
        pr = PullRequest(
            number=self._next_number,
            url=f"https://github.com/{repo}/pull/{self._next_number}",
            head=head,
            base=base,
            title=title,
            state="open",
        )
        self._next_number += 1
        self.prs[head] = pr
        self.created.append(head)
        self.last_body = body
        return pr

    def update_pr(self, repo, number, *, title, body) -> PullRequest:
        head = next(h for h, p in self.prs.items() if p.number == number)
        pr = PullRequest(
            number=number,
            url=self.prs[head].url,
            head=head,
            base=self.prs[head].base,
            title=title,
            state="open",
        )
        self.prs[head] = pr
        self.updated.append(number)
        self.last_body = body
        return pr


def make_tools(
    source: Path,
    remote: Path,
    gh: FakeGitHub,
    *,
    cfg: TargetConfig | None = None,
    catalog: DictCatalog | None = None,
) -> LocalTools:
    """Delivery's whole seam, with only the REST boundary and the database faked.

    `source` is a worktree-shaped tree standing in for the materialized head
    revision; git, the filesystem and the infra templates are all real.
    """
    from tests.target_helpers import CONFIG

    return LocalTools(
        gh=gh,
        git=Git(),
        token="t0ken",
        catalog=catalog or DictCatalog(source, cfg or CONFIG),
        remote=remote,
    )


def remote_files(bare: Path, branch: str = "master") -> set[str]:
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", branch],
        cwd=str(bare),
        capture_output=True,
        text=True,
        check=True,
    )
    return set(out.stdout.split())


def remote_branches(bare: Path) -> set[str]:
    out = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"],
        cwd=str(bare),
        capture_output=True,
        text=True,
        check=True,
    )
    return set(out.stdout.split())


def remote_commit_messages(bare: Path, branch: str = "master") -> str:
    """Every commit message on `branch`, bodies included.

    `remote_log` reports subjects (`%s`), which is what most assertions want.
    The Run-ID lives in the *body*, so asserting on it needs `%B`.
    """
    out = subprocess.run(
        ["git", "log", "--format=%B", branch],
        cwd=str(bare),
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def remote_log(bare: Path, branch: str = "master") -> list[str]:
    out = subprocess.run(
        ["git", "log", "--format=%s", branch],
        cwd=str(bare),
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def make_worktree(
    root: Path, *, story: str = "SCRUM-1", slug: str = "checkout", cfg=None
) -> Path:
    """A hydrated worktree: one target's whole tree at the root, nothing else.

    The shape P3 hydrates and ingests -- the infra entries at their destination
    paths, the target's own content beside them, and no apps/<app>/ prefix
    anywhere, because the on-disk shape and the stored shape are now the same
    shape.

    The infra is written by the **real** `write_infra`, generated config and
    all. That matters: a fixture that committed some other bytes for
    `playwright.config.ts` would make the first run's hydrate differ from the
    revision it hydrated, and every run would commit a spurious revision for
    the config alone.
    """
    from tests.target_helpers import CONFIG

    root.mkdir(parents=True, exist_ok=True)
    write_infra(root, cfg or CONFIG)

    (root / "user-stories").mkdir(parents=True, exist_ok=True)
    (root / "specs").mkdir(exist_ok=True)
    (root / "tests" / slug).mkdir(parents=True, exist_ok=True)
    (root / "seed.spec.ts").write_text("// seed\n")
    (root / "user-stories" / f"{story}-{slug}.md").write_text(
        f"# User Story: {story} - Checkout Flow\n\nAs a user...\n"
    )
    (root / "specs" / f"{story}-{slug}-test-plan.md").write_text("# Plan\n")
    (root / "tests" / slug / "cart.spec.ts").write_text("// cart\n")
    (root / "tests" / slug / "pay.spec.ts").write_text("// pay\n")
    return root
