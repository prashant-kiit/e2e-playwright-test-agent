"""The git/GitHub/token/catalog set the delivery tools work through.

Bundling them makes every tool injectable in one argument: tests pass a Tools
built from an httpx.MockTransport client, a throwaway local remote and a
dict-backed catalog, so the whole delivery surface runs without network,
credentials or a database.

**No delivery function may reach for config, credentials or git outside this
value.** P3 changed what two of its fields mean rather than adding a fifth seam:
the long-lived `workspace` is gone, replaced by `catalog.materialize(app)` which
builds the head revision into a temporary tree per operation, and the catalog is
where a target's configuration comes from now that `app.json` does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import Catalog, DeliveryState
from .git import Git, require_git
from .github import GitHubClient, clone_url, token_from_env


@dataclass(frozen=True)
class Tools:
    gh: GitHubClient
    git: Git
    token: str
    catalog: Catalog

    def clone_url(self, repo: str) -> str:
        return clone_url(repo, self.token)

    def state(self, app: str) -> DeliveryState:
        return self.catalog.state(app)


def default_tools() -> Tools:
    """Built from the environment and the configured database.

    The PAT comes from the environment **only**. The `.env`-beside-the-workspace
    fallback is gone: the workspace is a tree an LLM wrote while reading a live
    customer website, and a credential lookup inside agent-produced content is
    an exfiltration path. DESIGN.md §6's rule does not formally bind until P4,
    but this is the phase that would have introduced it.
    """
    from .. import storage
    from ..db import SessionLocal
    from .catalog import DbCatalog

    require_git()
    token = token_from_env()
    return Tools(
        gh=GitHubClient.from_token(token),
        git=Git(),
        token=token,
        catalog=DbCatalog(SessionLocal, storage.from_env()),
    )
