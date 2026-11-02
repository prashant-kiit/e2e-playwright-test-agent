"""Unprotected auth endpoints: login / logout / me.

Login is per-user now (P5): email + password, checked against the user's
`credential` hash. There is no shared-password path and no `QA_ADMIN_PASSWORD` --
the only way in is a `users` row.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import repo
from .auth import (
    COOKIE_NAME,
    MAX_AGE,
    CurrentUser,
    mint_token,
    require_auth,
    verify_password,
)
from .db import get_session

auth_router = APIRouter(prefix="/auth")


class LoginBody(BaseModel):
    email: str
    password: str


def _as_current_user(user) -> CurrentUser:
    return CurrentUser(
        id=user.id, tenant_id=user.tenant_id, email=user.email, role=user.role
    )


@auth_router.post("/login")
def login(body: LoginBody, response: Response, session: Session = Depends(get_session)):
    """Log in as yourself. A bad email and a bad password are the same 401, so a
    probe cannot tell a registered address from an unregistered one."""
    user = repo.get_user_by_email(session, body.email)
    if user is None or not verify_password(body.password, user.credential):
        return Response(status_code=401)
    current = _as_current_user(user)
    response.set_cookie(
        COOKIE_NAME, mint_token(current), max_age=MAX_AGE, httponly=True, samesite="lax"
    )
    return {"ok": True, "email": current.email, "role": current.role.value}


@auth_router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@auth_router.get("/me")
def me(user: CurrentUser = Depends(require_auth)):
    return {
        "authenticated": True,
        "email": user.email,
        "role": user.role.value,
        "tenant_id": user.tenant_id,
    }
