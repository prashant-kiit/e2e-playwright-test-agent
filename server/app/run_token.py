"""The run-scoped bearer token: a sandbox's entire authority.

Before P5-05 a sandbox held `DATABASE_URL` and the `S3_*` credentials, which is
to say it held the control plane's own authority over every tenant's data and was
trusted not to use it. The envelope made the sealed PATs it could read harmless
(P5-03), but "can read every row of `targets` and every blob in the bucket" was
still the honest description of a process running a model that executes
TypeScript against a web page an attacker may control.

This replaces that with a token that can say exactly three things:

    run_id      the run this sandbox is working on, and no other
    target_id   the one target whose tree it may read and commit to
    tenant_id   the one tenant whose blobs it may name

Everything the internal API will do for a sandbox is authorized against those
three fields (app/control/service.py), so the blast radius of a leaked token is
one run of one target of one tenant, for as long as that run is live.

**Signed and timestamped, not stored.** The same mechanism and the same library
as the portal's session cookies (app/auth.py): a stateless token costs no table
and no round trip, and the thing that bounds it is time. The cost is the one
app/auth.py already names -- a stateless token cannot be revoked before it
expires -- and the answer here is different from the portal's, because there *is*
a row that says whether this token's run is still going: the service checks the
run's status on every call, so a token for a finished, paused or stopped run is
refused however long its signature has left. Expiry is the backstop, liveness is
the gate, and that pairing is why this needs no token table.

**A distinct salt**, for the reason app/auth.py splits its two cookies: a token
minted here must not verify as a portal session, and a portal session must not
verify as a run token. Without that the sandbox's token would be interchangeable
with an operator's cookie, which would make every other rule here decorative.

**The key is the deployment's, never the sandbox's.** `QA_RUN_TOKEN_KEY` if a
deployment wants the run tokens signed with their own key, else the portal's
`QA_SECRET_KEY`. Either way it stays in the control plane: `QA_SECRET_KEY` is on
the forbidden list that tests/test_sandbox_credentials.py enforces, and a
sandbox that could sign its own tokens could mint one for any run of any tenant.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config

# Distinct from `_ACCESS_SALT` and `_REFRESH_SALT` in app/auth.py, so none of the
# three verifies where another belongs.
_SALT = "qa-run-token"

# How much longer than the run's own wall clock a token stays valid. A run is
# already failed by the reaper once it passes `QA_RUN_TIMEOUT_S` (app/reaper.py),
# so this margin only has to cover the work that happens *around* the last step
# -- the final ingest, the artifact sweep, the session archive and the cost row.
_GRACE_S = 15 * 60


@dataclass(frozen=True)
class RunScope:
    """What a run-scoped token authorizes, and the whole of it.

    Frozen because it is an authorization decision's input: a scope that could
    be edited after it was verified would make every check downstream a check of
    something else.
    """

    run_id: int
    target_id: int
    tenant_id: int


class RunTokenError(Exception):
    """The token does not authorize anything. The caller answers 401."""


def _secret() -> str:
    """`QA_RUN_TOKEN_KEY`, else the portal's own key. See
    `config.run_token_key`, which is now the one place that resolves it."""
    return config.run_token_key()


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(), salt=_SALT)


def ttl_s() -> float:
    """How long a minted token stays valid.

    Derived from the run wall clock rather than configured separately, because
    the two numbers have one correct relationship and a second hand-set value
    would eventually disagree with it. The failure that relationship exists to
    prevent is the expensive one: a token that expires mid-run fails a *healthy*
    run at a step boundary, after it has burned its tokens, and the reason would
    look like a store outage rather than a clock.
    """
    return config.run_timeout_s() + _GRACE_S


def mint(scope: RunScope) -> str:
    """A token carrying `scope`, signed and timestamped."""
    return _serializer().dumps(asdict(scope))


def read_unverified(token: str) -> RunScope:
    """The claims `token` carries, **without checking the signature**.

    For the sandbox, and only for the sandbox. It is handed a token and no key:
    `QA_SECRET_KEY` is on the forbidden list that
    tests/test_sandbox_credentials.py enforces, precisely because a sandbox that
    could verify a token could also *mint* one, for any run of any tenant. So a
    sandbox cannot check its own token, and must not be able to.

    It does need to read it. The run id addresses every request it makes
    (`/internal/runs/{run_id}/...`) and the tenant id is how it builds the blob
    keys it uploads -- neither is a decision, both are addressing. The control
    plane verifies the signature on every request and refuses a scope that does
    not match the row (app/control/service.py), so a sandbox that edited its own
    claims would be addressing requests it is then refused.

    **Nothing in the control plane may call this.** The name is deliberately
    ugly for the reason `repo.get_run_across_tenants` is: a reviewer should
    notice it, and the call site that is allowed to have it is the one that
    cannot do anything else.
    """
    _ok, claims = _serializer().loads_unsafe(token)
    if not isinstance(claims, dict) or set(claims) != {
        "run_id",
        "target_id",
        "tenant_id",
    }:
        raise RunTokenError("not a run token")
    return RunScope(**claims)


def verify(token: str, *, max_age_s: float | None = None) -> RunScope:
    """The scope `token` carries, or raise `RunTokenError`.

    This is the half that holds with no database: signature, payload and age.
    Whether the run is still *live* is a property of the run row, not of the
    token, so it is checked where that row is read (app/control/service.py).
    """
    age = ttl_s() if max_age_s is None else max_age_s
    try:
        claims = _serializer().loads(token, max_age=age)
    except (BadSignature, SignatureExpired) as exc:
        raise RunTokenError(str(exc)) from exc
    if not isinstance(claims, dict) or set(claims) != {
        "run_id",
        "target_id",
        "tenant_id",
    }:
        raise RunTokenError("not a run token")
    return RunScope(**claims)
