"""Who "we" are for the current request: the tenant, and the acting user.

Every table carries `tenant_id` from P2 onward (DESIGN.md §13). P2 bought, by
carrying the column even while there was one tenant, that P5 is a data backfill
plus *one* replacement -- this module. Every insert sets `tenant_id` from here
and every read filters on it, so the request-scoped version lands in one place
instead of being chased through every query.

**The replacement is a scope, not a new argument.** `current_tenant_id()` reads
a `ContextVar` set for the duration of whoever is acting:

* a request sets it from the authenticated user's session (app/auth.py's
  `require_auth`), which is async so the value propagates into the sync endpoint
  and every repo call it makes;
* a run on the thread/CI path sets it from the run's own `tenant_id`
  (app/launcher.py), because that work has no request behind it.

Outside any scope the resolver **raises** (`NoTenantScope`, P5-11). It used to
answer `DEFAULT_TENANT_ID`, and that default was load-bearing in exactly the
wrong direction: it meant a route that forgot its auth dependency, or
background work that forgot to bind a scope, quietly read and wrote the first
customer's rows. Story 6 asks for the opposite -- a missing filter should fail
closed rather than leak -- so the resolver no longer guesses. The constant
remains what the migrations seed, what the CLI defaults to and what the test
harness binds; it is simply not something resolution falls back on.

Every path with no request behind it therefore binds its tenant itself: the
maintenance sweeps one tenant at a time (`reaper._for_each_tenant`), the
heartbeat thread by copying its caller's context, the operator CLI from
`--tenant`, and the test suite from an autouse fixture (tests/conftest.py).

Do not inline the constant at call sites, and do not thread a tenant argument
through them. The indirection is the point.

**The acting user lives here too** (`current_actor`, P5-07), resolved the same
way and bound by the same dependency. It is here rather than in `app/audit.py`
because this module is the one that answers "who is acting", and because
`app/auth.py` -- which binds both -- would otherwise have to import the ORM to
reach the audit module. `audit.record` reads it; nothing else needs to.

The two are deliberately *not* one object. A tenant is resolved on every path
including the ones with no user at all (a run, a background sweep), and
collapsing them would mean inventing a user for those.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import MappingProxyType

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

# Seeded by the migration that introduces the tenants table.
DEFAULT_TENANT_ID = 1

# None means "no scope is active"; the resolver turns that into the default. A
# ContextVar rather than a thread-local because the request path is async (the
# value is set in an async dependency and read in the threadpooled endpoint),
# and contextvars are what propagate across that boundary and isolate one
# request's tenant from another's.
_current_tenant: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_tenant_id", default=None
)


class NoTenantScope(RuntimeError):
    """Raised when the current tenant is resolved with nothing acting.

    Its own class rather than a bare `RuntimeError`, for two reasons. The read
    guard resolves the tenant inside SQLAlchemy's `do_orm_execute`, so this
    surfaces from the middle of arbitrary query machinery and a caller that
    wants to distinguish "no scope" from "the database is down" needs something
    to catch. And `app/api.py` turns it into a 500 deliberately -- see the
    handler there -- which takes a type, not a message.
    """


def current_tenant_id() -> int:
    """The tenant owning the work in progress.

    Resolved from the active scope: a request's authenticated user
    (`auth.require_auth`), a run acting under its own token
    (`control.service.acting_as`), a maintenance sweep binding each tenant in
    turn (`reaper._for_each_tenant`), or an operator at the CLI (`--tenant`).

    **With no scope active this raises** (P5-11, story 6). It used to answer
    `DEFAULT_TENANT_ID`, which made the one guarantee the spec asks for --
    "structurally unable to read another tenant's data ... a missing filter is
    a bug that fails closed rather than a leak" -- the one property the design
    did not have. A route that forgot its auth dependency served the first
    customer's rows; a background job that forgot to bind a scope maintained
    the first customer's rows; and both looked exactly like working code,
    because the resolver answered a real tenant to a question nobody had the
    standing to ask.

    Failing here rather than at each call site is the whole value of the seam:
    one function refuses, and every read filter and every insert built on it
    refuses with it.
    """
    tenant_id = _current_tenant.get()
    if tenant_id is None:
        raise NoTenantScope(
            "no tenant scope is active, so there is no tenant to act as. A "
            "request resolves one from the authenticated user "
            "(auth.require_auth -- check the route has its auth dependency); "
            "a run from its token (control.service.acting_as); background "
            "work and the CLI must bind one explicitly with "
            "tenancy.tenant_scope()."
        )
    return tenant_id


def set_current_tenant(tenant_id: int) -> None:
    """Bind the current tenant for the rest of this context, with no unbinding.

    What `require_auth` uses: a dependency cannot wrap the request in a
    `finally`, so there is nowhere to restore from. Nothing is leaked by that,
    because the server gives each request its own task and therefore its own
    `Context` -- one request's tenant is not visible to the next. Code that
    *does* own a begin and an end uses `tenant_scope` instead.
    """
    _current_tenant.set(tenant_id)


@contextmanager
def tenant_scope(tenant_id: int) -> Iterator[None]:
    """Bind the current tenant for the duration of a block, then restore it.

    The form the background paths use (app/launcher.py): they own a clear
    begin/end around a run, so they get the `finally` a request dependency
    cannot have. Nests correctly, so an outer scope is restored on exit.
    """
    token = _current_tenant.set(tenant_id)
    try:
        yield
    finally:
        _current_tenant.reset(token)


# --- the acting user ------------------------------------------------------
#
# The audit log's `actor` (P5-07, #37). Scoped exactly like the tenant above,
# and for the same two reasons: the request path is async, so a ContextVar is
# what carries the value into the threadpooled endpoint; and threading an
# acting user through every call site would make every new call site a chance
# to pass the wrong one.

# What the actor is when nobody is logged in: the delivery CLI (`make
# deliver`), a console session, a background sweep. A real answer rather than a
# missing one -- those genuinely are not a user, and `system` says so. What it
# must never become is a stand-in for a user the code failed to resolve, which
# is why `auth.require_auth` binds the actor for every authenticated request
# rather than each route remembering to.
SYSTEM_ACTOR = "system"

_current_actor: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_actor", default=None
)


def current_actor() -> str:
    """Who is acting: the authenticated user's email, or `SYSTEM_ACTOR`."""
    actor = _current_actor.get()
    return SYSTEM_ACTOR if actor is None else actor


def set_current_actor(actor: str) -> None:
    """Bind the acting user for the rest of this context, with no unbinding.

    The sibling of `set_current_tenant`, used by `require_auth` for the reason
    given there: a dependency cannot wrap the request in a `finally`, and
    nothing leaks because each request has its own `Context`.
    """
    _current_actor.set(actor)


@contextmanager
def actor_scope(actor: str) -> Iterator[None]:
    """Bind the acting user for the duration of a block, then restore it."""
    token = _current_actor.set(actor)
    try:
        yield
    finally:
        _current_actor.reset(token)


# --- the enforced read and write path --------------------------------------
#
# The *insert* side of tenancy was always one line at each call site
# (`tenant_id=current_tenant_id()`), visible in review and asserted
# structurally by tests/test_tenancy.py. The read side was not: a `select()`
# that forgot `.where(tenant_id == ...)` looked exactly like one that did not
# need it, and three modules filtered by hand while `repo.py` -- the module
# every route goes through -- did not filter at all. That is how
# `/artifacts/{id}/content` came to stream any tenant's bytes to any logged-in
# user: nothing was wrong with the route, and nothing could have been seen to
# be missing from it.
#
# So the filter stops being something a query remembers. One listener adds it
# to every ORM SELECT, and forgetting is no longer possible -- what is possible
# is *bypassing*, which takes an explicit execution option and is therefore
# something a reviewer and a test can both find. #32's criterion, in one
# sentence: a query that bypasses the filter is the detectable exception, not
# the silent default.

# The execution option that opts a statement out. Named, rather than a bare
# string at each call site, so the allowlist test can find every user of it.
ACROSS_TENANTS = "qa_across_tenants"

# The same option as a mapping, for `Session.get()`, which takes
# `execution_options=` as a mapping rather than as keywords. Read-only: it is
# module-level and shared, and a caller that mutated it would silently change
# what every other bypass means.
ACROSS_TENANTS_OPTION: Mapping[str, bool] = MappingProxyType({ACROSS_TENANTS: True})


def across_tenants(statement):
    """Opt this statement out of the tenant filter. **Read the list first.**

    There are exactly three legitimate reasons, all of them "no tenant is
    acting yet, or every tenant is":

    1. **Login.** `repo.get_user_for_login` runs before a current tenant
       exists -- deciding which tenant is acting is its job. It is scoped by
       the slug the caller typed instead.
    2. **Resolving a reaped run's tenant.** `reaper._tenant_of` reads the run
       row in order to *open* the scope, so it cannot already be inside it.
       (This reason used to name `launcher._run_tenant_scope`; P5-05 deleted
       that function, because the run-scoped token now carries the tenant.)
    3. **The background sweeps.** The reaper and the log prune run on a timer
       with no request and no run behind them, so `current_tenant_id()` would
       answer the seeded default and they would quietly maintain tenant 1
       alone -- every other tenant's crashed runs holding their apps for ever.

    Anything else is a bug. A new call site must be added to the allowlist in
    tests/test_tenant_isolation_repo.py, which is the test that makes this
    function an exception rather than an escape hatch.
    """
    return statement.execution_options(**ACROSS_TENANTS_OPTION)


def install_tenant_guard(tenant_owned: type) -> None:
    """Filter every ORM read *and bulk write* of a tenant-owned entity by the
    current tenant.

    Named `install_read_guard` until P5-12, when it grew to cover ORM bulk
    `UPDATE` and `DELETE`: the old name made the same claim the old docstring
    did, and a guard whose name says "read" is one a reviewer will assume does
    not cover a write.

    `tenant_owned` is the mixin every table with a `tenant_id` inherits
    (`models.TenantOwned`); `with_loader_criteria` applies the criteria to all
    of its mapped subclasses at once, which is what makes this one listener
    cover the whole schema instead of one entity.

    **What it covers**, each confirmed against a real session rather than
    assumed: entity selects, `Session.get()` (so a direct-id read of someone
    else's row answers `None`, and every `repo.get_*` raises `NotFound`),
    column and aggregate selects, lazy relationship loads -- the criteria
    propagates from the originating query, so `run.steps` cannot walk into
    another tenant -- and, since P5-12, **ORM bulk `UPDATE` and `DELETE`**.

    The writes were the half this guard spent its first version not covering,
    and the docstring said so where the code could not. "A missing filter is a
    bug that fails closed rather than a leak" (#30, story 6) has no reading
    under which a bulk write is exempt: `update(Project).where(Project.id == n)`
    reached any tenant's row by id, and renaming or deleting another customer's
    rows is worse than reading them. The filter arrives as a `WHERE` clause, so
    such a statement now matches nothing rather than raising -- the row is
    untouched, which is the same shape as a filtered read coming up empty.

    An `INSERT` is deliberately not in that list: there is no existing row to
    narrow, and the write side sets `tenant_id` from `current_tenant_id()` at
    each call site, which is the seam the column was carried for.

    **What it asks a tenant for.** Every statement except one it can prove
    touches nothing tenant-owned -- a select of `tenants` itself, the one table
    with no `tenant_id`. Since P5-11 made resolution raise outside a scope,
    resolving for every statement would have turned "I have nothing to filter
    here" into "you may not run this". The proof has to run in the fail-closed
    direction, and the comment at the check says why: a statement whose mappers
    are not visible is filtered, not waved through.

    **What it does not cover**, and must not be mistaken for covering:

    * **Raw SQL.** `session.execute(text(...))` is not an ORM statement.
      The test fixtures' TRUNCATE is the only such thing in the tree.
    * **The identity map.** A row already loaded in a session is returned by
      `get()` without a SELECT, so a session that bypassed the filter once can
      hand that object back afterwards. No request does: the bypass is used by
      login and by background sweeps, which open their own sessions.

    The one bulk write that *must* span tenants -- `bus.prune_run_logs`, the
    retention sweep, whose job is the whole table -- declares it with
    `across_tenants()` and is on the allowlist for it. That is the shape every
    such path takes: a cross-tenant write is the detectable exception, not the
    silent default.

    Installed once, at import of app/models.py, so it is in force for the API,
    the orchestrator, the CLI and the tests alike. There is no "guard off"
    mode: a flag would mean the suite could prove isolation in a configuration
    production does not run in.
    """
    @event.listens_for(Session, "do_orm_execute")
    def _filter_by_tenant(state) -> None:
        if state.is_column_load or state.is_relationship_load:
            # A column load is a refresh of an already-loaded row, and a
            # relationship load inherits the criteria from the query that
            # loaded its parent; re-applying to either is at best redundant.
            return
        if not (state.is_select or state.is_update or state.is_delete):
            # An insert sets `tenant_id` from this module at each call site,
            # which is the write seam the column was carried for; there is no
            # existing row for a filter to narrow.
            return
        if state.execution_options.get(ACROSS_TENANTS):
            return
        # A statement that provably touches nothing tenant-owned has nothing to
        # filter, and so no business resolving a tenant. That distinction only
        # started to matter when resolution began to *raise* (P5-11): resolving
        # unconditionally meant a select of a table with no `tenant_id` at all
        # demanded a scope and failed without one -- the guard inventing a
        # requirement rather than enforcing one. `repo.list_tenant_ids` is the
        # case that proves it: a select of `tenants`, run by the reaper
        # precisely to discover which tenants to bind, necessarily before any
        # of them is bound. Failing it would have taken the maintenance loop
        # down every thirty seconds while looking like the fail-closed
        # guarantee doing its job.
        #
        # **"Provably" is load-bearing, and this is the fail-closed direction
        # of an otherwise innocuous optimisation.** `all_mappers` is empty for
        # an aggregate like `select(func.count()).select_from(Run)` -- the
        # shape `repo.tenant_usage` counts quotas with -- so a check written as
        # "skip unless some mapper is tenant-owned" skips the filter on exactly
        # the statements whose mappers it cannot see. That is not a missing
        # optimisation, it is an unfiltered read: the first version of this
        # made one tenant's runs count against another's quota, and
        # test_quotas.py caught it. So an empty or unreadable mapper list means
        # "filter it", and only a non-empty list with nothing owned in it is
        # allowed through.
        mappers = state.all_mappers
        if mappers and not any(
            issubclass(mapper.class_, tenant_owned) for mapper in mappers
        ):
            return
        # Resolved *outside* the lambda, and this is load-bearing rather than
        # stylistic. `with_loader_criteria`'s criteria is lambda SQL: the
        # lambda is analysed once and thereafter its *closure variables* are
        # re-extracted as bound parameters without the body being re-invoked.
        # A `current_tenant_id()` call inside the lambda would therefore be
        # evaluated once and baked in -- every later request reading the first
        # one's tenant, which is the exact bug this guard exists to prevent,
        # introduced by the guard itself. SQLAlchemy refuses that form outright
        # ("Can't invoke Python callable ... inside of lambda expression"),
        # which is how this was found; the local keeps it a tracked closure
        # variable, re-bound on every execution.
        tenant_id = current_tenant_id()
        state.statement = state.statement.options(
            with_loader_criteria(
                tenant_owned,
                lambda cls: cls.tenant_id == tenant_id,
                include_aliases=True,
            )
        )
