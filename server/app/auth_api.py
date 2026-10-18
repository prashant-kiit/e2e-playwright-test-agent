"""Unprotected auth endpoints: login / logout / me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from .auth import COOKIE_NAME, MAX_AGE, check_password, mint_token, require_auth

auth_router = APIRouter(prefix="/auth")


class LoginBody(BaseModel):
    password: str


@auth_router.post("/login")
def login(body: LoginBody, response: Response):
    if not check_password(body.password):
        return Response(status_code=401)
    response.set_cookie(
        COOKIE_NAME, mint_token(), max_age=MAX_AGE, httponly=True, samesite="lax"
    )
    return {"ok": True}


@auth_router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@auth_router.get("/me", dependencies=[Depends(require_auth)])
def me():
    return {"authenticated": True}
