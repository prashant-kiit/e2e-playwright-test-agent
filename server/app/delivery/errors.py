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


def redact(text: str) -> str:
    """Blank the password half of any credential-bearing URL.

    A GitError is built from the argv that failed, and that argv contains the
    PAT. Its message reaches the API's HTTP detail and the portal's bootstrap
    banner, which renders it verbatim -- so this is the choke point where the
    token stops. The repo path and git's own diagnosis survive.
    """
    return _CREDENTIAL_IN_URL.sub(r"\1***\2", text)


class DeliveryError(Exception):
    """Base: anything that stops a delivery tool."""


# `NotBootstrapped` was deleted with the remote bootstrap check (P3-07). Nothing
# can usefully *require* bootstrap before the first delivery any more, because
# "bootstrapped" means "a revision carries a delivered_sha" and the first
# delivery is what writes one. `ensure_bootstrapped` folds the setup into that
# first approved push instead (DESIGN.md decision 16).


class CredentialError(DeliveryError):
    """No usable GitHub token, or GitHub rejected the one we have."""


class ConfirmationMismatch(DeliveryError):
    """A destructive action was not confirmed with the exact repo name.

    reset-target.sh read the confirmation from a TTY. There is no TTY behind a
    portal action, so the caller must echo the repo name back instead.
    """


class GitError(DeliveryError):
    """A git subprocess failed."""

    def __init__(self, args: tuple[str, ...], rc: int, err: str) -> None:
        args = tuple(redact(a) for a in args)
        err = redact(err)
        super().__init__(f"git {' '.join(args)} failed (rc={rc}): {err.strip()}")
        self.args_ = args
        self.rc = rc
        self.err = err
