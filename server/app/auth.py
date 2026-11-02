"""Per-user auth.

P5 replaces the single shared password with real per-user login (DESIGN.md
§13). A user logs in with their email and password; the password is checked
against the `credential` hash on their `users` row; a signed, timestamped
cookie then carries *who they are* -- their user id, their tenant, and their
role -- for a week.

The session carries the claims rather than re-reading the row on every request:
this is a portal speed bump, not a revocation system, so a cheap stateless
check beats a database round-trip per request. The cost is that a role change
takes effect at the user's next login; acceptable for the actions it gates.

Two dependencies:

* `require_auth` resolves the current user from the cookie and -- because it is
  async -- sets `tenancy.current_tenant_id` for the rest of the request, so the
  sync endpoint and every repo call it makes insert and read as that tenant. A
  missing or bad cookie is a 401.
* `require_tenant_admin` is `require_auth` plus a role check: a non-admin acting
  on a tenant-admin surface (delivery approval, PAT rotation, quota/user
  changes) is a 403.

Passwords are hashed with PBKDF2-HMAC-SHA256 from the standard library -- no new
dependency, and strong enough for the handful of operator accounts this serves.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .domain.roles import UserRole
from .tenancy import set_current_tenant

COOKIE_NAME = "qa_session"
MAX_AGE = 7 * 24 * 3600  # a week

# PBKDF2 parameters. The iteration count is stored in the hash string, so it can
# be raised later without stranding existing credentials.
_PBKDF2_ITERATIONS = 240_000
_PBKDF2_ALGO = "pbkdf2_sha256"


@dataclass(frozen=True)
class CurrentUser:
    """The acting user, reconstructed from the session cookie's signed claims."""

    id: int
    tenant_id: int
    email: str
    role: UserRole


def _secret() -> str:
    return os.environ.get("QA_SECRET_KEY", "dev-secret-change-me")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt="qa-session")


# --- password hashing ----------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password for storage in `users.credential`.

    Format: ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`` -- self-
    describing, so `verify_password` needs no out-of-band parameters and the
    cost can be raised per-credential over time.
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, _PBKDF2_ITERATIONS
    )
    return f"{_PBKDF2_ALGO}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored hash, in constant time."""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != _PBKDF2_ALGO:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


# --- the session cookie --------------------------------------------------

def mint_token(user: CurrentUser) -> str:
    """Sign the acting user's claims into the session cookie's value."""
    return _serializer().dumps(
        {
            "uid": user.id,
            "tid": user.tenant_id,
            "email": user.email,
            "role": UserRole(user.role).value,
        }
    )


def read_token(token: str) -> CurrentUser | None:
    """The user a cookie names, or None if it is missing, forged or expired."""
    try:
        data = _serializer().loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    try:
        return CurrentUser(
            id=data["uid"],
            tenant_id=data["tid"],
            email=data["email"],
            role=UserRole(data["role"]),
        )
    except (KeyError, ValueError, TypeError):
        return None  # a token from an older claim shape is simply not a session


# --- the dependencies ----------------------------------------------------

async def require_auth(request: Request) -> CurrentUser:
    """Resolve the current user, and bind their tenant for the request.

    Async on purpose: a value a sync dependency sets does not reach the
    threadpooled endpoint, but one an async dependency sets does, so this is
    where `current_tenant_id()` is made to answer the acting user's tenant for
    the whole request. Tests override this dependency to bypass auth, which
    leaves the tenant unset and so the default -- exactly what a single-tenant
    test wants.
    """
    token = request.cookies.get(COOKIE_NAME)
    user = read_token(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    set_current_tenant(user.tenant_id)
    return user


async def require_tenant_admin(
    user: CurrentUser | None = Depends(require_auth),
) -> CurrentUser | None:
    """A tenant-admin action: `require_auth` plus a role check.

    It depends on `require_auth` rather than re-reading the cookie, so a route
    that requires admin also gets the tenant bound. When auth is bypassed (the
    API tests override `require_auth` to return None) there is no user to check
    and the gate is a no-op -- the same bypass those tests already rely on.
    """
    if user is not None and user.role is not UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="tenant-admin role required")
    return user


AuthDep = Depends(require_auth)
AdminDep = Depends(require_tenant_admin)
