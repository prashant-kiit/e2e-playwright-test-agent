"""Unprotected auth endpoints: login / refresh / logout / me.

Login is per-user now (P5): tenant slug + email + password, checked against the
user's `credential` hash. There is no shared-password path and no
`QA_ADMIN_PASSWORD` -- the only way in is a `users` row. The tenant slug is part
of the body because `users.email` is unique only per tenant, so an address alone
no longer names an account.

Login sets *two* cookies and `/auth/refresh` is what trades the long-lived one
for a new short-lived one; see app/auth.py for why there are two.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import repo
from .auth import (
    REFRESH_COOKIE,
    CurrentUser,
    clear_session_cookies,
    read_refresh,
    require_auth,
    set_access_cookie,
    set_refresh_cookie,
    verify_password,
)
from .db import get_session
from .models import User
from .tenancy import tenant_scope

auth_router = APIRouter(prefix="/auth")


class LoginBody(BaseModel):
    tenant: str
    email: str
    password: str


def _as_current_user(user) -> CurrentUser:
    return CurrentUser(
        id=user.id, tenant_id=user.tenant_id, email=user.email, role=user.role
    )


@auth_router.post("/login")
def login(body: LoginBody, response: Response, session: Session = Depends(get_session)):
    """Log in as yourself, into a named tenant.

    `tenant` is the tenant's slug, and it is required: `users.email` is unique
    only per tenant, so an address on its own no longer names an account. The
    lookup is email *within* that tenant.

    An unknown tenant, an unknown email and a bad password are all the same
    bare 401, so a probe can map out neither which tenants exist nor which
    addresses are registered in one.
    """
    user = repo.get_user_for_login(session, body.tenant, body.email)
    if user is None or not verify_password(body.password, user.credential):
        return Response(status_code=401)
    current = _as_current_user(user)
    set_access_cookie(response, current)
    set_refresh_cookie(response, current)
    return {"ok": True, "email": current.email, "role": current.role.value}


@auth_router.post("/refresh")
def refresh(
    request: Request, response: Response, session: Session = Depends(get_session)
):
    """Trade a valid refresh cookie for a new access cookie.

    Unprotected on purpose: the caller's access cookie has just expired, which
    is the only reason to be here, so requiring a live session would make the
    endpoint useless. The refresh cookie *is* the credential.

    **It re-reads the `users` row, and that is the one place in the session
    design that does.** It did not, and UAT 3 (#54) found what that cost once
    P5-14 added a way to remove a user: an admin removed *themselves* through
    `DELETE /users/{id}`, refreshed with the cookie they already held, and used
    the new session to read `/users`, create another admin and change the
    tenant's quotas. `app/auth.py` justifies the stateless trade-off as "a role
    or tenant change takes effect at the user's next login", and for a
    downgrade that is a fair bargain -- the person still works here. A
    *removal* is the case it does not cover, because a removal is usually an
    offboarded contractor or a compromised account, and the honest description
    of the old behaviour was "they keep whatever role they had for up to 30
    days", the refresh cookie's cap, not fifteen minutes.

    So this reads the row and takes the claims from it. The cost is one
    database read per refresh -- once per access-cookie lifetime per user,
    not once per request -- which leaves intact the argument `app/auth.py`
    actually makes ("a cheap stateless check beats a database round-trip per
    request"): the *access* cookie is still claim-carrying and unchecked.

    Two things this buys beyond the removal: the role on the new cookie comes
    from the row, so a role change now takes effect at the next refresh rather
    than only at the next login; and the read is tenant-scoped, so a refresh
    cookie naming another tenant's user id finds nothing.

    **What it does not buy**: a removed user keeps their *existing* access
    cookie until it expires, up to 15 minutes. Closing that needs a check on
    every request, which is the round trip this design declined -- recorded as
    a follow-up rather than decided here.
    """
    token = request.cookies.get(REFRESH_COOKIE)
    claims = read_refresh(token) if token else None
    if claims is None:
        raise HTTPException(status_code=401, detail="authentication required")
    # Scoped, so the id in the cookie is only ever resolved inside the tenant
    # the cookie itself names: a forged or stale cross-tenant id finds nothing
    # rather than another tenant's user.
    with tenant_scope(claims.tenant_id):
        row = session.scalars(select(User).where(User.id == claims.id)).one_or_none()
    if row is None:
        # Same bare 401 as a missing or expired cookie: a caller probing with a
        # removed account's cookie must not be able to tell "removed" from
        # "expired", which is the distinction they would be probing for.
        raise HTTPException(status_code=401, detail="authentication required")
    current = _as_current_user(row)
    set_access_cookie(response, current)
    return {"ok": True, "email": current.email, "role": current.role.value}


@auth_router.post("/logout")
def logout(response: Response):
    clear_session_cookies(response)
    return {"ok": True}


@auth_router.get("/me")
def me(user: CurrentUser = Depends(require_auth)):
    return {
        "authenticated": True,
        "email": user.email,
        "role": user.role.value,
        "tenant_id": user.tenant_id,
    }
