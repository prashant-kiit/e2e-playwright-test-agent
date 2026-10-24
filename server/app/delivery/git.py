"""git as a subprocess, with typed results.

We orchestrate git, we never reimplement it (DESIGN.md §11), so this is a thin
wrapper and nothing more. Every machine-made commit carries the harness identity
that scripts/qa-lib.sh's `qa_git` used, so history in a customer repo keeps
attributing these commits to the harness rather than to whoever ran the server.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import GitError

# Ported from qa-lib.sh `qa_git`.
HARNESS_NAME = "qa-harness"
HARNESS_EMAIL = "qa-harness@users.noreply.github.com"
HARNESS_IDENTITY = (
    "-c",
    f"user.name={HARNESS_NAME}",
    "-c",
    f"user.email={HARNESS_EMAIL}",
)


@dataclass(frozen=True)
class GitResult:
    rc: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


def require_git() -> None:
    if shutil.which("git") is None:
        raise GitError(("--version",), 127, "missing dependency: git")


class Git:
    """Runs git in `cwd`. A fresh instance per worktree; `cwd` may be set later
    (clone creates the directory this instance will then work in)."""

    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = cwd

    def at(self, cwd: Path) -> Git:
        return Git(cwd)

    def run(self, *args: str, check: bool = True, identity: bool = False) -> GitResult:
        argv = ["git", *(HARNESS_IDENTITY if identity else ()), *args]
        proc = subprocess.run(
            argv,
            cwd=str(self.cwd) if self.cwd else None,
            capture_output=True,
            text=True,
        )
        result = GitResult(proc.returncode, proc.stdout, proc.stderr)
        if check and not result.ok:
            raise GitError(args, result.rc, result.err)
        return result

    # --- plumbing used by the delivery tools -----------------------------

    def clone(
        self, url: str, dest: Path, *, branch: str | None = None, depth: int | None = None
    ) -> Git:
        args = ["clone"]
        if depth is not None:
            args += ["--depth", str(depth)]
        if branch is not None:
            args += ["--branch", branch]
        args += [url, str(dest)]
        Git(None).run(*args)
        return Git(dest)

    def checkout_new(self, branch: str, start_point: str | None = None) -> None:
        args = ["checkout", "-b", branch]
        if start_point is not None:
            args.append(start_point)
        self.run(*args)

    def checkout_orphan(self, branch: str) -> None:
        self.run("checkout", "--orphan", branch)

    def rename_branch(self, branch: str) -> None:
        self.run("branch", "-M", branch)

    def add_all(self) -> None:
        self.run("add", "-A")

    def remove_all_cached(self) -> None:
        # `git rm -rf .` on an orphan branch: tolerate an already-empty index.
        self.run("rm", "-rf", ".", check=False)

    def has_staged_changes(self) -> bool:
        return not self.run("diff", "--cached", "--quiet", check=False).ok

    def diff_cached_name_status(self) -> str:
        return self.run("--no-pager", "diff", "--cached", "--name-status").out

    def commit(self, message: str, *, allow_empty: bool = False) -> None:
        args = ["commit", "-q", "-m", message]
        if allow_empty:
            args.insert(1, "--allow-empty")
        self.run(*args, identity=True)

    def push(
        self,
        remote: str,
        refspec: str,
        *,
        force: bool = False,
        set_upstream: bool = False,
    ) -> None:
        args = ["push"]
        if force:
            args.append("-f")
        if set_upstream:
            args.append("-u")
        args += [remote, refspec]
        self.run(*args)

    def delete_remote_branch(self, remote: str, branch: str) -> bool:
        """True if the branch was deleted. False is expected for a protected or
        default branch, which the shell tool warned about rather than failing."""
        return self.run("push", remote, "--delete", branch, check=False).ok

    def head_sha(self) -> str:
        """The commit the worktree is on. What `delivered_sha` records."""
        return self.run("rev-parse", "HEAD").out.strip()

    def remote_branch_exists(self, remote: str, branch: str) -> bool:
        return self.run(
            "ls-remote", "--exit-code", "--heads", remote, branch, check=False
        ).ok

    def fetch_branch(self, remote: str, branch: str, *, depth: int | None = None) -> None:
        args = ["fetch"]
        if depth is not None:
            args += ["--depth", str(depth)]
        args += [remote, branch]
        self.run(*args)

    def ls_remote_heads(self, url: str) -> list[str]:
        out = Git(None).run("ls-remote", "--heads", url).out
        heads: list[str] = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].startswith("refs/heads/"):
                heads.append(parts[1][len("refs/heads/") :])
        return heads

    def bundle_create(self, path: Path, ref: str = "--all") -> None:
        """A full bundle of the worktree's history (DESIGN.md §5 pause-reap)."""
        self.run("bundle", "create", str(path), ref)
