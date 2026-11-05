"""Offboarding: remove a tenant's rows and sweep its storage. P5-15 / #47.

Story 32 -- "deleting a tenant to purge that tenant's entire storage prefix and
rows, so that offboarding is clean" -- and the largest piece of #30 that was
never built. Two modules deferred it by name in comments (`app/audit.py` for
the audit trigger, `app/domain/quotas.py` for the absence of any tenant
lifecycle at all) and none of the original seven tickets covered it.

**The order is the whole design**, because the requirement is that a purge
which fails halfway is safe to run again:

    1. the store, under `tenant/<id>/`     (idempotent: delete ignores misses)
    2. the tenant's rows, table by table   (idempotent: deleting none is fine)
    3. the audit rows, trigger disabled    (the one permitted exception)
    4. the `tenants` row itself            (last, so a crash leaves a handle)
    5. the `purge_log` row                 (the thing that survives it)

The tenant row goes **last** on purpose. It is what the slug resolves to, so a
purge interrupted at any earlier step can be re-run by the same command with
the same argument and will finish; one that deleted it first would leave an
operator holding a slug that resolves to nothing and a bucket prefix nobody can
name. Step 5 is after step 4 for the same reason it is a separate table: it
records a completed purge, and an interrupted one is not that.

**No tenant bypass, and that is a deviation from what #47 expected.** The
ticket says purge "must use the documented bypass rather than quietly escaping
the guard". It does not need to: P5-12 (#44) put ORM `UPDATE`/`DELETE` under
the tenant guard, so a delete issued inside `tenant_scope(tenant_id)` is
*scoped by the guard* to exactly the rows being purged. That is strictly
stronger than opting out -- the guard becomes the mechanism rather than the
obstacle -- and `tests/test_tenant_isolation_repo.py`'s allowlist asks for
precisely this ("ask first whether the read can be done inside a tenant scope
instead"). The two reads that *are* outside any tenant -- resolving the slug
and deleting the `tenants` row -- touch `Tenant`, which is not `TenantOwned`
and has never been guarded: its id *is* the tenant.

**The audit trigger is disabled for one statement, inside the transaction.**
That is the exception the spec allows and the migration anticipated, spelled
the way it asked for: an explicit, reviewable `ALTER TABLE ... DISABLE
TRIGGER`, re-enabled in the same transaction. It needs table-owner rights,
which is worth knowing before running this as a reduced-privilege application
role in production.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from .. import db
from ..domain import store_keys
from ..models import AuditLog, Base, PurgeLog, Run, Tenant, TenantOwned
from ..storage import Storage
from ..tenancy import current_actor, tenant_scope

log = logging.getLogger(__name__)

# The trigger the P5-07 migration installs on `audit_log`, named here because
# this module is the one thing allowed to switch it off.
_AUDIT_TRIGGER = "audit_log_append_only"


class PurgeError(Exception):
    """The purge was refused. Never raised after anything has been deleted."""


@dataclass
class PurgeReport:
    """What a purge removed. Printed by the command and stored in `purge_log`."""

    tenant_id: int
    slug: str
    name: str
    objects: int = 0
    rows: dict[str, int] = field(default_factory=dict)

    @property
    def total_rows(self) -> int:
        return sum(self.rows.values())

    def __str__(self) -> str:
        tables = ", ".join(
            f"{table} {count}" for table, count in sorted(self.rows.items()) if count
        )
        return (
            f"tenant {self.tenant_id} ({self.slug}): {self.objects} object(s), "
            f"{self.total_rows} row(s)" + (f" [{tables}]" if tables else "")
        )


def _owned_tables() -> list[str]:
    """Every tenant-owned table, in an order safe to delete in.

    Derived from the mapped classes rather than listed, so a table added later
    is purged without anybody remembering to come back here -- the same
    argument `install_tenant_guard` makes for covering the whole schema in one
    call, and the same one `tests/conftest.py` makes for its TRUNCATE.

    Reverse dependency order, because every `tenant_id` FK is `ondelete=
    RESTRICT`: a child row must go before its parent, and the parent `tenants`
    row before nothing at all.
    """
    owned = {
        mapper.class_.__tablename__
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, TenantOwned)
    }
    return [
        table.name
        for table in reversed(Base.metadata.sorted_tables)
        if table.name in owned
    ]


def purge_tenant(
    session: Session,
    store: Storage,
    *,
    slug: str,
    confirm_slug: str,
) -> PurgeReport:
    """Remove everything belonging to the tenant `slug` names.

    `confirm_slug` must equal `slug`. Not a boolean flag: a `--yes` can be
    pasted into any invocation, while naming the tenant again cannot be
    confirmed for the wrong one by accident. This is the only operation in the
    system with no undo and no backup behind it, so the gate is the argument
    rather than a prompt -- a prompt would also make it un-scriptable, and an
    operator who scripts it still has to spell the tenant twice.
    """
    slug = slug.strip().lower()
    if confirm_slug.strip().lower() != slug:
        raise PurgeError(
            f"refusing to purge {slug!r}: the confirmation named "
            f"{confirm_slug.strip().lower()!r}. Both must be the same tenant, "
            f"because this cannot be undone"
        )
    # `Tenant` is not tenant-owned -- its id *is* the tenant -- so this read is
    # outside any scope by construction rather than by opting out.
    tenant = session.scalars(select(Tenant).where(Tenant.slug == slug)).one_or_none()
    if tenant is None:
        raise PurgeError(
            f"no tenant with slug {slug!r}. A purge interrupted earlier leaves "
            f"this row in place, so if the slug is gone the purge finished"
        )
    report = PurgeReport(tenant_id=tenant.id, slug=tenant.slug, name=tenant.name)
    actor = current_actor()

    # 1. The store first. Nothing references these objects once the rows go, so
    #    doing them first means an interrupted purge leaves rows pointing at
    #    missing bytes -- which is recoverable (re-run) -- rather than objects
    #    nothing can name, which is not.
    #
    #    The tenant prefix, **and** this tenant's runs under the pre-P5-10
    #    artifact shape. Those are read from the `runs` rows, so they have to
    #    be collected before step 2 deletes them.
    report.objects = _sweep_storage(store, tenant.id, _legacy_prefixes(session, tenant.id))

    with tenant_scope(tenant.id):
        # 2. and 3. Every owned table, with the audit log's trigger off for
        #    exactly as long as its own delete takes.
        for table in _owned_tables():
            report.rows[table] = _delete_table(session, table)
        session.commit()

    # 4. The tenant row, last: until it is gone, the slug still resolves and
    #    the command can be re-run.
    session.delete(tenant)
    session.commit()

    # 5. The record that outlives all of it.
    session.add(
        PurgeLog(
            purged_tenant_id=report.tenant_id,
            slug=report.slug,
            name=report.name,
            actor=actor,
            removed={"objects": report.objects, **report.rows},
        )
    )
    session.commit()
    log.info("purged %s", report)
    return report


def _delete_table(session: Session, table: str) -> int:
    """Delete the acting tenant's rows from one table, and count them.

    The count is read before the delete rather than taken from
    `result.rowcount`, because the report is the only evidence this operation
    leaves and `rowcount` is a driver-dependent promise. Both reads are inside
    the tenant scope, so both are filtered by the guard.
    """
    model = _model_for(table)
    count = session.scalar(select(func.count()).select_from(model))
    if not count:
        return 0
    if table == AuditLog.__tablename__:
        # The one exception #30 allows, and the spelling the P5-07 migration
        # asked for: explicit, reviewable, and re-enabled in the same
        # transaction so no other statement can slip through behind it.
        session.execute(text(f"ALTER TABLE audit_log DISABLE TRIGGER {_AUDIT_TRIGGER}"))
        try:
            session.execute(delete(model))
        finally:
            session.execute(
                text(f"ALTER TABLE audit_log ENABLE TRIGGER {_AUDIT_TRIGGER}")
            )
    else:
        session.execute(delete(model))
    return count


def _model_for(table: str):
    for mapper in Base.registry.mappers:
        if mapper.class_.__tablename__ == table:
            return mapper.class_
    raise AssertionError(f"no mapped class for {table!r}")  # pragma: no cover


def _legacy_prefixes(session: Session, tenant_id: int) -> list[str]:
    """`<run_key>/` for each of this tenant's runs. Pre-P5-10 artifact keys.

    The tenant prefix is a true description of "everything this tenant owns"
    only for objects written since P5-10 (#42) moved artifacts under it. A
    deployment that has not run `python -m app.artifacts rekey`, or whose run
    was interrupted between updating a row and deleting the old object, still
    has objects keyed by run alone -- outside the tenant prefix, and therefore
    outside what the sweep below would find.

    Leaving them would make "offboarding leaves nothing behind" false for
    exactly the deployments that have been running longest. So the purge reads
    its own run keys and sweeps those prefixes too. Read **before** step 2
    deletes the `runs` rows, because afterwards there is nothing left to derive
    them from -- which is also why this is not a separate pass somebody could
    forget to run.
    """
    with tenant_scope(tenant_id):
        run_keys = session.scalars(select(Run.run_key)).all()
    return [store_keys.legacy_run_prefix(key) for key in run_keys]


def _sweep_storage(store: Storage, tenant_id: int, extra_prefixes: list[str]) -> int:
    """Delete every object under this tenant's prefixes. Returns the count
    **actually deleted**, which is not the same as the count listed.

    A `delete` that fails -- `AccessDenied` on a misconfigured bucket, say --
    is swallowed by `Storage.delete`, by design, because a purge must be
    re-runnable past an object that is already gone. That makes "how many did
    we list?" the wrong number to report: `purge_log` would record objects
    removed that are still in the bucket, in the one operation with no undo.
    So each key is re-checked with `exists` and only counted if it is really
    gone, and anything left is logged and reported.

    The listing is materialised before deleting because deleting while
    iterating a paginator is asking the store to be consistent about something
    it does not promise.
    """
    deleted = 0
    survived: list[str] = []
    for prefix in [store_keys.tenant_prefix(tenant_id), *extra_prefixes]:
        for key in list(store.list_keys(prefix)):
            store.delete(key)
            if store.exists(key):
                survived.append(key)
            else:
                deleted += 1
    if survived:
        # Not raised: the rows still have to go, or the tenant is half-purged
        # with no way to finish. Reported loudly instead, and the purge is
        # re-runnable -- but the `tenants` row is gone by then, so this line is
        # the only thing that will say which objects to chase.
        log.error(
            "purge of tenant %s left %d object(s) in the store: %s",
            tenant_id,
            len(survived),
            ", ".join(survived[:20]),
        )
    return deleted


def purge_with_own_session(
    store: Storage, *, slug: str, confirm_slug: str, session_factory=None
) -> PurgeReport:
    """`purge_tenant` for a caller with no session -- the command.

    The factory is resolved at call time through `db` rather than captured as a
    default argument, so the suite's `_no_dev_database` guard can refuse it.
    That is not theoretical: the same mistake in `artifacts.rekey` had a test
    quietly purging nothing from the developer's database (#42).
    """
    factory = session_factory or db.SessionLocal
    with factory() as session:
        return purge_tenant(
            session, store, slug=slug, confirm_slug=confirm_slug
        )
