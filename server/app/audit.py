"""The audit log: every control-plane mutation, and who authorized it.

P5-07 / #37. "Who authorized writing this commit into our repo, and when?" was
answerable only from logs -- which rotate, which are not tenant-scoped, and
which no customer can be shown. It is a table now: `audit_log(id, tenant_id,
actor, action, target, before, after, at)`, append-only, one row per mutation.

**The actor is a scope, not an argument**, and it lives in `app/tenancy.py`
alongside the tenant -- `current_actor()`, bound by `require_auth`. The reason
is the one `tenancy` gives at length: threading an acting user through every
call site means every new call site is a chance to pass the wrong one, and two
of the mutations recorded here (`repo.set_tenant_caps`, and the delivery CLI)
have no request behind them to thread it from. Outside any scope it is
`tenancy.SYSTEM_ACTOR`, which is a real answer rather than a missing one.

**A row is written after the mutation succeeds, never before**, so a crash in
between loses a row rather than inventing one. That is the correct direction
for a trail: an auditor who finds no row for a delivery has a gap they can see,
whereas one who finds a row for a delivery that never happened has been
actively misled. Nothing in the control plane treats the absence of a row as
permission.

Be precise about the transaction, because it is weaker than "its own": `record`
calls `commit()` on **the session it is handed**, which at every call site is
the request's session whose mutation has already committed. So the row is a
second commit on the same session, not an independent transaction -- and a
caller must not invoke it with unrelated pending ORM work, because that work
would be committed too. Recording only mutations that have already committed is
what keeps that safe.

**A dry run is not a mutation and is not recorded.** `POST .../deliver` and
`POST .../reset` with `dry_run` touch nothing in the customer's repo, so no row
is written: the trail is a record of mutations, and `delivery.approve` has to
stay a clean filter for "deliveries that actually happened" -- a reader who has
to check a flag on every row to find out which ones were real is being misled
by default.

**Text built from a subprocess or an exception must be redacted before it gets
here.** `infra.sync` is the one action whose payload is program output rather
than a known value, and a failing git push can echo a remote URL carrying the
PAT. The call site redacts and bounds it (`app/api.py`); this table is the last
place a credential should be able to land, because it is the one table nothing
may prune or delete.

**Append-only is enforced by the database.** A `BEFORE UPDATE OR DELETE`
trigger on `audit_log` raises, so the guarantee survives raw SQL, a psql
session and a future bulk delete -- not only code that goes through this
module. The one exception the spec allows is tenant purge (#30, story 32),
built by P5-15: `app/accounts/purge.py` disables the trigger explicitly
(`ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only`) for exactly
the one statement that removes a purged tenant's rows, and re-enables it in
the same transaction. That is a seam a reviewer can see, which was the point --
a purge that silently bypassed the trail would be the one write nobody
notices -- and a test asserts the trigger is back on afterwards, because a
purge that left it off would remove story 28's guarantee with nothing else in
the system noticing.

**That module is the only thing permitted to delete from this table**, and the
list is short enough to state: it holds the only `DISABLE TRIGGER` in the tree.
Deleting a user does *not* remove their audit rows -- `actor` is a copied
string rather than an FK for exactly that reason -- so offboarding a customer
is the only thing that erases any part of the trail.

**Never record a credential.** `before`/`after` hold the *state* either side of
a mutation, and a PAT save records that the credential state went from `absent`
to `valid` -- never the token, not even redacted. The rule is the one
`app/delivery/credentials.py` holds for logs, and `tests/test_audit.py` asserts
the token is absent from every column.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain.audit import Action
from .models import AuditLog
from .tenancy import current_actor, current_tenant_id

# `Action` is re-exported so a call site needs one import
# (`audit.record(..., action=audit.Action.X)`) rather than two that must stay
# in step.
__all__ = ["Action", "entries", "prompt_ref", "record", "target_ref", "tenant_ref"]

# --- naming the thing that was mutated ------------------------------------
#
# `audit_log.target` is a string rather than a polymorphic foreign key, because
# the rows outlive what they name: a target reset, a tenant purged, a prompt
# renamed, and the trail still has to read correctly afterwards. An FK with
# `ondelete RESTRICT` would make the audit log something that blocks deletes,
# and `ondelete SET NULL` would quietly erase what a row was about. These
# helpers keep the spelling consistent so filtering by prefix works.


def target_ref(app: str) -> str:
    """Name a target by its app slug -- the handle an operator recognises."""
    return f"target:{app}"


def tenant_ref(tenant_id: int | None = None) -> str:
    """Name a tenant. Used by the quota change, whose subject *is* the tenant."""
    return f"tenant:{current_tenant_id() if tenant_id is None else tenant_id}"


def prompt_ref(name: str) -> str:
    return f"prompt:{name}"


# --- the one writer -------------------------------------------------------

def record(
    session: Session,
    *,
    action: Action,
    target: str,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    """Append one row. There is no update and no delete, here or anywhere.

    The actor is **not** a parameter. It comes from `tenancy.current_actor()`,
    which is the whole point of binding it as a scope: a caller that could pass
    an actor is a caller that could pass the wrong one, and the only honest
    answer to "who did this?" is whoever the request authenticated. A console
    or the CLI binds nothing and gets `SYSTEM_ACTOR`, which is also honest.

    **Commits the session it is given**, which must therefore have no unrelated
    pending work on it -- see the module docstring.
    """
    row = AuditLog(
        tenant_id=current_tenant_id(),
        actor=current_actor(),
        action=action,
        target=target,
        before=before,
        after=after,
    )
    session.add(row)
    session.commit()
    return row


def entries(session: Session, *, limit: int | None = None) -> list[AuditLog]:
    """This tenant's trail, most recent first.

    An ordinary ORM select, so `tenancy.install_tenant_guard` adds the
    `tenant_id` filter -- the enforced read path #37's last criterion asks for,
    and the same mechanism as every other read in the tree rather than a
    hand-written `.where()` that could be forgotten.

    Ordered by `id` descending rather than by `at`: `at` is a server-side
    `now()`, which is the *transaction's* start time in Postgres, so two rows
    written by concurrent transactions can share a timestamp and sort
    arbitrarily. The id is monotonic, so "most recent first" is stable.
    """
    statement = select(AuditLog).order_by(AuditLog.id.desc())
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.scalars(statement))
