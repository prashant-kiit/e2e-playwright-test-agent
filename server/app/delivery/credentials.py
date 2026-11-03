"""A tenant's GitHub credential: saved, sealed, opened once at push time.

This is the only module that turns `targets.github_pat_ciphertext` back into a
token, and it is reached only through the delivery `Tools` seam
(app/delivery/tools.py) in the control plane. Two consequences are deliberate
and load-bearing:

* **No delivery function reaches for a credential outside `Tools`** -- the rule
  that module's docstring states. `token_from_env()` as the tenant credential
  source is retired by this ticket; the token now comes from the target's own
  row.
* **Nothing reachable from a sandbox imports this file.** A sandbox runs the
  same server package as the API, so the *code* exists there; what must not
  exist is a path from the sandbox entrypoint to the function that opens a
  seal. `app/delivery/__init__.py` re-exports lazily for exactly this reason,
  and tests/test_sandbox_credentials.py walks the real import graph to keep it
  true.

**Four operations, and the asymmetry between them is the point.**

`save_pat` is the write path and the only place a plaintext token is accepted.
It validates the token against GitHub *before* storing it, because the failure
it prevents -- a token missing `workflow`, discovered hours later when a
delivery tries to push `.github/workflows/playwright.yml` -- is cheap to catch
while the operator still has the paste buffer open and expensive afterwards. A
fine-grained PAT reports no scopes at all, so an empty scope set is treated as
"cannot tell" and deferred to fail-loud at push: rejecting a working token here
would be worse than the thing the check exists for.

`decrypt_pat` is the read path, called once per delivery operation.

`mark_invalid` is what 401/403 at delivery writes. It fails the **delivery
only**: a credential problem must never cost a customer a run whose results are
already durable (DESIGN.md §8), and it must never be a silent retry either --
the state is sticky until a new token is saved, so the customer is told.

`credential_status` is the read the portal renders, including the expiry
warning. It is a pure function of the row, so showing it costs no KMS call and
no GitHub call -- the same reason "is this delivered?" is a Postgres question.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from .. import envelope
from ..domain.credentials import CredentialState
from ..models import Target
from .errors import CredentialError, CredentialRejected, DeliveryError, redact
from .github import GitHubClient, TokenInfo

# How long before a PAT lapses the portal starts warning. Fourteen days is
# about how long it takes a customer to find whoever owns the token and get a
# new one pasted in; a shorter window turns the warning into an emergency.
EXPIRY_WARNING_DAYS = 14

# Re-exported so a caller of this seam catches both halves of a credential
# failure -- "no such target" and "no usable token" -- from one import.
__all__ = [
    "Credentials",
    "CredentialError",
    "CredentialRejected",
    "CredentialStatus",
    "DbCredentials",
    "DeliveryError",
    "clear_pat",
    "credential_status",
    "decrypt_pat",
    "mark_invalid",
    "save_pat",
]

# The scopes a delivery actually needs. `repo` to push the branch, `workflow`
# because bootstrap pushes .github/workflows/playwright.yml and GitHub refuses
# that path without it (DESIGN.md §8).
REQUIRED_SCOPES = ("repo", "workflow")

log = logging.getLogger(__name__)


def validate_with_github(token: str) -> TokenInfo:
    """The live save-time check: `GET /user`, for its two response headers.

    A plain function so the save path takes it as a parameter -- the httpx
    `MockTransport` seam the rest of the GitHub surface is tested through
    already exists, and a check nothing can substitute is a check nothing
    tests offline.
    """
    with GitHubClient.from_token(token) as gh:
        return gh.token_info()


# --- the write path ------------------------------------------------------

def save_pat(
    session: Session,
    target: Target,
    token: str,
    *,
    validate=validate_with_github,
    wrapper: envelope.KeyWrapper | None = None,
) -> TokenInfo:
    """Validate a pasted PAT, seal it onto the target row, and return what
    GitHub said about it.

    Raises `CredentialRejected` -- never `CredentialError` -- for everything an
    operator can fix by pasting a different token, so the route answers 422
    rather than the 502 that means "GitHub is having a bad day". The row is not
    touched unless the token passed, so a failed rotation leaves the working
    credential in place rather than a broken one.
    """
    token = (token or "").strip()
    if not token:
        raise CredentialRejected("a GitHub token is required")

    try:
        info = validate(token)
    except CredentialError as exc:
        # GitHub itself refused the token. At save time that is the operator's
        # typo or a revoked token, not an outage, so it is a rejection.
        #
        # Through `redact`, because this message is built from whatever GitHub
        # said and goes straight into an HTTP detail the portal renders: an
        # error body that quotes the token back at us must not carry it there.
        raise CredentialRejected(
            redact(f"GitHub did not accept this token: {exc}")
        ) from exc

    if not info.has_delivery_scopes():
        missing = [s for s in REQUIRED_SCOPES if s not in info.scopes]
        raise CredentialRejected(
            f"this token is missing the {', '.join(missing)} scope(s); delivery "
            f"needs {' + '.join(REQUIRED_SCOPES)} because bootstrap pushes a "
            f"GitHub Actions workflow"
        )

    target.github_pat_ciphertext = envelope.seal(token, wrapper or envelope.wrapper_from_env())
    target.pat_expires_at = info.expires_at
    target.credential_state = CredentialState.VALID
    session.commit()
    return info


def clear_pat(session: Session, target: Target) -> None:
    """Remove a target's credential: back to `ABSENT`, as if never saved."""
    target.github_pat_ciphertext = None
    target.pat_expires_at = None
    target.credential_state = CredentialState.ABSENT
    session.commit()


def mark_invalid(session: Session, target: Target) -> None:
    """Record that GitHub rejected this credential at delivery.

    Sticky by design: it stays invalid until a new token is saved, so the next
    delivery attempt is refused with an explanation instead of failing the same
    way again. The ciphertext is deliberately **kept** -- deleting it would
    throw away the only evidence of what was rejected, and an operator who
    fixes the token's scopes on GitHub's side can re-save the same value.
    """
    target.credential_state = CredentialState.INVALID
    session.commit()


# --- the read paths ------------------------------------------------------

def decrypt_pat(target: Target, *, wrapper: envelope.KeyWrapper | None = None) -> str:
    """The target's PAT. **The one function that opens a seal.**

    Called once per delivery operation, in the control plane, from the `Tools`
    seam. `CredentialError` (not `CredentialRejected`) for both failure modes:
    at this point the operator has already approved a delivery and the problem
    is not something a different paste fixes.
    """
    if target.credential_state is CredentialState.INVALID:
        raise CredentialError(
            f"GitHub rejected the stored credential for {target.app!r}; save a "
            f"new token before delivering again"
        )
    if not target.github_pat_ciphertext:
        raise CredentialError(
            f"no GitHub credential stored for {target.app!r}; save one in the "
            f"portal before delivering"
        )
    try:
        return envelope.open_sealed(
            target.github_pat_ciphertext, wrapper or envelope.wrapper_from_env()
        )
    except envelope.SealError as exc:
        # A key that cannot open its own ciphertext: a rotated KMS key, a
        # changed QA_SECRET_KEY, or a corrupted column. Never guessed at.
        raise CredentialError(
            redact(f"the stored credential for {target.app!r} could not be decrypted: {exc}")
        ) from exc


@dataclass(frozen=True)
class CredentialStatus:
    """What the portal shows about a target's credential. No network, no KMS."""

    state: CredentialState
    expires_at: datetime | None
    days_until_expiry: int | None
    expiring_soon: bool
    warning: str | None


def credential_status(target: Target) -> CredentialStatus:
    """The row, read as the three things an operator needs to know: is there a
    credential, does GitHub still accept it, and is it about to lapse."""
    state = CredentialState(target.credential_state)
    expires_at = target.pat_expires_at
    days = _days_until(expires_at)
    # Expiry only matters for a credential that would otherwise work: "absent"
    # and "invalid" have their own, louder messages.
    expiring_soon = (
        state is CredentialState.VALID and days is not None and days <= EXPIRY_WARNING_DAYS
    )
    return CredentialStatus(
        state=state,
        expires_at=expires_at,
        days_until_expiry=days,
        expiring_soon=expiring_soon,
        warning=_warning(state, days, expiring_soon),
    )


def _days_until(expires_at: datetime | None) -> int | None:
    """Whole days until expiry, rounded **up**, and negative once past.

    `timedelta.days` truncates, which is the wrong direction for a warning: a
    token with 2 days and 23 hours left would be reported as "2 days", and one
    with 3 hours left as "0 days" -- a message that reads like "no deadline"
    about the most urgent case there is. Rounding up means the number never
    claims more time than the credential has.
    """
    if expires_at is None:
        return None
    # The column is timezone-aware, but a value read back from a naive source
    # would make this a TypeError rather than a warning -- so it is normalised.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return math.ceil((expires_at - datetime.now(UTC)).total_seconds() / 86400)


def _warning(state: CredentialState, days: int | None, expiring_soon: bool) -> str | None:
    if state is CredentialState.ABSENT:
        return (
            "No GitHub credential is stored for this target, so delivery cannot "
            "run. Save a personal access token with repo + workflow scope."
        )
    if state is CredentialState.INVALID:
        return (
            "GitHub rejected this credential the last time we delivered. Save a "
            "new personal access token; runs are unaffected."
        )
    if expiring_soon and days is not None:
        if days < 0:
            return (
                "This GitHub credential has expired. Delivery will fail until a "
                "new token is saved."
            )
        return (
            f"This GitHub credential expires in {days} days. Save a new token "
            f"before then to keep delivery working."
        )
    return None


# --- the credential half of the delivery seam ----------------------------

class Credentials(Protocol):
    """What `Tools` asks for a target's credential, and what tells it one was
    rejected. A protocol so a test substitutes a dict the way it substitutes a
    `Catalog`."""

    def token_for(self, app: str) -> str: ...
    def mark_invalid(self, app: str) -> None: ...


class DbCredentials:
    """A `Credentials` over Postgres and a key wrapper.

    Takes a session *factory* for the same reason `DbCatalog` does: a delivery
    operation runs for as long as a clone and a push take, and holding a
    transaction open across that is how a connection pool runs out. Both reads
    here are short and open their own session.

    The lookup is `catalog.target_by_app`, so it carries the tenant filter
    every other read carries -- one tenant cannot name another's target and be
    handed its credential.
    """

    def __init__(self, session_factory, wrapper: envelope.KeyWrapper | None = None) -> None:
        self._sessions = session_factory
        self._wrapper = wrapper or envelope.wrapper_from_env()

    def token_for(self, app: str) -> str:
        from .catalog import target_by_app

        with self._sessions() as session:
            return decrypt_pat(target_by_app(session, app), wrapper=self._wrapper)

    def mark_invalid(self, app: str) -> None:
        """Record a 401/403 from delivery. **Never raises.**

        It is called from the failure path of a delivery that is already
        failing, and a second exception there would replace a clear "GitHub
        rejected your token" with whatever went wrong while writing that down.
        A target that has vanished under us is the realistic case, and the
        delivery's own error is the more useful one to surface.

        Never raising is not the same as never saying: it **logs**. A failed
        mark means the next delivery will fail the same way with no warning on
        the row, which is precisely the silent retry §8 forbids -- so it must
        not be indistinguishable from a successful one in the one place an
        operator can still look (P5-03 review). The log carries the app, never
        the credential.
        """
        from .catalog import target_by_app

        try:
            with self._sessions() as session:
                mark_invalid(session, target_by_app(session, app))
        except Exception:
            # Deliberately broad -- see the docstring. Logged, not silent.
            log.exception(
                "could not record that GitHub rejected the credential for %r; "
                "the row still reads valid and the next delivery will fail the "
                "same way",
                app,
            )
