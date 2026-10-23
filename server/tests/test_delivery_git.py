"""The git subprocess wrapper, and what its failures are allowed to say.

The clone URL carries the PAT (`https://x-access-token:<token>@github.com/...`),
and a GitError is built from the argv that failed -- so without redaction a
failed clone would carry the token into the API's HTTP detail and into the
portal's bootstrap banner, which renders it verbatim.
"""

from __future__ import annotations

import pytest

from app.delivery.errors import GitError
from app.delivery.git import Git
from app.delivery.github import clone_url

TOKEN = "ghp_sUpErSeCrEt0123456789"


def test_a_failed_clone_does_not_leak_the_token(tmp_path):
    url = clone_url("o/does-not-exist", TOKEN)

    with pytest.raises(GitError) as exc:
        Git().clone(url, tmp_path / "repo")

    message = str(exc.value)
    assert TOKEN not in message
    assert "x-access-token:***@github.com/o/does-not-exist" in message


def test_redaction_keeps_the_rest_of_the_message_useful(tmp_path):
    """Redaction must not cost the diagnosis: the repo, the subcommand and
    git's own stderr still have to be there."""
    url = clone_url("o/does-not-exist", TOKEN)

    with pytest.raises(GitError) as exc:
        Git().clone(url, tmp_path / "repo")

    message = str(exc.value)
    assert "clone" in message
    assert "o/does-not-exist" in message
    assert "rc=" in message


def test_the_token_is_scrubbed_from_stderr_too():
    """git echoes the URL back in its own error text, so the argv is not the
    only path the token can take."""
    stderr = f"fatal: https://x-access-token:{TOKEN}@github.com/o/r.git/ not found"
    err = GitError(("push", "origin"), 128, stderr)
    assert TOKEN not in str(err)
    assert TOKEN not in err.err
