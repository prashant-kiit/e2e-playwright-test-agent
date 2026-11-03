"""Typed failures for the delivery tools.

The shell tools these replace signalled failure with `qa_die` + a non-zero exit;
the Python ports raise instead, so the portal can map a cause to an HTTP status
without parsing stderr.
"""

from __future__ import annotations

import re

# `https://x-access-token:<token>@github.com/...` -- the clone URL every push and
# clone is given. It arrives here two ways: as part of the argv that failed, and
# inside git's own stderr, which echoes the remote back.
_CREDENTIAL_IN_URL = re.compile(r"(://[^/\s:@]*:)[^/\s@]+(@)")

# A bare GitHub PAT, by **prefix** rather than by shape (P5-03). The constant
# is named `_BARE_PAT` and not for style: this module is imported by code a
# sandbox runs, and tests/test_sandbox_credentials.py asserts that no such
# module so much as mentions `GITHUB_TOKEN` -- a name is a mention. The shape
# alternative -- "a 40-character hex blob" -- would redact every `delivered_sha`
# in every delivery message, which is most of what makes those messages useful.
# These are GitHub's documented prefixes: classic PAT, OAuth, user-to-server,
# server-to-server, refresh, and fine-grained.
_BARE_PAT = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})"
)

# One of our own sealed credentials, quoted whole. The ciphertext is not a
# secret -- that is what the envelope buys -- but a hundred characters of base64
# in an error message is noise, and a reader who finds one in a log has no way
# to know it is harmless. Matches the `app.envelope` format by its version
# prefix; a literal rather than an import, because `errors` is imported by
# modules a sandbox loads and `app.envelope` must not be (see
# tests/test_sandbox_credentials.py).
_SEALED_CREDENTIAL = re.compile(r"\bqa-env\d+\$[A-Za-z0-9_-]+\$[A-Za-z0-9_-]+\$[A-Za-z0-9_-]+")


def redact(text: str) -> str:
    """Blank any credential in a message bound for a human.

    The choke point where a token stops. A GitError is built from the argv that
    failed and that argv contains the PAT; its message reaches the API's HTTP
    detail and the portal's bootstrap banner, which renders it verbatim. §8
    requires the credential never to appear in a log, and this is what makes
    that true of the paths that build a message out of whatever they were given.

    Three shapes, because P5-03 added two. The clone URL was the only one while
    there was a single operator token used in a single place. A per-tenant PAT
    arrives as an *argument* to a save path, so a validation message or a quoted
    GitHub error body can carry it bare; and the sealed column can be quoted
    whole by anything that failed to open it.

    Everything else survives, deliberately: the repo path, the subcommand, git's
    own diagnosis and the delivered sha. A redaction that costs the diagnosis
    gets turned off by the next person debugging a delivery.
    """
    text = _CREDENTIAL_IN_URL.sub(r"\1***\2", text)
    text = _BARE_PAT.sub("***", text)
    return _SEALED_CREDENTIAL.sub("***", text)


class DeliveryError(Exception):
    """Base: anything that stops a delivery tool."""


# `NotBootstrapped` was deleted with the remote bootstrap check (P3-07). Nothing
# can usefully *require* bootstrap before the first delivery any more, because
# "bootstrapped" means "a revision carries a delivered_sha" and the first
# delivery is what writes one. `ensure_bootstrapped` folds the setup into that
# first approved push instead (DESIGN.md decision 16).


class CredentialError(DeliveryError):
    """No usable GitHub token, or GitHub rejected the one we have."""


class CredentialRejected(DeliveryError):
    """A credential we were asked to *store* is not usable, and the operator can
    fix it by pasting a different one.

    Deliberately **not** a `CredentialError`. The two mean different things to
    the caller and so map to different status codes: `CredentialError` is "the
    token we have stopped working" (502 -- GitHub refused us), while this is
    "the token you just typed will not do" (422 -- your input was refused). One
    class for both would have made a missing `workflow` scope read to the
    operator as a GitHub outage.
    """


class ConfirmationMismatch(DeliveryError):
    """A destructive action was not confirmed with the exact repo name.

    reset-target.sh read the confirmation from a TTY. There is no TTY behind a
    portal action, so the caller must echo the repo name back instead.
    """


# How git's HTTPS transport reports a credential it will not accept. The PAT
# travels in the clone URL, so a revoked, expired or under-scoped token is
# rejected *here* -- by git, before any REST call -- and not by the GitHub
# client that raises `CredentialError` directly. Matched on git's and GitHub's
# own wording because that is all the transport gives us: there is no status
# code on a subprocess, only its stderr.
_GIT_CREDENTIAL_REJECTION = re.compile(
    r"authentication failed"
    r"|invalid username or password"
    r"|could not read username"
    r"|could not read password"
    r"|terminal prompts disabled"
    r"|permission to .* denied"
    r"|repository not found"          # what GitHub says for a private repo a token cannot see
    r"|returned error: 40[13]",
    re.IGNORECASE,
)


class GitError(DeliveryError):
    """A git subprocess failed."""

    def __init__(self, args: tuple[str, ...], rc: int, err: str) -> None:
        args = tuple(redact(a) for a in args)
        err = redact(err)
        super().__init__(f"git {' '.join(args)} failed (rc={rc}): {err.strip()}")
        self.args_ = args
        self.rc = rc
        self.err = err

    @property
    def is_credential_rejection(self) -> bool:
        """Whether git failed because the credential in the clone URL was refused.

        Read by the delivery seam, which turns a true here into the same
        `CredentialError` the REST client raises -- so "GitHub rejected this
        token" is one outcome with one HTTP status and one sticky
        `credential_state`, however the rejection reached us (DESIGN.md §8).

        A conservative match: a non-fast-forward push, a missing ref or a merge
        conflict says nothing about the token, and marking a working credential
        invalid would send a customer off to rotate it for no reason.
        """
        return bool(_GIT_CREDENTIAL_REJECTION.search(self.err))
