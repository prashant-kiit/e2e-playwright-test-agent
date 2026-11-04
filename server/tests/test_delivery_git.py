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


# --- a bare token, not only one inside a URL (P5-03) ---------------------
#
# Through P4 the only way a credential reached a message was inside a clone
# URL, because there was one operator token and the clone URL was the one place
# it was used. P5-03 adds a save path that takes a token as an *argument*, and
# the shapes that carry one into a message are different: a GitHub error body
# quoting what was sent, a validation message built from the input, a stack
# frame. Redaction has to recognise the token itself.


def test_a_bare_classic_token_is_redacted():
    from app.delivery.errors import redact

    scrubbed = redact(f"GitHub rejected {TOKEN} for GET /user")

    assert TOKEN not in scrubbed
    assert "GET /user" in scrubbed, "the diagnosis survives"


def test_every_github_token_prefix_is_redacted():
    """GitHub's documented prefixes. Listed rather than matched by shape: a
    40-hex-character blob is also a commit sha, and redacting those would make
    every delivery message useless."""
    from app.delivery.errors import redact

    for token in (
        "ghp_" + "a" * 36,
        "gho_" + "b" * 36,
        "ghu_" + "c" * 36,
        "ghs_" + "d" * 36,
        "ghr_" + "e" * 36,
        "github_pat_" + "f" * 22 + "_" + "g" * 59,
    ):
        scrubbed = redact(f"saving {token} failed")
        assert token not in scrubbed, token
        assert "saving" in scrubbed


def test_a_commit_sha_is_not_mistaken_for_a_token():
    """The thing a shape-based rule would have broken: `delivered_sha` is in
    almost every delivery message."""
    from app.delivery.errors import redact

    sha = "e492a9d1f0b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7"

    assert sha in redact(f"delivered {sha} to o/r")


def test_a_sealed_credential_is_redacted():
    """The ciphertext is not a secret -- that is the point of the envelope --
    but a message that quotes a whole column is noise, and a reader who sees
    one in a log cannot tell it is safe."""
    from app import envelope
    from app.delivery.errors import redact

    sealed = envelope.seal("ghp_" + "a" * 36, envelope.LocalKeyWrapper(b"k"))

    scrubbed = redact(f"could not open {sealed} for demo")

    assert sealed not in scrubbed
    assert "for demo" in scrubbed
