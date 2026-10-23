"""The git/GitHub/token trio the delivery tools work through.

Bundling them makes every tool injectable in one argument: tests pass a Tools
built from an httpx.MockTransport client and a throwaway local remote, so the
whole delivery surface runs without network or credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import config
from .git import Git, require_git
from .github import GitHubClient, clone_url, token_from_env


@dataclass(frozen=True)
class Tools:
    gh: GitHubClient
    git: Git
    token: str
    workspace: Path

    def clone_url(self, repo: str) -> str:
        return clone_url(repo, self.token)


def default_tools() -> Tools:
    """Built from the environment: GITHUB_PAT (or .env) and the repo root."""
    require_git()
    workspace = config.repo_root()
    token = token_from_env(workspace)
    return Tools(
        gh=GitHubClient.from_token(token),
        git=Git(),
        token=token,
        workspace=workspace,
    )
