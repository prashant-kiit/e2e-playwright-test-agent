"""Who "we" are for the current request.

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
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

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


def set_current_tenant(tenant_id: int) -> contextvars.Token:
    """Bind the current tenant for the rest of this context. Returns the token
    `reset_current_tenant` restores from. Used by `require_auth`, where a
    dependency cannot wrap the request in a `finally`; task isolation frees it."""
    return _current_tenant.set(tenant_id)


def reset_current_tenant(token: contextvars.Token) -> None:
    _current_tenant.reset(token)


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
