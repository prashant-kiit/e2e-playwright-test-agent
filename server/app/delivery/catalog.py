"""What delivery knows about a target: its configuration, its tree, its state.

Through P2 delivery read all three off the filesystem and asked GitHub for the
fourth: `app.json` for the configuration, the repo mount for the tree, an
`ls-remote` for "is this bootstrapped?", and a worktree diff for "is this in
sync?". P3 replaces all of it with one injected source over Postgres and the
blob store, reached through delivery's existing `Tools` seam.

Four things, and they are the four questions delivery actually asks:

- **`config(app)`** -- the target's row: which repo, which branch, and the values
  the generated infra renders from.
- **`materialize(app)`** -- the head revision as a temporary tree, built by the
  same function hydrate uses and removed afterwards. Delivery therefore pushes
  provably the revision it records, rather than whatever a long-lived mount
  happened to hold.
- **`state(app)`** -- delivered, or N revisions ahead. One query, the same answer
  for everyone, and it does not depend on the network being up.
- **`record_delivered(app, sha)`** -- the only writer of `revisions.delivered_sha`
  in the system.

A `Catalog` is a protocol so tests substitute a dict-backed one: one more field
on the double they already build, and no delivery function reaches for config,
credentials or git outside `Tools`.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select

from .. import revisions
from ..models import Revision, Target
from ..sandbox import hydrate as hyd
from ..storage import Storage
from ..target_config import TargetConfig, config_of
from ..tenancy import current_tenant_id
from .errors import DeliveryError


@dataclass(frozen=True)
class DeliveryState:
    """Whether a target's head revision is in the customer's repo.

    `delivered` and `ever_delivered` are different questions and both are
    needed: the head may be undelivered on a target we have pushed to twenty
    times, which is "2 revisions ahead", not "never set up".
    """

    rev: int | None
    tree_hash: str | None
    delivered_sha: str | None
    revisions_ahead: int
    ever_delivered: bool

    @property
    def delivered(self) -> bool:
        """The head revision's own bytes are in the customer's repo."""
        return self.delivered_sha is not None

    @property
    def bootstrapped(self) -> bool:
        """We have pushed to this repo at least once.

        Derived from the same column rather than from an `ls-remote`, so there
        is one definition. If a customer wipes the repo this stays true and the
        next delivery appends over the drift; the deliberate repair is the
        "re-sync infra" action (DESIGN.md §7), not a silent re-bootstrap.
        """
        return self.ever_delivered

    def describe(self) -> str:
        if self.rev is None:
            return "no revisions yet"
        if self.delivered:
            return f"delivered (revision {self.rev})"
        return (
            f"{self.revisions_ahead} revision(s) ahead of the last delivered one"
            if self.ever_delivered
            else f"never delivered ({self.revisions_ahead} revision(s) to push)"
        )


class Catalog(Protocol):
    def config(self, app: str) -> TargetConfig: ...
    def materialize(self, app: str) -> AbstractContextManager[Path]: ...
    def state(self, app: str) -> DeliveryState: ...
    def record_delivered(self, app: str, sha: str) -> None: ...


class DbCatalog:
    """A Catalog over Postgres and the blob store.

    Takes a session *factory*, not a session: a delivery operation runs for as
    long as a clone and a push take, and holding a transaction open across that
    is how a connection pool runs out.
    """

    def __init__(self, session_factory, store: Storage) -> None:
        self._sessions = session_factory
        self._store = store

    # --- configuration ----------------------------------------------------

    def config(self, app: str) -> TargetConfig:
        with self._sessions() as session:
            return config_of(self._target(session, app))

    # --- the tree ---------------------------------------------------------

    @contextmanager
    def materialize(self, app: str) -> Iterator[Path]:
        """The head revision as a temporary tree, removed on the way out.

        The generated entries are rendered from the row, exactly as hydrate
        does, so the tree delivery pushes is the tree a run would have worked
        in -- including the config whose `baseURL` came from the database.
        """
        tmp = Path(tempfile.mkdtemp(prefix="qa-delivery-"))
        try:
            root = tmp / "workspace"
            with self._sessions() as session:
                target = self._target(session, app)
                head = revisions.head_revision(session, target.id)
                if head is None:
                    raise DeliveryError(
                        f"target {app!r} has no head revision, so there is nothing to deliver"
                    )
                try:
                    hyd.materialize(session, head, self._store, root)
                except hyd.HydrateError as exc:
                    raise DeliveryError(f"could not materialize {app!r}: {exc}") from exc
                hyd.render_generated(root, config_of(target))
            yield root
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # --- state ------------------------------------------------------------

    def state(self, app: str) -> DeliveryState:
        """Delivered, or N revisions ahead. One query, no network."""
        with self._sessions() as session:
            target = self._target(session, app)
            head = revisions.head_revision(session, target.id)
            newest_delivered = session.scalar(
                select(func.max(Revision.rev)).where(
                    Revision.target_id == target.id,
                    Revision.tenant_id == current_tenant_id(),
                    Revision.delivered_sha.is_not(None),
                )
            )
            if head is None:
                return DeliveryState(
                    rev=None,
                    tree_hash=None,
                    delivered_sha=None,
                    revisions_ahead=0,
                    ever_delivered=newest_delivered is not None,
                )
            # Count the revisions newer than the last delivered one, rather
            # than subtracting rev numbers: `rev` is monotonic per target, but
            # the count is what "N ahead" means to the operator reading it.
            ahead = session.scalar(
                select(func.count(Revision.id)).where(
                    Revision.target_id == target.id,
                    Revision.tenant_id == current_tenant_id(),
                    Revision.rev > (newest_delivered or 0),
                )
            )
            return DeliveryState(
                rev=head.rev,
                tree_hash=head.tree_hash,
                delivered_sha=head.delivered_sha,
                revisions_ahead=int(ahead or 0),
                ever_delivered=newest_delivered is not None,
            )

    def record_delivered(self, app: str, sha: str) -> None:
        """Record the commit a push produced, on the revision it delivered.

        The only writer of this column. "What exactly did we push, and from
        what?" becomes a row rather than an archaeology exercise.
        """
        with self._sessions() as session:
            target = self._target(session, app)
            head = revisions.head_revision(session, target.id)
            if head is None:
                raise DeliveryError(
                    f"target {app!r} has no head revision to record a delivery against"
                )
            head.delivered_sha = sha
            session.commit()

    # --- plumbing ---------------------------------------------------------

    @staticmethod
    def _target(session, app: str) -> Target:
        if not app:
            raise DeliveryError("a target is required")
        target = session.scalars(
            select(Target).where(
                Target.app == app, Target.tenant_id == current_tenant_id()
            )
        ).one_or_none()
        if target is None:
            raise DeliveryError(f"no such target: {app!r}")
        return target
