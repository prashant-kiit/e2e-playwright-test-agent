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

**There are two cookies, not one.** A single week-long session cookie meant a
copy of it -- out of a log, a proxy, a backup, a borrowed laptop -- was good for
a week. So the session is split:

* an **access** cookie carrying the claims, good for `ACCESS_MAX_AGE`
  (15 minutes). This is the one every request presents and the only one
  `require_auth` will look at. A stolen copy is worth a quarter of an hour.
* a **refresh** cookie, good for `REFRESH_MAX_AGE` (30 days), which trades
  itself for a new access cookie at `POST /auth/refresh`. It is scoped to
  `REFRESH_PATH` -- the `/auth` prefix, so the browser attaches it to the handful
  of auth routes and to none of the API, which is where it would otherwise be
  sitting in every request log. `/auth/refresh` is the only route that *reads*
  it; `/auth/logout` is under the same prefix so the delete can reach it.

Both are stateless signed tokens; **there is no server-side token store, so
neither can be revoked before it expires.** That is a deliberate continuation of
the "speed bump, not a revocation system" line above, and it is what bounds the
blast radius choice: the access cookie is short *because* nothing can cut it
short. Logout clears both cookies, which ends the session on that browser but
would not stop a copy already taken. Revocation, if it is ever wanted, means a
token table, and the place to put it is here.

The refresh cookie's lifetime is a hard cap, not a sliding window: refreshing
does not re-issue it, so a session ends 30 days after *login* however active the
user has been. A sliding window with no revocation would be a session that never
ends.

The two are signed with **different salts**, so neither token is accepted where
the other belongs. Without that the split would be decorative -- presenting the
30-day refresh token as an access cookie would simply restore the old
week-long-cookie behaviour, worse.

Two dependencies:

* `require_auth` resolves the current user from the access cookie and --
  because it is async -- sets `tenancy.current_tenant_id` **and
  `tenancy.current_actor`** for the rest of the request, so the sync endpoint and
  every repo call it makes insert and read as that tenant, and every audit row
  names that user. A missing, bad or **expired** cookie is a 401.
* `require_tenant_admin` is `require_auth` plus a role check: a non-admin acting
  on a tenant-admin surface (delivery approval, PAT rotation, quota/user
  changes) is a 403.

Passwords are hashed with PBKDF2-HMAC-SHA256 from the standard library -- no new
dependency, and strong enough for the handful of operator accounts this serves.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config
from .domain.roles import UserRole
from .tenancy import set_current_actor, set_current_tenant

# The access cookie keeps the original name: it is still "the session cookie"
# from the browser's point of view, just a short-lived one now.
ACCESS_COOKIE = "qa_session"
REFRESH_COOKIE = "qa_refresh"

ACCESS_MAX_AGE = 15 * 60  # fifteen minutes
REFRESH_MAX_AGE = 30 * 24 * 3600  # thirty days

# Scoping the refresh cookie to the /auth prefix (rather than "/") keeps the
# browser from attaching the long-lived credential to every API call, so it is
# not sitting in the request log of every route that has no business seeing it.
# The browser does send it to the other /auth routes; only /auth/refresh reads
# it, and /auth/logout being under the same prefix is what lets the delete match.
REFRESH_PATH = "/auth"

# Distinct salts: a token minted for one slot does not verify in the other, so
# the long-lived refresh token cannot be replayed as a 30-day session cookie.
_ACCESS_SALT = "qa-session"
_REFRESH_SALT = "qa-refresh"

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
    """The signing key, from `config` -- which is the one place that knows what
    it and its development fallback are. See `config.secret_key`."""
    return config.secret_key()


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt=salt)


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

def _claims(user: CurrentUser) -> dict:
    return {
        "uid": user.id,
        "tid": user.tenant_id,
        "email": user.email,
        "role": UserRole(user.role).value,
    }


def _read(token: str, salt: str, max_age: int) -> CurrentUser | None:
    """The user a token names, or None if it is missing, forged, expired, or was
    minted for the *other* slot (which the salt mismatch turns into a
    BadSignature, indistinguishable from a forgery -- as it should be)."""
    try:
        data = _serializer(salt).loads(token, max_age=max_age)
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


def mint_access(user: CurrentUser) -> str:
    """Sign the acting user's claims into a short-lived access token."""
    return _serializer(_ACCESS_SALT).dumps(_claims(user))


def mint_refresh(user: CurrentUser) -> str:
    """Sign the same claims into a long-lived refresh token.

    It carries the claims rather than an opaque handle for the same reason the
    access token does: there is no token table to look a handle up in, so
    `/auth/refresh` reconstitutes the session from the token itself.
    """
    return _serializer(_REFRESH_SALT).dumps(_claims(user))


def read_access(token: str) -> CurrentUser | None:
    """The user an access token names. Reads `ACCESS_MAX_AGE` at call time, so
    the window is one module attribute rather than something baked into a
    default argument."""
    return _read(token, _ACCESS_SALT, ACCESS_MAX_AGE)


def read_refresh(token: str) -> CurrentUser | None:
    """The user a refresh token names, within `REFRESH_MAX_AGE` of login."""
    return _read(token, _REFRESH_SALT, REFRESH_MAX_AGE)


# --- the cookie contract -------------------------------------------------
#
# Names, lifetimes, flags and the refresh cookie's path live here and nowhere
# else: a route that set one of these itself could get the path wrong and leave
# a logout that does not log out, or re-issue the refresh cookie and turn the
# hard cap into a sliding window by accident.
#
# **`Secure` outside development**, from `config.cookies_secure()`. Both
# cookies carry it, including the renewed access cookie -- a flag set at login
# but not at refresh would protect only the first fifteen minutes.
#
# The two deletes carry it as well, for a smaller reason than an earlier
# version of this comment claimed. A browser keys cookie *identity* on name,
# domain and path only, so a delete matches regardless of this flag -- unlike
# the refresh cookie's `Path`, which really must match and is why
# `clear_session_cookies` repeats it. `Secure` is on the deletes so the
# expiring `Set-Cookie` itself does not travel in clear, and so the contract
# is one rule rather than a rule with an exception somebody has to remember.
# It is conditional rather than unconditional because a development stack
# reached over a LAN address or a tunnel has no TLS, and there a `Secure`
# cookie is a login that silently never persists; `http://localhost` would
# have been fine either way, since browsers treat it as a secure context.
# `samesite="lax"` is not a substitute: it bounds which *sites* may cause the
# cookie to be sent, not which *protocol* carries it.

def set_access_cookie(response: Response, user: CurrentUser) -> None:
    """Issue a fresh access cookie. Login and refresh both end here."""
    response.set_cookie(
        ACCESS_COOKIE,
        mint_access(user),
        max_age=ACCESS_MAX_AGE,
        httponly=True,
        secure=config.cookies_secure(),
        samesite="lax",
        path="/",
    )


def set_refresh_cookie(response: Response, user: CurrentUser) -> None:
    """Issue the refresh cookie. **Only login calls this.**

    `/auth/refresh` deliberately does not: re-issuing here on every refresh
    would make the 30 days a sliding window, and a sliding window on a token
    nothing can revoke is a session that never ends.
    """
    response.set_cookie(
        REFRESH_COOKIE,
        mint_refresh(user),
        max_age=REFRESH_MAX_AGE,
        httponly=True,
        secure=config.cookies_secure(),
        samesite="lax",
        path=REFRESH_PATH,
    )


def clear_session_cookies(response: Response) -> None:
    """End the session on this browser: expire both cookies.

    The refresh cookie must be deleted at the path it was set on -- a delete at
    "/" does not match a cookie scoped to "/auth", and the leftover would let
    the next `/auth/refresh` mint a new session out of a logged-out browser.
    """
    secure = config.cookies_secure()
    response.delete_cookie(ACCESS_COOKIE, path="/", secure=secure)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, secure=secure)


# --- the dependencies ----------------------------------------------------

async def require_auth(request: Request) -> CurrentUser:
    """Resolve the current user, and bind their tenant for the request.

    Async on purpose: a value a sync dependency sets does not reach the
    threadpooled endpoint, but one an async dependency sets does, so this is
    where `current_tenant_id()` is made to answer the acting user's tenant for
    the whole request.

    **A route that loses this dependency now fails rather than serving the
    first tenant** (P5-11). It used to leave the tenant unset, and the resolver
    answered the seeded default -- so the mistake was invisible, and a test that
    overrode this dependency to bypass auth relied on that fallback. The
    resolver raises instead, the suite binds its tenant in an autouse fixture
    (tests/conftest.py), and the failure is asserted at the boundary in
    tests/test_tenant_isolation.py.
    """
    token = request.cookies.get(ACCESS_COOKIE)
    user = read_access(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    set_current_tenant(user.tenant_id)
    # The acting user, for the audit log (P5-07), bound in the same breath as
    # the tenant and for the same reason: a route that had to remember to pass
    # the actor is a route that can forget, and an audit row attributing a
    # customer's delivery to "system" is worse than no row -- it is a wrong
    # answer to the question the table exists to answer. There is no route that
    # could forget, because none of them does it.
    set_current_actor(user.email)
    return user


async def require_tenant_admin(
    user: CurrentUser = Depends(require_auth),
) -> CurrentUser:
    """A tenant-admin action: `require_auth` plus a role check.

    It depends on `require_auth` rather than re-reading the cookie, so a route
    that requires admin also gets the tenant bound.

    **It refuses anything that is not demonstrably an admin.** An earlier
    version let a `None` user through so that a test overriding `require_auth`
    to a no-op kept working; that put the safety of an authorization gate in
    the hands of a test convention, and a gate whose production behaviour
    depends on how tests are written is not a gate. A test that needs past this
    one overrides *it*, explicitly, the way the suite already overrides every
    other dependency it wants out of the way.
    """
    if not isinstance(user, CurrentUser) or user.role is not UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="tenant-admin role required")
    return user


AuthDep = Depends(require_auth)
AdminDep = Depends(require_tenant_admin)
