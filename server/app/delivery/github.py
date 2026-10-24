"""GitHub over REST, replacing the `gh` CLI (DESIGN.md §11, decision 20).

Five operations are all the delivery tools ever need from `gh`. The httpx client
is injected rather than constructed here, so tests drive the whole surface
through httpx.MockTransport with no network -- the same constructor-injection
seam `Storage` uses in app/storage.py.

P3 deleted the sixth. "Is this target bootstrapped?" used to be two REST calls
asking whether the branch carried an `app.json` and a `playwright.config.ts`;
it is a Postgres query now (`delivery.catalog`), because the answer must be the
same for everyone and must not depend on the network being up.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from .errors import CredentialError, DeliveryError

API_ROOT = "https://api.github.com"
_TIMEOUT = httpx.Timeout(30.0)


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    head: str
    base: str
    title: str
    state: str


@dataclass(frozen=True)
class TokenInfo:
    login: str
    scopes: frozenset[str]
    expires_at: datetime | None

    def has_delivery_scopes(self) -> bool:
        """Bootstrap pushes .github/workflows/playwright.yml, which needs
        `workflow` on top of `repo` (DESIGN.md §8).

        A fine-grained PAT reports no scopes at all in x-oauth-scopes, so an
        empty set is treated as "cannot tell" rather than "insufficient" --
        failing loud at push time is better than rejecting a valid token here.
        """
        if not self.scopes:
            return True
        return "repo" in self.scopes and "workflow" in self.scopes


def token_from_env() -> str:
    """GITHUB_PAT from the environment. The environment only.

    qa-lib.sh read it from a `.env` beside the workspace as a fallback, and that
    fallback is deleted here. From P3 the workspace is a tree an LLM wrote while
    reading a live customer website, so looking for a credential anywhere near
    it is an exfiltration path -- the single most dangerous line this phase could
    have introduced. DESIGN.md §6 ("no GitHub credentials ever enter a sandbox")
    does not formally bind until P4; the lookup path is introduced here, so the
    rule is applied here.

    Per-tenant encrypted credentials are P5; this stays a process-level
    environment variable until then.
    """
    token = os.environ.get("GITHUB_PAT", "").strip()
    if token:
        return token
    raise CredentialError("no GitHub token: set GITHUB_PAT in the environment")


def clone_url(repo: str, token: str) -> str:
    """Ports qa-lib.sh `qa_clone_url`. Callers must keep this out of logs."""
    return f"https://x-access-token:{token}@github.com/{repo}.git"


def make_client(token: str, *, base_url: str = API_ROOT) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        timeout=_TIMEOUT,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "qa-harness",
        },
    )


class GitHubClient:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @classmethod
    def from_token(cls, token: str) -> GitHubClient:
        return cls(make_client(token))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- plumbing ---------------------------------------------------------

    def _get(self, path: str, **params: Any) -> httpx.Response:
        resp = self._client.get(path, params=params or None)
        self._raise_for_credentials(resp)
        return resp

    @staticmethod
    def _raise_for_credentials(resp: httpx.Response) -> None:
        """Fail loud on a credential problem (DESIGN.md §8) rather than letting
        it read as 'the resource does not exist'."""
        if resp.status_code in (401, 403):
            raise CredentialError(
                f"GitHub rejected the token ({resp.status_code}) for "
                f"{resp.request.method} {resp.request.url.path}"
            )

    # --- the five operations ---------------------------------------------

    def repo_has_commits(self, repo: str) -> bool:
        """Ports `qa_repo_has_commits`: the API answers 409 for an empty repo."""
        resp = self._get(f"/repos/{repo}/commits", per_page=1)
        if resp.status_code == 409:
            return False
        if resp.status_code == 404:
            raise DeliveryError(f"no such repo (or no access): {repo}")
        return resp.is_success

    def branch_exists(self, repo: str, branch: str) -> bool:
        return self._get(f"/repos/{repo}/branches/{branch}").is_success

    def find_pr(self, repo: str, head_branch: str) -> PullRequest | None:
        """The open PR whose head is `head_branch`, if any (replaces
        `gh pr view <branch>`)."""
        owner = repo.split("/", 1)[0]
        resp = self._get(f"/repos/{repo}/pulls", head=f"{owner}:{head_branch}", state="open")
        if not resp.is_success:
            return None
        items = resp.json()
        return _as_pr(items[0]) if items else None

    def create_pr(
        self, repo: str, *, head: str, base: str, title: str, body: str
    ) -> PullRequest:
        resp = self._client.post(
            f"/repos/{repo}/pulls",
            json={"head": head, "base": base, "title": title, "body": body},
        )
        self._raise_for_credentials(resp)
        if not resp.is_success:
            raise DeliveryError(f"could not create the PR for {head}: {_detail(resp)}")
        return _as_pr(resp.json())

    def update_pr(self, repo: str, number: int, *, title: str, body: str) -> PullRequest:
        resp = self._client.patch(
            f"/repos/{repo}/pulls/{number}", json={"title": title, "body": body}
        )
        self._raise_for_credentials(resp)
        if not resp.is_success:
            raise DeliveryError(f"could not update PR #{number}: {_detail(resp)}")
        return _as_pr(resp.json())

    def token_info(self) -> TokenInfo:
        """Scope + expiry validation at save time (DESIGN.md §8). Both facts
        arrive as response headers, not in the body."""
        resp = self._get("/user")
        if not resp.is_success:
            raise CredentialError(f"could not validate the token: {_detail(resp)}")
        raw_scopes = resp.headers.get("x-oauth-scopes", "")
        scopes = frozenset(s.strip() for s in raw_scopes.split(",") if s.strip())
        return TokenInfo(
            login=resp.json().get("login", ""),
            scopes=scopes,
            expires_at=_parse_expiry(
                resp.headers.get("github-authentication-token-expiration")
            ),
        )


def _as_pr(data: dict) -> PullRequest:
    return PullRequest(
        number=data["number"],
        url=data.get("html_url", ""),
        head=(data.get("head") or {}).get("ref", ""),
        base=(data.get("base") or {}).get("ref", ""),
        title=data.get("title", ""),
        state=data.get("state", ""),
    )


def _detail(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("message") or resp.text)
    except ValueError:
        return resp.text


def _parse_expiry(value: str | None) -> datetime | None:
    """GitHub sends e.g. "2026-12-31 23:59:59 UTC" on classic PATs."""
    if not value:
        return None
    cleaned = value.strip().replace(" UTC", "+0000")
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None
