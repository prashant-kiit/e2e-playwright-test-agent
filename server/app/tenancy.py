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

Outside any scope the resolver answers `DEFAULT_TENANT_ID`. That default is not
a stand-in for "unknown": it is what keeps the pure-domain tests and any code
that runs before auth exists writing the one seeded tenant, exactly as the
constant did before P5.

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


def current_tenant_id() -> int:
    """The tenant owning the work in progress.

    Resolved from the active scope (a request's user, a run's row); the seeded
    default when there is no scope.
    """
    tenant_id = _current_tenant.get()
    return DEFAULT_TENANT_ID if tenant_id is None else tenant_id


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


# --- the enforced read path -----------------------------------------------
#
# The write side of tenancy was always one line at each insert
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


def install_read_guard(tenant_owned: type) -> None:
    """Filter every ORM SELECT of a tenant-owned entity by the current tenant.

    `tenant_owned` is the mixin every table with a `tenant_id` inherits
    (`models.TenantOwned`); `with_loader_criteria` applies the criteria to all
    of its mapped subclasses at once, which is what makes this one listener
    cover the whole schema instead of one entity.

    **What it covers**, each confirmed against a real session rather than
    assumed: entity selects, `Session.get()` (so a direct-id read of someone
    else's row answers `None`, and every `repo.get_*` raises `NotFound`),
    column and aggregate selects, and lazy relationship loads -- the criteria
    propagates from the originating query, so `run.steps` cannot walk into
    another tenant.

    **What it does not cover**, and must not be mistaken for covering:

    * **ORM UPDATE and DELETE.** `is_select` is false for them, so a bulk
      `delete(RunLog)` is unfiltered. Writes are reached through a guarded read
      first everywhere in `repo.py` (every mutator calls `get_run`/`get_target`
      before touching a row), and the one bulk delete there is --
      `bus.prune_run_logs` -- is a retention sweep that *should* span tenants.
      A future bulk write that must not span tenants has to say so itself.
    * **Raw SQL.** `session.execute(text(...))` is not an ORM statement.
      The test fixtures' TRUNCATE is the only such thing in the tree.
    * **The identity map.** A row already loaded in a session is returned by
      `get()` without a SELECT, so a session that bypassed the filter once can
      hand that object back afterwards. No request does: the bypass is used by
      login and by background sweeps, which open their own sessions.

    Installed once, at import of app/models.py, so it is in force for the API,
    the orchestrator, the CLI and the tests alike. There is no "guard off"
    mode: a flag would mean the suite could prove isolation in a configuration
    production does not run in.
    """
    @event.listens_for(Session, "do_orm_execute")
    def _filter_by_tenant(state) -> None:
        if not state.is_select or state.is_column_load or state.is_relationship_load:
            # A column load is a refresh of an already-loaded row, and a
            # relationship load inherits the criteria from the query that
            # loaded its parent; re-applying to either is at best redundant.
            return
        if state.execution_options.get(ACROSS_TENANTS):
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
