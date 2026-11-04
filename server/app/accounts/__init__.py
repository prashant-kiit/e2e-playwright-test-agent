"""Who may log in: tenants, and the users inside them. P5-14 / #46.

Stories 1, 2 and 27 of #30: a customer is onboarded as their own tenant, a
tenant admin invites and removes users within their tenant, and both show up in
the audit log. Before this there was no code path that added or removed a user
at all -- `app/domain/audit.py` carried a standing note saying so, and
onboarding a second customer meant a migration or hand-written SQL.

**Two altitudes, one module, and the split is the point.**

    add_user / remove_user / list_users   a tenant's own business: tenant
                                          scoped, admin gated, reached from
                                          the portal
    create_tenant                         not a tenant's business at all: the
                                          person doing it belongs to no tenant
                                          yet, so it is an operator action and
                                          has no HTTP route

They live together because they are one concept -- an account and the tenant
it belongs to are created by the same kind of decision -- and because the first
admin of a new tenant is literally `add_user` run inside the new tenant's
scope. Keeping them apart would mean two modules that both know how a user is
made. Why `create_tenant` is deliberately not a route is
docs/adr/0002-tenant-creation-is-an-operator-action.md.

**Every mutation here is audited, and the actor is never a parameter.** It
comes from `tenancy.current_actor()`, which is the request's authenticated user
on the portal path and `system` for the CLI -- "a human at a console did this
and we cannot say which human" being the honest answer, as
`app/delivery/__main__.py` already argues.

**The password is generated, returned once, and never stored in the clear.**
There is no mail in this deployment, so an invitation cannot be a link; the
alternative is an admin choosing a password on someone else's behalf, which is
a password that admin then knows for ever. So the server generates one, hands
it back exactly once in the response to the call that created the account, and
keeps only the hash. It is not in the audit row and not in any log. A real
invitation flow -- a one-time link, an expiry, a forced reset on first login --
needs an email path this deployment does not have, and is named as a follow-up
rather than half-built here.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..auth import hash_password
from ..domain.audit import Action
from ..domain.roles import UserRole
from ..models import Tenant, User
from ..tenancy import current_tenant_id, tenant_scope

# Long enough that it is not worth guessing, short enough to read down a phone
# to a colleague once. `token_urlsafe` is the CSPRNG, not `random`.
_PASSWORD_BYTES = 12


class AccountError(Exception):
    """A tenant or user could not be created or removed, and why.

    One type for every refusal here, because every one of them is something a
    human did that the portal should explain: a duplicate address, the last
    admin, a tenant slug already taken. The routes turn it into a 4xx with this
    message, so the message is the user-facing text and is written that way.
    """


class NoSuchUser(AccountError):
    """The acting tenant has no user with that id. The route answers 404.

    A subclass rather than the route matching on the message, which is what it
    did first: `status = 404 if message.startswith("no such user") else 409`
    made an HTTP status code depend on prose that is *simultaneously*
    user-facing text, so rewording the sentence for a human would silently
    change the status for a caller. The distinction belongs on the exception,
    where it is a decision rather than a coincidence.

    Deliberately the same answer for an id that does not exist and one that
    belongs to another tenant -- see `remove_user`.
    """


@dataclass(frozen=True)
class AddedUser:
    """A new account, and the one and only time its password exists in the clear.

    A pair rather than a bare `User`, because the password is not a property of
    the row -- the row has the hash -- and a caller that had to ask for it
    separately would be a caller that could forget to show it, leaving an
    account nobody can get into.
    """

    user: User
    password: str


@dataclass(frozen=True)
class Account:
    """One user, as the portal lists them: **no credential**.

    A projection rather than the ORM row, so the hash cannot reach a browser by
    being on an object somebody serialized whole. `test_accounts.py` asserts
    the attribute is absent rather than trusting the schema to omit it.
    """

    id: int
    email: str
    role: UserRole


def list_users(session: Session) -> list[Account]:
    """This tenant's users. Tenant-scoped by the ordinary read guard."""
    rows = session.scalars(select(User).order_by(User.email)).all()
    return [Account(id=u.id, email=u.email, role=UserRole(u.role)) for u in rows]


def _normalised_email(email: str) -> str:
    """Lower-cased and stripped, or an `AccountError` saying why not.

    Separate from `add_user` because `create_tenant` has to run it **before**
    it creates anything: the two writes are one transaction, and a tenant left
    behind by a rejected address would be exactly the unadministrable tenant
    `remove_user` refuses to produce.

    Lower-cased because `users.email` is unique per tenant and a login form is
    typed by hand: `Boss@acme.example` and `boss@acme.example` must not be two
    accounts, and the stored form has to be the one login looks up.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        raise AccountError(f"{email!r} is not an email address")
    return email


def add_user(session: Session, *, email: str, role: UserRole) -> AddedUser:
    """Create an account in the acting tenant and return its one-time password.

    The tenant comes from `current_tenant_id()` rather than from an argument,
    which is what makes "invite into another tenant" unexpressible rather than
    checked for -- the same shape the quota route uses.
    """
    email = _normalised_email(email)
    tenant_id = current_tenant_id()
    # Asked before inserting, so the refusal is this sentence rather than an
    # IntegrityError on `uq_users_tenant_id_email` surfacing as a 500. The
    # unique index is still the thing that makes it true under a race; this is
    # the thing that makes it readable.
    taken = session.scalars(select(User).where(User.email == email)).one_or_none()
    if taken is not None:
        raise AccountError(f"{email} already has an account in this tenant")

    password = secrets.token_urlsafe(_PASSWORD_BYTES)
    user = User(
        tenant_id=tenant_id,
        email=email,
        role=role,
        credential=hash_password(password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    # After the commit, like every other mutator here: `audit.record` commits
    # the session it is given, so a row written before the user existed would
    # be a trail entry for a thing that might still fail.
    audit.record(
        session,
        action=Action.USER_ADD,
        target=f"user:{user.id}",
        before=None,
        # Deliberately not the password, generated or otherwise: the audit log
        # is read by people who are not entitled to log in as this account.
        after={"email": user.email, "role": UserRole(user.role).value},
    )
    return AddedUser(user=user, password=password)


def remove_user(session: Session, user_id: int) -> None:
    """Remove an account from the acting tenant.

    **A tenant cannot be left with no admin.** Not a warning: a tenant whose
    last admin is gone can never be administered again from inside -- nobody
    can add a user, change a cap or approve a delivery, and no surface exists
    that could repair it. The only way back would be the SQL this ticket exists
    to remove.

    Removing *yourself* needs no special case and gets none: leaving is allowed
    while another admin remains, and the last-admin rule already refuses the
    one departure that matters. A rule about "me" would additionally be the
    wrong rule, since the dangerous act is identical whoever performs it.
    """
    # Tenant-filtered, so another tenant's id simply finds nothing. The message
    # is the same one a genuinely unknown id gets, for the reason
    # `control.service.NotAuthorized` gives: "no such user" and "not yours"
    # must not be distinguishable by someone trying ids.
    user = session.scalars(select(User).where(User.id == user_id)).one_or_none()
    if user is None:
        raise NoSuchUser(f"no such user {user_id}")

    if UserRole(user.role) is UserRole.ADMIN and _admin_count(session) == 1:
        raise AccountError(
            f"{user.email} is the last admin of this tenant and cannot be "
            f"removed; make another admin first, then remove this one"
        )

    before = {"email": user.email, "role": UserRole(user.role).value}
    removed_id = user.id
    session.delete(user)
    session.commit()
    audit.record(
        session,
        action=Action.USER_REMOVE,
        target=f"user:{removed_id}",
        before=before,
        after=None,
    )


def _admin_count(session: Session) -> int:
    """How many admins the acting tenant has. Tenant-filtered like every read."""
    return session.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
    )


def create_tenant(
    session: Session, *, name: str, slug: str, admin_email: str
) -> AddedUser:
    """Onboard a customer: a tenant and its first admin, in one call.

    **Not a route.** See docs/adr/0002. The short version: the person doing
    this belongs to no tenant, so there is no tenant-admin gate that fits, and
    the only ungated alternative would let anyone create tenants.

    One call rather than two, because a tenant with no admin is precisely the
    state `remove_user` refuses to create -- it would be unadministrable from
    the moment it existed. The two writes are one transaction for the same
    reason.

    The returned password is the first admin's, and the operator running this
    is expected to hand it over; it exists nowhere else.
    """
    slug = slug.strip().lower()
    name = name.strip()
    if not slug or not name:
        raise AccountError("a tenant needs both a name and a slug")
    # **Every validation before the first write.** The tenant and its admin are
    # one transaction, and the cheapest way to keep that true is to have
    # nothing left to reject once the tenant row exists -- a rejected address
    # after the commit would leave a tenant nobody can log into or administer,
    # which is the state `remove_user` exists to prevent.
    admin_email = _normalised_email(admin_email)
    # `Tenant` is not `TenantOwned`, so this read crosses no boundary that
    # needs one: there is no acting tenant here at all, by construction.
    taken = session.scalars(select(Tenant).where(Tenant.slug == slug)).one_or_none()
    if taken is not None:
        raise AccountError(
            f"the slug {slug!r} is already taken; it is what users type to log "
            f"in, so it has to be unique across customers"
        )

    tenant = Tenant(name=name, slug=slug)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    # The first admin is made by the ordinary path, inside the new tenant's
    # scope -- the same function the portal calls, so there is one way a user
    # is created and one place its audit row is written.
    with tenant_scope(tenant.id):
        return add_user(session, email=admin_email, role=UserRole.ADMIN)
