"""The run-scoped bearer token: what it says, and what it refuses to say.

The token is the whole of a sandbox's authority after P5-05. It replaces
`DATABASE_URL` and the `S3_*` credentials, so the questions a test has to
answer about it are the ones an attacker would ask: can it be forged, can it be
edited, can it be replayed somewhere else, and does it stop working when the run
it was minted for is over.

Liveness is deliberately **not** tested here -- it is not a property of the
token but of the run row, so it lives with the service that reads that row
(tests/test_control_service.py). What is here is the part that holds with no
database at all.
"""

from __future__ import annotations

import pytest

from app import run_token
from app.domain.roles import UserRole
from app.run_token import RunScope


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    monkeypatch.setenv("QA_SECRET_KEY", "the-suite-signing-key")
    monkeypatch.delenv("QA_RUN_TOKEN_KEY", raising=False)


def test_a_minted_token_carries_back_the_run_the_target_and_the_tenant():
    """The three facts every authorization decision downstream is made on."""
    scope = RunScope(run_id=7, target_id=3, tenant_id=42)

    assert run_token.verify(run_token.mint(scope)) == scope


def test_a_token_signed_with_another_key_is_refused(monkeypatch):
    """The forgery case. A sandbox never holds the key, so a token it made up
    itself has to be worthless."""
    token = run_token.mint(RunScope(run_id=7, target_id=3, tenant_id=42))
    monkeypatch.setenv("QA_SECRET_KEY", "a-different-key")

    with pytest.raises(run_token.RunTokenError):
        run_token.verify(token)


def test_an_edited_token_is_refused():
    """The escalation case: the interesting edit is the tenant id, so the
    payload has to be signed rather than merely encoded."""
    token = run_token.mint(RunScope(run_id=7, target_id=3, tenant_id=42))

    with pytest.raises(run_token.RunTokenError):
        run_token.verify(token[:-4] + "AAAA")


def test_a_portal_session_cookie_does_not_verify_as_a_run_token(monkeypatch):
    """The reason app/auth.py's salts exist, extended to this third token.

    Interchangeable tokens would make every rule here decorative: an operator's
    cookie out of a log would be a run token, and a run token would be an
    operator's cookie.
    """
    from app import auth

    cookie = auth.mint_access(
        auth.CurrentUser(
            id=1, tenant_id=1, email="a@b.c", role=UserRole.ADMIN
        )
    )

    with pytest.raises(run_token.RunTokenError):
        run_token.verify(cookie)


def test_a_run_token_does_not_verify_as_a_portal_session(monkeypatch):
    """The same guarantee from the other side: a leaked run token must not be
    presentable to the portal as a logged-in operator."""
    from app import auth

    token = run_token.mint(RunScope(run_id=7, target_id=3, tenant_id=42))

    assert auth.read_access(token) is None


def test_a_token_older_than_its_lifetime_is_refused():
    """Expiry is the backstop under the liveness gate, so it has to work with
    no database in the picture at all."""
    token = run_token.mint(RunScope(run_id=7, target_id=3, tenant_id=42))

    with pytest.raises(run_token.RunTokenError):
        run_token.verify(token, max_age_s=-1)


def test_the_lifetime_outlasts_the_longest_a_run_may_take(monkeypatch):
    """A token that expired mid-run would fail a healthy run at a step
    boundary, which is the one failure mode worse than a token that lives too
    long. Derived from the run wall clock rather than a second hand-set number
    that can disagree with it."""
    monkeypatch.setenv("QA_RUN_TIMEOUT_S", "3600")

    assert run_token.ttl_s() > 3600


# --- what a sandbox can and cannot do with its own token -----------------
#
# The asymmetry that cost a container-path debugging session: a sandbox is
# handed a token and no key, so it can *read* its token and cannot *check* it.
# Getting this backwards fails only in a real container, because every
# in-process test has the signing key in its environment.

def test_a_sandbox_can_read_its_own_token_without_the_signing_key(monkeypatch):
    """The addressing use: the run id goes in every URL the sandbox calls, and
    the tenant id is how ingest builds its blob keys."""
    token = run_token.mint(RunScope(run_id=7, target_id=3, tenant_id=42))
    # Exactly a sandbox's environment: the key is not in it, by design.
    monkeypatch.delenv("QA_SECRET_KEY", raising=False)
    monkeypatch.delenv("QA_RUN_TOKEN_KEY", raising=False)

    assert run_token.read_unverified(token) == RunScope(
        run_id=7, target_id=3, tenant_id=42
    )


def test_verifying_a_token_without_the_key_fails_which_is_why_a_sandbox_reads(
    monkeypatch,
):
    """The other half, stated so the asymmetry is not rediscovered.

    A sandbox calling `verify` would raise on every real run -- it signs
    nothing, so it holds nothing to verify against. The control plane verifies;
    the sandbox reads.
    """
    token = run_token.mint(RunScope(run_id=7, target_id=3, tenant_id=42))
    monkeypatch.delenv("QA_SECRET_KEY", raising=False)
    monkeypatch.delenv("QA_RUN_TOKEN_KEY", raising=False)

    with pytest.raises(run_token.RunTokenError):
        run_token.verify(token)


def test_read_unverified_still_refuses_something_that_is_not_a_token():
    """Unverified is not unvalidated: a sandbox handed rubbish must fail at
    once, naming the reason, rather than on its first operation."""
    with pytest.raises(run_token.RunTokenError):
        run_token.read_unverified("not-a-token")


def test_only_the_sandbox_client_reads_a_token_unverified():
    """A structural guard, in the style of tests/test_sandbox_credentials.py.

    `read_unverified` is safe exactly once -- in the one process that cannot do
    anything else. Anywhere in the control plane it would be a signature check
    somebody forgot, and no behavioural test would notice.
    """
    from pathlib import Path

    import app

    app_dir = Path(app.__file__).parent
    offenders = sorted(
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*.py")
        if "read_unverified" in path.read_text()
    )

    assert offenders == ["control/http.py", "run_token.py"], offenders
