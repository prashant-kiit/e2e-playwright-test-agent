"""Move existing artifact objects under the tenant prefix. P5-10 / #42.

The contract half of expand-then-contract. New uploads are keyed
`tenant/<id>/runs/<run_key>/<path>` (app/domain/store_keys.py); objects written
before that are keyed `<run_key>/<path>`, and until they move, story 32's
"purge that tenant's entire storage prefix" is not true of them.

**Why this is a command and not an Alembic revision.** The rows are in Postgres
and the bytes are in an object store. A revision can rewrite `artifacts.s3_key`
and nothing else -- which would point every existing row at an object that is
not there, turning a cosmetic inconsistency into an outage for every artifact
in the system. Moving the bytes needs the store, and the store is not something
a migration has, so this is a maintenance command that does both in the only
order that is safe to interrupt.

**Safe to re-run, and safe to interrupt**, which are the same requirement here:
a half-finished pass leaves some rows moved and some not, and the next pass has
to finish rather than double-move. Each row is independent and the order within
one is fixed:

    1. copy the bytes to the new key   (idempotent: skipped if already there)
    2. update the row to the new key   (committed per row)
    3. delete the bytes at the old key (idempotent by `Storage.delete`)

Interrupted between 1 and 2, the next pass finds the new object already present
and skips to 2. Between 2 and 3 it finds the row already migrated and skips the
whole row -- leaving one orphaned old object. Nothing references it, so it is
harmless to read, and there is deliberately **no prune pass**: an orphan sits
outside the tenant prefix, so the thing that must not miss it is the tenant
purge, and `accounts.purge` sweeps each of a tenant's run prefixes as well as
the tenant prefix for exactly this reason. A separate prune command would be
one more thing to remember at the moment it matters least.

**Per tenant, inside each tenant's scope**, rather than one unfiltered read
across all of them. That is the shape `reaper._for_each_tenant` established and
the reason `tests/test_tenant_isolation_repo.py`'s allowlist asks for: this is
not one query but a read, a write and two store calls per row, so an unfiltered
outer query would need every nested operation opted out too, and the opt-out
would become the normal case in the one module that touches every tenant.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db, repo
from ..domain import store_keys
from ..models import Artifact
from ..storage import Storage, content_type_for
from ..tenancy import tenant_scope

log = logging.getLogger(__name__)


@dataclass
class Outcome:
    """What a pass did, in the terms the command prints.

    Counted rather than logged-and-forgotten because the operator running this
    needs to know whether a second pass is worth it, and "moved 0, already 418"
    is the answer that says no.
    """

    moved: int = 0
    already: int = 0
    missing: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return (
            f"moved {self.moved}, already migrated {self.already}, "
            f"bytes missing {self.missing}, failed {self.failed}"
        )


def _new_key_for(row: Artifact) -> str | None:
    """Where `row` should live, or None if it is already there.

    Returns None for a key that is already under a tenant prefix rather than
    recomputing one, so a row that has been moved is cheap to recognise and
    impossible to move twice.
    """
    if row.s3_key.startswith("tenant/"):
        return None
    run_key = store_keys.artifact_run_key(row.s3_key)
    if run_key is None:  # pragma: no cover - a blob key on an artifact row
        return None
    rel = row.s3_key[len(run_key) :].lstrip("/")
    return store_keys.artifact_key(row.tenant_id, run_key, rel)


def rekey_tenant(session: Session, store: Storage) -> Outcome:
    """Move the acting tenant's legacy artifact objects. One row at a time.

    Committed per row on purpose: the alternative is one transaction over a
    tenant's entire artifact history, held open across two store round trips
    per row, which is the kind of pass that gets killed halfway and leaves a
    rollback nobody wanted. Per-row commits are what make interruption
    uninteresting.
    """
    outcome = Outcome()
    rows = session.scalars(select(Artifact).order_by(Artifact.id)).all()
    for row in rows:
        new_key = _new_key_for(row)
        if new_key is None:
            outcome.already += 1
            continue
        old_key = row.s3_key
        try:
            if not store.exists(new_key):
                if not store.exists(old_key):
                    # The row names bytes that are not there. Left alone and
                    # counted: re-keying it would move the inconsistency
                    # rather than fix it, and an operator needs to know the
                    # count -- "blob before row" means this should be zero.
                    log.warning(
                        "artifact %s names %s, which is not in the store; "
                        "leaving the row alone",
                        row.id,
                        old_key,
                    )
                    outcome.missing += 1
                    continue
                _copy(store, old_key, new_key)
            row.s3_key = new_key
            session.commit()
            # After the row, so an interrupted pass never leaves a row
            # pointing at bytes that have been deleted.
            store.delete(old_key)
            outcome.moved += 1
        except Exception:
            session.rollback()
            # One row's failure does not stop the tenant's others, for the
            # reason the reaper gives: a single wedged row must not be able to
            # hold up a pass whose whole job is to be re-runnable.
            log.exception("could not re-key artifact %s (%s)", row.id, old_key)
            outcome.failed += 1
    return outcome


def _copy(store: Storage, old_key: str, new_key: str) -> None:
    """Copy one object, through a temp file because `put_file` takes a path.

    A real S3 would do this server-side with `CopyObject`, and that is a
    worthwhile optimisation the `Storage` protocol does not expose. It is not
    added here: this runs once per deployment, over a dataset measured in run
    artifacts, and a protocol method with one caller that disappears after the
    migration is the Speculative Generality a reviewer would rightly flag.
    """
    chunks, content_type = store.get_stream(old_key)
    with tempfile.TemporaryDirectory(prefix="qa-rekey-") as tmp:
        path = Path(tmp) / "object"
        with path.open("wb") as fh:
            for chunk in chunks:
                fh.write(chunk)
        store.put_file(new_key, path, content_type or content_type_for(new_key))


def rekey_all(store: Storage, *, session_factory=None) -> Outcome:
    """Every tenant, each inside its own scope. See the module docstring.

    `session_factory=None` resolved **here** rather than as a default
    argument, and that is not a style choice. A default is evaluated once when
    the function is defined, so `session_factory=SessionLocal` captures the
    real factory for ever and monkeypatching this module's `SessionLocal` has
    no effect -- which is how this function's own test silently connected to
    the *development* database instead of the test one, found 25 artifact rows
    from a real October run, and reported them as missing bytes. It did not
    write anything, by luck rather than by design: the fake store held none of
    those objects, so every row was skipped. A late-bound lookup is what makes
    the seam substitutable, and the store guard in tests/conftest.py is what
    would have caught the other half.
    """
    # `db.SessionLocal` through the module, not a name imported from it: the
    # suite's guard (tests/conftest.py `_no_dev_database`) patches the
    # attribute on `app.db`, so a module that bound the name at import would
    # sail past it and open a session on the *developer's* database. That guard
    # exists because P5-07 did exactly that, and its docstring claims every
    # such caller takes an injectable factory -- this keeps that claim true.
    session_factory = session_factory or db.SessionLocal
    with session_factory() as session:
        tenant_ids = repo.list_tenant_ids(session)
    total = Outcome()
    for tenant_id in tenant_ids:
        with tenant_scope(tenant_id), session_factory() as session:
            one = rekey_tenant(session, store)
        log.info("tenant %s: %s", tenant_id, one)
        total.moved += one.moved
        total.already += one.already
        total.missing += one.missing
        total.failed += one.failed
    return total
