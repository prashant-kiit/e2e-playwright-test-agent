"""The GitHub REST client, driven entirely through httpx.MockTransport.

`gh` is gone (DESIGN.md decision 20), so these are the tests that used to be
impossible: the whole GitHub surface is now exercised offline, including the
status codes that carried meaning in the shell tools (409 = empty repo,
404 = file absent) and the credential failures §8 requires to fail loud.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.delivery import errors
from app.delivery.github import GitHubClient, clone_url, token_from_env


def client_for(handler) -> GitHubClient:
    transport = httpx.MockTransport(handler)
    return GitHubClient(
        httpx.Client(transport=transport, base_url="https://api.github.com")
    )


def test_repo_has_commits_is_false_on_409():
    """An empty repo answers 409 -- the signal bootstrap uses to choose its mode."""
    gh = client_for(lambda req: httpx.Response(409, json={"message": "Git Repository is empty."}))
    assert gh.repo_has_commits("o/r") is False


def test_repo_has_commits_is_true_on_200():
    gh = client_for(lambda req: httpx.Response(200, json=[{"sha": "abc"}]))
    assert gh.repo_has_commits("o/r") is True


def test_repo_has_commits_raises_on_404():
    gh = client_for(lambda req: httpx.Response(404, json={"message": "Not Found"}))
    with pytest.raises(errors.DeliveryError, match="no such repo"):
        gh.repo_has_commits("o/missing")


def test_file_exists_maps_404_to_false_and_sends_the_ref():
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(404 if "missing" in req.url.path else 200, json={})

    gh = client_for(handler)
    assert gh.file_exists("o/r", "playwright.config.ts", "master") is True
    assert gh.file_exists("o/r", "missing.txt", "master") is False
    assert "ref=master" in seen[0]


def test_is_bootstrapped_needs_both_files():
    def only_config(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if "playwright.config.ts" in req.url.path else 404, json={})

    assert client_for(only_config).is_bootstrapped("o/r", "demo", "master") is False

    def both(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    assert client_for(both).is_bootstrapped("o/r", "demo", "master") is True


def test_find_pr_queries_owner_qualified_head_and_open_state():
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(dict(req.url.params))
        return httpx.Response(
            200,
            json=[
                {
                    "number": 12,
                    "html_url": "https://github.com/o/r/pull/12",
                    "title": "t",
                    "state": "open",
                    "head": {"ref": "qa/SCRUM-1-x"},
                    "base": {"ref": "master"},
                }
            ],
        )

    pr = client_for(handler).find_pr("o/r", "qa/SCRUM-1-x")
    assert seen == {"head": "o:qa/SCRUM-1-x", "state": "open"}
    assert pr is not None and pr.number == 12
    assert pr.url.endswith("/pull/12")


def test_find_pr_is_none_when_there_is_no_open_pr():
    gh = client_for(lambda req: httpx.Response(200, json=[]))
    assert gh.find_pr("o/r", "qa/none") is None


def test_create_pr_posts_the_expected_body():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(req.content))
        assert req.method == "POST"
        return httpx.Response(
            201,
            json={
                "number": 3,
                "html_url": "https://github.com/o/r/pull/3",
                "title": captured["title"],
                "state": "open",
                "head": {"ref": captured["head"]},
                "base": {"ref": captured["base"]},
            },
        )

    pr = client_for(handler).create_pr(
        "o/r", head="qa/b", base="master", title="T", body="B"
    )
    assert captured == {"head": "qa/b", "base": "master", "title": "T", "body": "B"}
    assert pr.number == 3


def test_create_pr_surfaces_the_api_message():
    gh = client_for(lambda req: httpx.Response(422, json={"message": "No commits between"}))
    with pytest.raises(errors.DeliveryError, match="No commits between"):
        gh.create_pr("o/r", head="qa/b", base="master", title="T", body="B")


def test_update_pr_patches_by_number():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "PATCH"
        assert req.url.path.endswith("/pulls/7")
        return httpx.Response(
            200,
            json={
                "number": 7,
                "html_url": "u",
                "title": "T2",
                "state": "open",
                "head": {"ref": "qa/b"},
                "base": {"ref": "master"},
            },
        )

    assert client_for(handler).update_pr("o/r", 7, title="T2", body="B").title == "T2"


def test_401_and_403_raise_credential_error_not_not_found():
    """§8: a credential problem must never read as 'the resource is absent'."""
    for status in (401, 403):
        gh = client_for(lambda req, s=status: httpx.Response(s, json={"message": "Bad creds"}))
        with pytest.raises(errors.CredentialError):
            gh.file_exists("o/r", "any", "master")


def test_token_info_parses_scopes_and_expiry_from_headers():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"login": "octocat"},
            headers={
                "x-oauth-scopes": "repo, workflow, read:org",
                "github-authentication-token-expiration": "2026-12-31 23:59:59 UTC",
            },
        )

    info = client_for(handler).token_info()
    assert info.login == "octocat"
    assert info.scopes == frozenset({"repo", "workflow", "read:org"})
    assert info.expires_at == datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert info.has_delivery_scopes() is True


def test_token_info_rejects_a_token_missing_workflow():
    """Bootstrap pushes .github/workflows/playwright.yml, so `repo` alone is not enough."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"login": "o"}, headers={"x-oauth-scopes": "repo"})

    assert client_for(handler).token_info().has_delivery_scopes() is False


def test_fine_grained_token_reports_no_scopes_and_is_not_pre_rejected():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"login": "o"})

    info = client_for(handler).token_info()
    assert info.scopes == frozenset()
    assert info.expires_at is None
    assert info.has_delivery_scopes() is True


def test_token_from_env_prefers_the_environment(monkeypatch):
    monkeypatch.setenv("GITHUB_PAT", "from-env")
    assert token_from_env(Path("/nonexistent")) == "from-env"


def test_token_from_env_falls_back_to_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    (tmp_path / ".env").write_text('# comment\nGITHUB_PAT="from-file"\nOTHER=x\n')
    assert token_from_env(tmp_path) == "from-file"


def test_token_from_env_raises_when_there_is_no_token(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    with pytest.raises(errors.CredentialError, match="no GitHub token"):
        token_from_env(tmp_path)


def test_clone_url_embeds_the_token():
    assert clone_url("o/r", "tok") == "https://x-access-token:tok@github.com/o/r.git"
