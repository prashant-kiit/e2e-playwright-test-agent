"""Sessions that are dead before their cookie expires. #56.

`app/auth.py` buys cheap authentication by putting the claims in a signed
cookie and not reading the row: "a cheap stateless check beats a database
round-trip per request". UAT 3 (#54) found the case that argument does not
cover. A *downgrade* can wait for the next refresh -- the person still works
here. A **removal** cannot: an offboarded contractor or a compromised account
kept whatever role they had until their access cookie expired, and UAT 3
watched a removed admin spend those minutes creating another admin.

This module is the mechanism #56 chose, out of the four it weighed: a
revocation list. One small table, one read per authenticated request.

**Why this and not one of the other three.** Reading the `users` row per
request closes the window too, and costs the same round trip -- but it makes
every authenticated request depend on the whole of `users`, and
`app/auth.py`'s stated design disappears rather than gaining an exception.
Shortening the access cookie to ~2 minutes only makes the window smaller, and
a window that is merely small is still the window UAT 3 walked through.
Accepting it means writing down that a removal takes up to fifteen minutes to
take effect, which is not an answer anybody wants to give a customer about an
offboarding.

**What keeps it small**, which is the whole reason it is not the token table
`app/auth.py` and `app/run_token.py` both declined: a revocation stops
mattering once no cookie minted before it can still verify -- `ACCESS_MAX_AGE`
after it was written. A token table would have held a row per live session for
as long as sessions live; this holds a row per **removal**, and `revoke` prunes
the expired ones as it writes, so there is no sweep to schedule.

**What that prune does and does not reach**, stated exactly, because an earlier
version of this paragraph claimed more than the code does. The prune is an ORM
bulk `DELETE`, and since P5-12 those are under the tenant guard
(`tenancy.install_tenant_guard`), so it deletes **the acting tenant's** expired
rows and no others. A tenant that removes a user once and never again therefore
keeps that one row until it next removes somebody. That is the bound worth
having -- a row per removal, with every tenant's own removals keeping their own
list trimmed -- and it is not "the table holds only the last fifteen minutes".
Nothing reads an expired row: `is_revoked` bounds the question by `within`
rather than trusting the prune, which is also what stops an unpruned old row
from locking out an account that reuses the id.

**The window is a parameter, not an import.** Both functions take `within`,
and every caller passes `auth.ACCESS_MAX_AGE`. That is deliberate: how long a
session lives is `app/auth.py`'s decision, and `app/auth.py` is what imports
this module -- importing it back would be a cycle, and worse, it would make
this module an author of the cookie's lifetime rather than a reader of it.

**Neither function commits.** A revocation belongs to the same transaction as
the removal that caused it: committed separately, a crash in between would
leave a user removed and their cookie still working, which is the bug this
module exists to prevent. The opposite of `audit.record`, which commits the
session it is given -- and stated here for the same reason that is stated
there.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .models import RevokedUser
from .tenancy import current_tenant_id


def _cutoff(within: int) -> ColumnElement:
    """The database's "now" minus `within` seconds, as SQL.

    Built from `func.now()` rather than from Python's clock so the write and
    the read ask one clock the same question. `revoked_at` is written by a
    server default; a cutoff computed in the application would compare it
    against a different machine's idea of the time, and the whole guarantee is
    a comparison of two timestamps.
    """
    return func.now() - timedelta(seconds=within)


def revoke(session: Session, user_id: int, *, within: int) -> None:
    """Withdraw every session this user already holds. **Does not commit.**

    Called by the removal path, inside the same transaction as the `DELETE`,
    so there is no instant at which the user is gone and their cookie is not.

    It prunes while it writes: rows older than `within` cannot affect any
    cookie that still verifies, so they are deleted here rather than by a
    sweep somebody has to remember to schedule -- the only path that grows the
    list is also the path that shrinks it. **The prune is tenant-scoped**, like
    every other ORM bulk delete in this tree, so it trims the acting tenant's
    rows and leaves every other tenant's alone; see the module docstring for
    what that does and does not bound.
    """
    session.execute(delete(RevokedUser).where(RevokedUser.revoked_at < _cutoff(within)))
    session.add(RevokedUser(tenant_id=current_tenant_id(), user_id=user_id))


def is_revoked(session: Session, user_id: int, *, within: int) -> bool:
    """Has this user's access been withdrawn within the last `within` seconds?

    The question `require_auth` asks on every authenticated request. Tenant-
    filtered by the ordinary read guard, so a user id is only ever resolved
    inside the tenant the cookie itself names.

    **Bounded by `within` rather than trusting the prune**, which matters in
    the fail-closed direction: an unpruned old row must not lock a *new*
    account out, and the only way a user id can appear here and still own a
    valid cookie is a revocation newer than the cookie's maximum age. A row
    older than that says nothing about any cookie that still verifies.
    """
    return (
        session.scalar(
            select(func.count())
            .select_from(RevokedUser)
            .where(
                RevokedUser.user_id == user_id,
                RevokedUser.revoked_at >= _cutoff(within),
            )
        )
        > 0
    )
