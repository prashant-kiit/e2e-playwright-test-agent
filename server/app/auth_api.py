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
def refresh(request: Request, response: Response):
    """Trade a valid refresh cookie for a new access cookie.

    Unprotected on purpose: the caller's access cookie has just expired, which
    is the only reason to be here, so requiring a live session would make the
    endpoint useless. The refresh cookie *is* the credential.

    It does not re-read the `users` row -- the refresh token carries the claims,
    same as the access token -- so this inherits the same trade-off as the rest
    of the session: a role or tenant change takes effect at next login, not at
    next refresh. It also does not re-issue the refresh cookie, so 30 days from
    login remains a hard cap (see app/auth.py).
    """
    token = request.cookies.get(REFRESH_COOKIE)
    user = read_refresh(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    set_access_cookie(response, user)
    return {"ok": True, "email": user.email, "role": user.role.value}


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
