"""One way for a test to get a run's gateway, shared by the whole suite.

P5-05 replaced the pair `(session_factory, store)` that the launcher, the
driver, hydrate and the collector all used to take with a single run-scoped
gateway (app/control/gateway.py). Most tests do not care which transport that
is -- only that it is a real one, carrying a real token, against the fixtures'
database and the fixtures' fake store.

So they take it from here, for the reason tests/target_helpers.py and
tests/storage_helpers.py exist: the alternative is the same four lines of
minting and wiring in a dozen files, which is a dozen places to forget the
token.

`LocalGateway` rather than `HttpGateway`, because these tests are about the
pipeline rather than about the transport. The transport is covered on its own:
tests/test_control_gateway.py runs one suite against both, and
tests/test_internal_api.py drives the routes directly.
"""

from __future__ import annotations

from app.control import factory, service
from app.control.local import LocalGateway
from app.storage import Storage

# The suite's run-token signing key. Set explicitly so a token minted in one
# test is not verifiable with whatever `QA_SECRET_KEY` a neighbouring test left
# behind -- and so the default `dev-secret-change-me` is never what the suite is
# actually exercising.
SIGNING_KEY = "the-suite-signing-key"


def BorrowedSessionFactory(session):
    """A session *factory* that always lends one session it does not own.

    For tests built on the `session` fixture rather than `session_factory`.
    `LocalGateway` opens a short session per operation, as the driver always
    did, and closing a session the test still holds would be wrong -- but so
    would taking a *second* connection, and that is the subtler problem: **a
    test using both fixtures gets two teardowns, and the second one's
    `TRUNCATE` waits for ever on the first one's still-open transaction.** That
    presents as a hang with no failure, which is why it is worth a named helper
    rather than a comment. One session per test, one teardown.

    `service.BorrowedSession` is the shape, reused rather than copied: it exists
    in the app for the same reason (`PostgresLogBus` wants a factory and the
    request already owns a session) and one `__exit__` that declines to close is
    enough for both.
    """
    return lambda: service.BorrowedSession(session)


def control_for(
    run_id: int, session_factory, store: Storage, monkeypatch=None
) -> LocalGateway:
    """A gateway scoped to `run_id`, against these fixtures.

    Minting reads the run with the tenant filter on, so this works for a run of
    the acting tenant -- which in the fixtures is the seeded default one. A test
    about a *second* tenant mints inside that tenant's `tenant_scope`, the way
    the production call sites do on a request thread.
    """
    if monkeypatch is not None:
        monkeypatch.setenv("QA_SECRET_KEY", SIGNING_KEY)
    return factory.local_for_run(
        run_id, session_factory=session_factory, store=store
    )


def control_for_session(
    run_id: int, session, store: Storage, monkeypatch=None
) -> LocalGateway:
    """`control_for`, for a test built on the `session` fixture.

    Two named functions rather than one with an optional argument, because the
    choice is not a detail: see `BorrowedSessionFactory` for what taking the
    wrong one does.
    """
    return control_for(run_id, BorrowedSessionFactory(session), store, monkeypatch)
