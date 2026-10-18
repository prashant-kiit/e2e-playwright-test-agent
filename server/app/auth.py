"""Single-operator login.

This is a speed bump, not multi-tenant security (audience: just me). One shared
password (QA_ADMIN_PASSWORD) mints a signed, timestamped session cookie; a
dependency verifies it on protected routes. No user table.
"""

from __future__ import annotations

import os

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "qa_session"
MAX_AGE = 7 * 24 * 3600  # a week


def _secret() -> str:
    return os.environ.get("QA_SECRET_KEY", "dev-secret-change-me")


def _password() -> str:
    return os.environ.get("QA_ADMIN_PASSWORD", "admin")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="qa-session")


def check_password(password: str) -> bool:
    return password == _password()


def mint_token() -> str:
    return _serializer().dumps({"sub": "admin"})


def verify_token(token: str) -> bool:
    try:
        _serializer().loads(token, max_age=MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def require_auth(request: Request) -> None:
    """Dependency on protected routes. Overridden to a no-op in tests."""
    token = request.cookies.get(COOKIE_NAME)
    if not token or not verify_token(token):
        raise HTTPException(status_code=401, detail="authentication required")


AuthDep = Depends(require_auth)
