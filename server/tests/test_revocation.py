"""The revocation list: #56's mechanism, at its own seam.

What `tests/test_auth.py` and `tests/test_api_users.py` prove about the
*window* -- a removed user's existing cookie stops working -- this proves about
the list underneath it: the window it answers within, that it prunes itself,
and that one tenant's revocation says nothing about another tenant's user ids.

The last one matters more than it looks. User ids are small integers, so tenant
2's user 7 and tenant 1's user 7 both exist; a revocation list that answered
"7 is revoked" without a tenant would log out an unrelated customer's user.
"""

from __future__ import annotations

import pytest

from app import revocation
from app.auth import ACCESS_MAX_AGE
from app.models import RevokedUser, Tenant
from app.tenancy import DEFAULT_TENANT_ID, tenant_scope

# The window every caller passes: how long a session lives is `app/auth.py`'s
# decision, and a second copy of the number here is how the test and the
# production call would come to ask different questions.
WINDOW = ACCESS_MAX_AGE


def test_a_revoked_user_is_revoked_and_an_untouched_one_is_not(session):
    revocation.revoke(session, 7, within=WINDOW)
    session.commit()

    assert revocation.is_revoked(session, 7, within=WINDOW) is True
    assert revocation.is_revoked(session, 8, within=WINDOW) is False


def test_revoke_does_not_commit(session):
    """The row belongs to the removal's transaction.

    `accounts.remove_user` deletes the `users` row and revokes in one
    transaction on purpose: a revocation committed separately leaves an
    instant in which the user is gone and their cookie still works, which is
    the bug the list exists to prevent. So this function must leave the commit
    to its caller, and a rollback must take the row with it.
    """
    revocation.revoke(session, 7, within=WINDOW)
    session.rollback()

    assert session.query(RevokedUser).count() == 0


def test_a_revocation_older_than_the_window_no_longer_revokes(session):
    """A row stops mattering once no cookie minted before it can still verify.

    Asserted by asking with a window of zero seconds rather than by waiting
    fifteen minutes: the row is in the past either way, and what is under test
    is the comparison, not the clock.
    """
    revocation.revoke(session, 7, within=WINDOW)
    session.commit()

    assert revocation.is_revoked(session, 7, within=0) is False


def test_writing_a_revocation_prunes_the_expired_ones(session):
    """The only path that grows the list is the path that shrinks it.

    This is what keeps the table "removals in the last fifteen minutes" rather
    than a row per removal for ever, with no sweep to schedule. The second
    `revoke` is given a zero-second window, which makes every existing row
    expired by definition.
    """
    revocation.revoke(session, 7, within=WINDOW)
    session.commit()

    revocation.revoke(session, 8, within=0)
    session.commit()

    assert [r.user_id for r in session.query(RevokedUser).all()] == [8]


@pytest.mark.unscoped_tenant
def test_the_prune_is_tenant_scoped_like_every_other_bulk_delete(session):
    """What the prune bounds, asserted rather than assumed.

    The prune is an ORM bulk `DELETE`, and since P5-12 those are under the
    tenant guard -- so it trims the acting tenant's expired rows and leaves
    another tenant's alone. An earlier version of `revocation.py` claimed the
    table held "removals from the last fifteen minutes and nothing else",
    which this is the test that would have contradicted. Nothing *reads* an
    expired row either way: `is_revoked` bounds the question by `within`.
    """
    other = Tenant(slug="other", name="Other")
    session.add(other)
    session.commit()
    with tenant_scope(other.id):
        revocation.revoke(session, 7, within=WINDOW)
        session.commit()

    with tenant_scope(DEFAULT_TENANT_ID):
        revocation.revoke(session, 8, within=0)
        session.commit()

    with tenant_scope(other.id):
        assert [r.user_id for r in session.query(RevokedUser).all()] == [7]


@pytest.mark.unscoped_tenant
def test_one_tenants_revocation_does_not_revoke_another_tenants_user_id(session):
    """Tenant-filtered, like every other read.

    The ids collide by construction -- both tenants have a user 7 -- so an
    unfiltered list would log tenant 1's user out because tenant 2 removed
    somebody.
    """
    other = Tenant(slug="other", name="Other")
    session.add(other)
    session.commit()

    with tenant_scope(other.id):
        revocation.revoke(session, 7, within=WINDOW)
        session.commit()
        assert revocation.is_revoked(session, 7, within=WINDOW) is True

    with tenant_scope(DEFAULT_TENANT_ID):
        assert revocation.is_revoked(session, 7, within=WINDOW) is False
