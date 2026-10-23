"""Who "we" are for the current request.

Every table carries `tenant_id` from P2 onward (DESIGN.md §13), but there is
still exactly one tenant and nothing that could tell two apart: no per-tenant
auth, no quotas, no tenant-scoped sessions. All of that is P5.

What P2 buys by carrying the column anyway is that P5 becomes a data backfill
plus *one* replacement -- this function. Every insert sets `tenant_id` from
here, and every read filters on it, so the request-scoped version lands in one
place instead of being chased through every query.

Do not inline the constant at call sites. The indirection is the point.
"""

from __future__ import annotations

# Seeded by the migration that introduces the tenants table.
DEFAULT_TENANT_ID = 1


def current_tenant_id() -> int:
    """The tenant owning the work in progress.

    P5 resolves this from the authenticated session; until then there is one
    tenant and it is this one.
    """
    return DEFAULT_TENANT_ID
