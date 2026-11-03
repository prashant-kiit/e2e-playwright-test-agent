"""The per-tenant PAT surface: save, clear, and what the portal is told.

The credential logic is tested in test_delivery_credentials.py. Here the
concern is the HTTP contract, and it has three parts worth separating:

* **which failure is which status.** A token missing `workflow` is 422 -- the
  operator's input was refused and a different paste fixes it. A token GitHub
  stops accepting *at delivery* is 502. Conflating them would have told a
  customer with a scope typo that GitHub was down.
* **who may save one.** Rotating a credential is a tenant-admin action
  (DESIGN.md §13), like approving a delivery.
* **what the portal can see.** The expiry warning has to reach the browser
  without a KMS call or a GitHub call, and the plaintext must never reach it
  at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import envelope
from app.api import (
    get_catalog,
    get_delivery_tools,
    get_key_wrapper,
    get_launcher,
    get_resolver,
    get_storage,
    get_token_validator,
)
from app.auth import require_auth, require_tenant_admin
from app.db import get_session
from app.delivery.errors import CredentialError
from app.delivery.github import TokenInfo
from app.main import app
from tests.storage_helpers import FakeStorage
from tests.target_helpers import public_resolver, target_body

PAT = "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
WRAPPER = envelope.LocalKeyWrapper(b"the-route-suite-wrapping-key")


def token_info(*, scopes=("repo", "workflow"), expires_at=None, login="octocat"):
    return TokenInfo(login=login, scopes=frozenset(scopes), expires_at=expires_at)


@pytest.fixture()
def validator():
    """The injected save-time GitHub call. A test sets `.info` or `.raises`."""

    class Validator:
        info = token_info()
        raises: Exception | None = None
        seen: list[str] = []

        def __call__(self, token: str) -> TokenInfo:
            self.seen.append(token)
            if self.raises is not None:
                raise self.raises
            return self.info

    v = Validator()
    v.seen = []
    return v


@pytest.fixture()
def client(session, validator):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_launcher] = lambda: (lambda run_id: None)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_tenant_admin] = lambda: None
    app.dependency_overrides[get_resolver] = lambda: public_resolver
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_token_validator] = lambda: validator
    app.dependency_overrides[get_key_wrapper] = lambda: WRAPPER
    yield TestClient(app)
    app.dependency_overrides.clear()


def make_target(client, app_name="practice-target"):
    project = client.post("/projects", json={"name": "demo"}).json()
    created = client.post(
        f"/projects/{project['id']}/targets", json=target_body(app=app_name, name="T")
    ).json()
    return created["target"]["id"]


# --- GET /targets/{id}/credential ----------------------------------------

def test_a_target_starts_with_no_credential_and_the_portal_is_told_why(client):
    tid = make_target(client)

    body = client.get(f"/targets/{tid}/credential").json()

    assert body["state"] == "absent"
    assert body["expires_at"] is None
    assert "no github credential" in body["warning"].lower()


def test_the_credential_route_never_returns_the_token_or_the_ciphertext(client):
    """The portal has no business holding either, and a response body ends up
    in a browser's network log."""
    tid = make_target(client)
    client.put(f"/targets/{tid}/pat", json={"token": PAT})

    raw = client.get(f"/targets/{tid}/credential").text

    assert PAT not in raw
    assert envelope.SEAL_PREFIX not in raw
    assert "ciphertext" not in raw


# --- PUT /targets/{id}/pat -----------------------------------------------

def test_saving_a_valid_pat_reports_the_account_it_authors_as(client, validator):
    """So a customer can see *whose* token they pasted before a delivery pushes
    a commit under that name."""
    validator.info = token_info(login="acme-ci")
    tid = make_target(client)

    body = client.put(f"/targets/{tid}/pat", json={"token": PAT}).json()

    assert body["state"] == "valid"
    assert body["login"] == "acme-ci"
    assert validator.seen == [PAT]


def test_a_saved_pat_is_what_delivery_would_decrypt(client, session):
    """End to end through the route: the row the API wrote is one the delivery
    seam can open, which is the only thing that makes the save worth doing.

    `DbCredentials` takes a session *factory*, so the test's single session is
    handed over as one -- `nullcontext` because the fixture owns its lifetime
    and the seam must not close it.
    """
    from contextlib import nullcontext

    from app.delivery.credentials import DbCredentials

    tid = make_target(client)
    client.put(f"/targets/{tid}/pat", json={"token": PAT})

    seam = DbCredentials(lambda: nullcontext(session), WRAPPER)

    assert seam.token_for("practice-target") == PAT


def test_the_expiry_github_reports_reaches_the_portal(client, validator):
    validator.info = token_info(expires_at=datetime.now(UTC) + timedelta(days=5))
    tid = make_target(client)

    body = client.put(f"/targets/{tid}/pat", json={"token": PAT}).json()

    assert body["expiring_soon"] is True
    assert body["days_until_expiry"] == 5
    assert "5 days" in body["warning"]


def test_a_token_missing_a_scope_is_422_and_says_which(client, validator):
    validator.info = token_info(scopes=("repo",))
    tid = make_target(client)

    resp = client.put(f"/targets/{tid}/pat", json={"token": PAT})

    assert resp.status_code == 422
    assert "workflow" in resp.json()["detail"]


def test_a_token_github_rejects_is_422_not_502(client, validator):
    """At save time a refused token is the operator's paste, not an outage."""
    validator.raises = CredentialError("GitHub rejected the token (401) for GET /user")
    tid = make_target(client)

    resp = client.put(f"/targets/{tid}/pat", json={"token": PAT})

    assert resp.status_code == 422


def test_an_empty_token_is_refused(client):
    tid = make_target(client)

    assert client.put(f"/targets/{tid}/pat", json={"token": "  "}).status_code == 422


def test_a_rejected_save_leaves_the_working_credential_in_place(client, validator):
    """A failed rotation must not cost a customer the credential they had."""
    tid = make_target(client)
    client.put(f"/targets/{tid}/pat", json={"token": PAT})

    validator.raises = CredentialError("GitHub rejected the token (401) for GET /user")
    client.put(f"/targets/{tid}/pat", json={"token": "ghp_" + "z" * 36})

    assert client.get(f"/targets/{tid}/credential").json()["state"] == "valid"


def test_saving_a_pat_for_a_target_that_does_not_exist_is_404(client):
    assert client.put("/targets/9999/pat", json={"token": PAT}).status_code == 404


# --- DELETE /targets/{id}/pat --------------------------------------------

def test_clearing_a_pat_returns_the_target_to_absent(client):
    tid = make_target(client)
    client.put(f"/targets/{tid}/pat", json={"token": PAT})

    assert client.delete(f"/targets/{tid}/pat").status_code == 200
    assert client.get(f"/targets/{tid}/credential").json()["state"] == "absent"


# --- the role gate -------------------------------------------------------

def test_a_non_admin_may_not_save_or_clear_a_pat(client):
    """Rotating a credential sits with approving a delivery: both write into a
    customer's repository, one directly and one by authorising it."""
    from fastapi import HTTPException

    tid = make_target(client)

    def refuse():
        raise HTTPException(status_code=403, detail="tenant-admin role required")

    app.dependency_overrides[require_tenant_admin] = refuse

    assert client.put(f"/targets/{tid}/pat", json={"token": PAT}).status_code == 403
    assert client.delete(f"/targets/{tid}/pat").status_code == 403
    # Reading the state is not an admin action: a member has to be able to see
    # why delivery is refused.
    assert client.get(f"/targets/{tid}/credential").status_code == 200


# --- the delivery state carries the credential, for one fetch ------------

def test_the_delivery_state_carries_the_credential_warning(client):
    """The portal already fetches this per target for the delivery badge, so
    the warning rides along rather than costing a second round trip."""
    from app.delivery.catalog import DeliveryState
    from app.target_config import TargetConfig

    class StubCatalog:
        def config(self, app):
            return TargetConfig(
                app=app,
                name="T",
                base_url="https://t.example.com",
                locators="",
                agent_notes=(),
                target_repo="o/r",
                target_branch="master",
            )

        def state(self, app):
            return DeliveryState(
                rev=1,
                tree_hash="f" * 64,
                delivered_sha=None,
                revisions_ahead=1,
                ever_delivered=False,
            )

    tid = make_target(client)
    app.dependency_overrides[get_catalog] = lambda: StubCatalog()
    app.dependency_overrides[get_delivery_tools] = lambda: None

    body = client.get(f"/targets/{tid}/delivery").json()

    assert body["credential_state"] == "absent"
    assert "no github credential" in body["credential_warning"].lower()
    assert body["pat_expires_at"] is None


# --- a 401 at delivery: the fail-loud rule, end to end -------------------

def test_github_rejecting_the_token_at_delivery_marks_it_invalid_and_is_502(
    client, session
):
    """DESIGN.md §8's fail-loud rule, through the real route and the real seam.

    Everything between the route and the column is genuine here -- the delivery
    `Tools`, `for_target`, `DbCredentials`, the row -- because the thing worth
    proving is that the mark actually lands. A unit test of `for_target` shows
    the context manager calls `mark_invalid`; only this shows the column
    changing as a result of an HTTP request.

    **502, not 422**: at delivery a refused token is GitHub refusing *us*, and
    the remedy is to save a new one, which is what the state now says.
    """
    from contextlib import nullcontext

    from app.delivery.credentials import DbCredentials
    from app.delivery.errors import CredentialError
    from app.delivery.git import Git
    from app.delivery.tools import UNBOUND_GITHUB, Tools

    tid = make_target(client)
    client.put(f"/targets/{tid}/pat", json={"token": PAT})

    class RefusingGitHub:
        """A client whose every call is GitHub answering 401, as the real one
        raises it (`GitHubClient._raise_for_credentials`)."""

        def __getattr__(self, name):
            def refuse(*args, **kwargs):
                raise CredentialError(f"GitHub rejected the token (401) for {name}")

            return refuse

    tools = Tools(
        gh=UNBOUND_GITHUB,
        git=Git(),
        token="",
        catalog=_catalog_for("practice-target", bootstrapped=False),
        credentials=DbCredentials(lambda: nullcontext(session), WRAPPER),
        gh_factory=lambda token: RefusingGitHub(),
    )
    app.dependency_overrides[get_delivery_tools] = lambda: tools

    # The first delivery to this repo, so `ensure_bootstrapped` asks GitHub
    # whether it has commits -- the earliest authenticated call a delivery
    # makes, and the realistic place a bad token is discovered.
    resp = client.post(f"/targets/{tid}/deliver", json={"story_id": "SCRUM-1"})

    assert resp.status_code == 502
    assert "401" in resp.json()["detail"]
    after = client.get(f"/targets/{tid}/credential").json()
    assert after["state"] == "invalid"
    assert "rejected" in after["warning"].lower()


def test_a_delivery_with_no_credential_saved_is_refused_before_any_push(
    client, session
):
    """The normal state of a new target, and it must not read as a server fault."""
    from contextlib import nullcontext

    from app.delivery.credentials import DbCredentials
    from app.delivery.git import Git
    from app.delivery.tools import UNBOUND_GITHUB, Tools

    tid = make_target(client)

    app.dependency_overrides[get_delivery_tools] = lambda: Tools(
        gh=UNBOUND_GITHUB,
        git=Git(),
        token="",
        catalog=_catalog_for("practice-target"),
        credentials=DbCredentials(lambda: nullcontext(session), WRAPPER),
    )

    resp = client.post(f"/targets/{tid}/deliver", json={"story_id": "SCRUM-1"})

    assert resp.status_code == 502
    assert "no GitHub credential stored" in resp.json()["detail"]
    # Still absent, not invalid: nothing was rejected, there was nothing to
    # reject. Marking it invalid here would tell the customer their token was
    # refused when they never saved one.
    assert client.get(f"/targets/{tid}/credential").json()["state"] == "absent"


def _catalog_for(app_name: str, *, bootstrapped: bool = True):
    """A catalog that answers `config` and `state` and nothing else -- the
    delivery route reads both before it reaches for a credential."""
    from app.delivery.catalog import DeliveryState
    from app.target_config import TargetConfig

    class Catalog:
        def config(self, app):
            return TargetConfig(
                app=app_name,
                name="T",
                base_url="https://t.example.com",
                locators="",
                agent_notes=(),
                target_repo="o/r",
                target_branch="master",
            )

        def state(self, app):
            return DeliveryState(
                rev=1,
                tree_hash="f" * 64,
                delivered_sha="a" * 40 if bootstrapped else None,
                revisions_ahead=0 if bootstrapped else 1,
                ever_delivered=bootstrapped,
            )

    return Catalog()
