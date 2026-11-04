"""Who may log in: tenants and their users (P5-14 / #46).

Stories 1, 2 and 27 of #30. Before this, onboarding a second customer meant a
migration or hand-written SQL, and `app/domain/audit.py` carried a standing
note that two of #37's seven mutations could not be recorded because nothing
performed them.

The two halves are deliberately at different altitudes, and the tests follow:

- **user administration is a tenant's own business**, so it is tenant-scoped,
  admin-gated and reached from the portal. Those tests are here and in
  tests/test_api_users.py.
- **tenant creation is not**, because the person doing it belongs to no
  tenant yet. There is no platform role to gate an HTTP route with, so it is
  an operator CLI. See docs/adr/0002-tenant-creation-is-an-operator-action.md,
  and `test_onboarding_cli.py` for the command.
"""

from __future__ import annotations

import pytest

from app import accounts, audit, repo
from app.domain.audit import Action
from app.domain.roles import UserRole
from app.models import Tenant, User
from app.tenancy import DEFAULT_TENANT_ID, actor_scope, tenant_scope

# The admin the P5 users migration seeds into the default tenant. It is a
# permanent fixture of the suite's database: conftest restores state by
# deleting every *other* user, so nothing can put this row back if a test
# removes it (conftest asserts it survived, and says so). Every test here
# therefore acts on accounts it created itself.
ADMIN = "admin@example.com"


@pytest.fixture()
def second_tenant(session):
    """Another customer, with an admin of their own.

    Two tenants in the fixture for the reason tests/test_control_service.py
    gives: a single-tenant fixture cannot fail the test that matters most.
    """
    tenant = Tenant(name="Second", slug="second")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    with tenant_scope(tenant.id):
        theirs = accounts.add_user(
            session, email="boss@second.example", role=UserRole.ADMIN
        )
    return tenant, theirs.user


# --- adding a user -------------------------------------------------------

def test_an_added_user_belongs_to_the_acting_tenant_and_can_log_in(session):
    with tenant_scope(DEFAULT_TENANT_ID), actor_scope(ADMIN):
        added = accounts.add_user(
            session, email="new@example.com", role=UserRole.MEMBER
        )

    assert added.user.tenant_id == DEFAULT_TENANT_ID
    assert added.user.role is UserRole.MEMBER
    # The generated password is returned **once** and is not the stored value.
    assert added.password
    assert added.user.credential != added.password
    with tenant_scope(DEFAULT_TENANT_ID):
        found = repo.get_user_for_login(
            session, tenant_slug="default", email="new@example.com"
        )
    assert found is not None


def test_an_added_user_is_audited_naming_the_acting_admin(session):
    with tenant_scope(DEFAULT_TENANT_ID), actor_scope(ADMIN):
        accounts.add_user(session, email="new@example.com", role=UserRole.MEMBER)

        rows = [e for e in audit.entries(session) if e.action is Action.USER_ADD]

    (row,) = rows
    assert row.actor == ADMIN
    assert row.before is None, "there was no account before"
    assert row.after["email"] == "new@example.com"
    assert row.after["role"] == "member"
    # The password must not be anywhere in the trail, generated or not: the
    # audit log is read by people who are not entitled to log in as this user.
    assert "password" not in str(row.after).lower()


def test_an_email_already_taken_in_this_tenant_is_refused(session):
    with tenant_scope(DEFAULT_TENANT_ID), actor_scope(ADMIN):
        accounts.add_user(session, email="new@example.com", role=UserRole.MEMBER)

        with pytest.raises(accounts.AccountError, match="already"):
            accounts.add_user(session, email="new@example.com", role=UserRole.ADMIN)


def test_the_same_email_can_belong_to_two_different_tenants(session, second_tenant):
    """`users.email` is unique *per tenant*, and this is the behaviour that
    constraint exists for: a contractor both customers employ gets an account
    from each, and the first to claim the address does not lock the other out.
    """
    tenant, _theirs = second_tenant
    with tenant_scope(DEFAULT_TENANT_ID), actor_scope(ADMIN):
        accounts.add_user(session, email="contractor@x.example", role=UserRole.MEMBER)
    with tenant_scope(tenant.id), actor_scope("boss@second.example"):
        accounts.add_user(session, email="contractor@x.example", role=UserRole.MEMBER)

    with tenant_scope(tenant.id):
        assert len(accounts.list_users(session)) == 2


# --- removing a user -----------------------------------------------------

def test_a_removed_user_is_gone_and_audited(session):
    with tenant_scope(DEFAULT_TENANT_ID), actor_scope(ADMIN):
        added = accounts.add_user(
            session, email="new@example.com", role=UserRole.MEMBER
        )

        accounts.remove_user(session, added.user.id)

        assert [u.email for u in accounts.list_users(session)] == [ADMIN]
        (row,) = [e for e in audit.entries(session) if e.action is Action.USER_REMOVE]
    assert row.actor == ADMIN
    assert row.before["email"] == "new@example.com"
    assert row.after is None, "there is no account afterwards"


def test_the_last_admin_cannot_be_removed_and_the_refusal_says_why(
    session, second_tenant
):
    """A tenant with no admin can never be administered again: nobody can add
    a user, change a cap or approve a delivery, and there is no surface that
    could fix it from inside. So this is refused rather than warned about.

    Driven in the *second* tenant, whose single admin this test is allowed to
    try to remove -- the default tenant's admin is the seeded row the suite
    cannot replace."""
    tenant, theirs = second_tenant
    with tenant_scope(tenant.id), actor_scope(theirs.email):
        (only_admin,) = accounts.list_users(session)

        with pytest.raises(accounts.AccountError) as refused:
            accounts.remove_user(session, only_admin.id)

        assert accounts.list_users(session), "nothing was removed"
    message = str(refused.value)
    assert "last admin" in message
    assert "another admin" in message, "the refusal says what to do instead"


def test_an_admin_can_be_removed_while_another_admin_remains(session):
    """The rule is about the *last* admin, not about admins."""
    with tenant_scope(DEFAULT_TENANT_ID), actor_scope(ADMIN):
        second = accounts.add_user(
            session, email="second-admin@example.com", role=UserRole.ADMIN
        )

        accounts.remove_user(session, second.user.id)

        assert [u.email for u in accounts.list_users(session)] == [ADMIN]


def test_an_admin_can_remove_themselves_if_they_are_not_the_last(
    session, second_tenant
):
    """Named rather than incidental, because it is the other half of the rule
    the ticket asks to have a defined answer. Leaving is allowed; leaving a
    tenant unadministrable is not, and the last-admin check already says which
    is which without a special case for "me".

    In the second tenant again: the acting admin removes their *own* account,
    which is the thing being tested, and the seeded admin must survive the
    suite."""
    tenant, theirs = second_tenant
    with tenant_scope(tenant.id), actor_scope(theirs.email):
        accounts.add_user(session, email="other-admin@second.example", role=UserRole.ADMIN)
        me = next(u for u in accounts.list_users(session) if u.email == theirs.email)

        accounts.remove_user(session, me.id)

        assert [u.email for u in accounts.list_users(session)] == [
            "other-admin@second.example"
        ]


def test_a_member_is_not_an_admin_for_the_purposes_of_that_rule(
    session, second_tenant
):
    """A tenant whose only admin is removed in favour of a member is still a
    tenant nobody can administer, so members do not count."""
    tenant, theirs = second_tenant
    with tenant_scope(tenant.id), actor_scope(theirs.email):
        accounts.add_user(session, email="member@second.example", role=UserRole.MEMBER)
        (only_admin,) = [
            u for u in accounts.list_users(session) if u.role is UserRole.ADMIN
        ]

        with pytest.raises(accounts.AccountError, match="last admin"):
            accounts.remove_user(session, only_admin.id)


# --- the tenant boundary -------------------------------------------------

def test_another_tenants_user_cannot_be_removed_by_id(session, second_tenant):
    """The id is guessable, so this is the one that matters. The enforced read
    filter is what refuses it -- the user is simply not found inside the
    acting tenant -- rather than a comparison this module could forget."""
    _tenant, theirs = second_tenant

    with tenant_scope(DEFAULT_TENANT_ID), actor_scope(ADMIN):
        with pytest.raises(accounts.AccountError, match="no such user"):
            accounts.remove_user(session, theirs.id)

    assert session.get(User, theirs.id) is not None


def test_listing_users_shows_only_the_acting_tenants(session, second_tenant):
    tenant, _theirs = second_tenant

    with tenant_scope(DEFAULT_TENANT_ID):
        ours = {u.email for u in accounts.list_users(session)}
    with tenant_scope(tenant.id):
        mine = {u.email for u in accounts.list_users(session)}

    assert ours == {ADMIN}
    assert mine == {"boss@second.example"}


def test_no_password_hash_is_handed_back_by_the_listing(session):
    """The listing feeds a portal table. A credential hash is not something a
    browser needs, and an API that sends one invites it being stored."""
    with tenant_scope(DEFAULT_TENANT_ID):
        (admin,) = accounts.list_users(session)

    assert not hasattr(admin, "credential")
