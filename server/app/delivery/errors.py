"""Typed failures for the delivery tools.

The shell tools these replace signalled failure with `qa_die` + a non-zero exit;
the Python ports raise instead, so the portal can map a cause to an HTTP status
without parsing stderr.
"""

from __future__ import annotations


class DeliveryError(Exception):
    """Base: anything that stops a delivery tool."""


class NotBootstrapped(DeliveryError):
    """The target repo/branch is missing the infra an app needs."""

    def __init__(self, repo: str, branch: str, app: str) -> None:
        super().__init__(
            f"target not bootstrapped: {repo} ({branch}) is missing infra for app '{app}'"
        )
        self.repo = repo
        self.branch = branch
        self.app = app


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
        super().__init__(f"git {' '.join(args)} failed (rc={rc}): {err.strip()}")
        self.args_ = args
        self.rc = rc
        self.err = err
