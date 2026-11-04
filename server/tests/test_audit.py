"""The audit log: who authorized a control-plane mutation, and when (P5-07, #37).

The spec's testing decision for this ticket is one sentence -- "each control-
plane mutation writes exactly one immutable row naming the actor" -- and this
file is organised around its three claims:

* **one row, naming the actor.** Asserted per mutation, through the real
  surface (an HTTP route where there is one, the repo function where there is
  not), because the actor is resolved from the request and a test that called
  `audit.record` directly would prove only that the recorder works.
* **immutable.** Asserted against the database, not the module: the guarantee
  is a trigger, so an UPDATE and a DELETE must both raise even though no
  application code issues either.
* **tenant-scoped on read.** Inherited from `TenantOwned`, so the test is the
  one the spec asks for rather than a new mechanism.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import audit, envelope
from app.domain.audit import Action
from app.tenancy import DEFAULT_TENANT_ID, actor_scope, current_tenant_id, set_current_actor


def test_record_appends_one_row_naming_the_actor(session):
    """The write seam, at its simplest: an action, a target, and who did it."""
    with actor_scope("admin@example.com"):
        audit.record(
            session,
            action=Action.TARGET_RESET,
            target="target:saucedemo",
        )

    (row,) = audit.entries(session)
    assert row.actor == "admin@example.com"
    assert row.action is Action.TARGET_RESET
    assert row.target == "target:saucedemo"
    assert row.tenant_id == current_tenant_id() == DEFAULT_TENANT_ID
    assert row.at is not None


# --- append-only, enforced by the database -------------------------------
#
# Asserted with raw SQL on purpose. `app/audit.py` exposes no update and no
# delete, so a test driven through the module could only ever assert that an
# absent function is absent. The claim #30's story 28 makes is stronger than
# that -- the trail "cannot be quietly altered" -- and the only way to show it
# is to try the thing application code never does.

def test_an_audit_row_cannot_be_updated(session):
    with actor_scope("admin@example.com"):
        row = audit.record(
            session, action=Action.PAT_SAVE, target="target:saucedemo"
        )

    with pytest.raises(DBAPIError) as caught:
        session.execute(
            text("UPDATE audit_log SET actor = 'someone-else' WHERE id = :id"),
            {"id": row.id},
        )
    assert "append-only" in str(caught.value)
    session.rollback()

    # and the row is untouched
    (unchanged,) = audit.entries(session)
    assert unchanged.actor == "admin@example.com"


def test_an_audit_row_cannot_be_deleted(session):
    with actor_scope("admin@example.com"):
        row = audit.record(
            session, action=Action.PAT_SAVE, target="target:saucedemo"
        )

    with pytest.raises(DBAPIError) as caught:
        session.execute(
            text("DELETE FROM audit_log WHERE id = :id"), {"id": row.id}
        )
    assert "append-only" in str(caught.value)
    session.rollback()

    assert len(audit.entries(session)) == 1


def test_the_audit_module_offers_no_way_to_change_a_row():
    """The database refuses it; this asserts nothing in the tree *tries*.

    The trigger makes an attempted rewrite fail, which is the guarantee. This
    is the companion claim: there is no function here whose job is to alter the
    trail, so a caller cannot reach for one and discover the refusal at
    runtime. A deliberate exception, when tenant purge needs one, is a line in
    that purge rather than a mutator here -- see `app/audit.py`.
    """
    assert not [
        name
        for name in dir(audit)
        if not name.startswith("_")
        and any(verb in name for verb in ("update", "delete", "purge", "edit"))
    ]


# --- the mutations, through the real surface ------------------------------
#
# Every test below drives an HTTP route (or, for the quota change, the repo
# function that is the only way to perform it) and then asserts the trail. The
# actor is bound the way production binds it -- by the auth dependency -- so
# these also cover the wiring that puts the acting user there, which is the
# half most likely to be wrong.

ADMIN = "admin@example.com"

# A wrapping key for the sealed PAT, as `test_api_credentials.py` builds one:
# the suite must work with no cloud account, and conftest refuses a real KMS
# client outright.
_WRAPPER = envelope.LocalKeyWrapper(b"the-audit-suite-wrapping-key")


@pytest.fixture()
def client(session):
    """A client authenticated as `ADMIN`, with delivery and storage stubbed.

    `require_auth` is overridden rather than bypassed with `lambda: None` (the
    rest of the suite's shape), because what it *does* -- bind the tenant and
    the actor -- is exactly what these tests are checking the routes rely on. A
    no-op override would leave every row saying `system` and the file would
    prove nothing about attribution.
    """
    from fastapi.testclient import TestClient

    from app.api import (
        get_bootstrap_runner,
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
    from app.main import app
    from app.tenancy import set_current_tenant
    from tests.storage_helpers import FakeStorage
    from tests.target_helpers import public_resolver

    async def authenticated():
        # Precisely what the real dependency does, which is the point.
        set_current_tenant(DEFAULT_TENANT_ID)
        set_current_actor(ADMIN)
        return None

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_launcher] = lambda: (lambda run_id: None)
    app.dependency_overrides[require_auth] = authenticated
    app.dependency_overrides[require_tenant_admin] = authenticated
    app.dependency_overrides[get_resolver] = lambda: public_resolver
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_delivery_tools] = lambda: None
    app.dependency_overrides[get_catalog] = lambda: None
    app.dependency_overrides[get_key_wrapper] = lambda: _WRAPPER
    app.dependency_overrides[get_token_validator] = lambda: _accept_token
    # The infra sync really pushes to a git remote, so it is stubbed to a
    # successful outcome: what is under test is that the route records it, not
    # what bootstrap does (tests/test_delivery_bootstrap.py owns that).
    app.dependency_overrides[get_bootstrap_runner] = lambda: _bootstrap_ok
    yield TestClient(app)
    app.dependency_overrides.clear()


def _bootstrap_ok(app_name: str):
    from app.apphub import BootstrapOutcome

    return BootstrapOutcome(ok=True, output="synced 4 files")


def _accept_token(token: str):
    """A token validator that accepts anything with the delivery scopes."""
    from app.delivery.credentials import TokenInfo

    return TokenInfo(login="octocat", scopes=("repo", "workflow"), expires_at=None)


def _make_target(client, app_name="saucedemo", **kw):
    from tests.target_helpers import target_body

    project = client.post("/projects", json={"name": "demo"}).json()
    created = client.post(
        f"/projects/{project['id']}/targets",
        json=target_body(app=app_name, name="T", **kw),
    ).json()
    return created["target"]["id"]


def test_delivery_approval_records_the_approving_user_and_time(client, monkeypatch, session):
    """#30's story 26, which is the reason this table exists.

    "Who authorized writing this commit into our repo?" has to be answerable
    from the row alone, so the assertions are on the approving user, the story
    approved and the commit that resulted -- not merely that *something* was
    logged.
    """
    from app import delivery

    tid = _make_target(client)
    monkeypatch.setattr(delivery, "ensure_bootstrapped", lambda a, tools=None: None)
    monkeypatch.setattr(
        delivery,
        "push_artifacts",
        lambda a, s, **kw: delivery.PushResult(
            app=a,
            story_id=s,
            repo="o/r",
            branch="qa/SCRUM-201-x",
            committed=True,
            delivered_sha="a" * 40,
            pr_url="https://github.com/o/r/pull/1",
            pr_number=1,
            pr_created=True,
            message="PR: https://github.com/o/r/pull/1",
        ),
    )

    resp = client.post(f"/targets/{tid}/deliver", json={"story_id": "SCRUM-201"})
    assert resp.status_code == 200

    (row,) = [e for e in audit.entries(session) if e.action is Action.DELIVERY_APPROVE]
    assert row.actor == ADMIN
    assert row.target == "target:saucedemo"
    assert row.at is not None
    # What was approved, and what it wrote into the customer's repo.
    assert row.after["story_id"] == "SCRUM-201"
    assert row.after["delivered_sha"] == "a" * 40
    assert row.after["pr_url"] == "https://github.com/o/r/pull/1"


def test_saving_a_pat_records_the_state_it_replaced(client, session):
    """Save and rotate are one action; `before` is what tells them apart.

    A first save goes from `absent`, a rotation from `valid` or `invalid`, so
    an auditor asking "when was this credential last rotated?" reads the
    states rather than trusting the call site to have picked the right verb.
    """
    tid = _make_target(client)

    first = client.put(f"/targets/{tid}/pat", json={"token": "ghp_first"})
    assert first.status_code == 200

    (row,) = [e for e in audit.entries(session) if e.action is Action.PAT_SAVE]
    assert row.actor == ADMIN
    assert row.target == "target:saucedemo"
    assert row.before == {"credential_state": "absent"}
    assert row.after["credential_state"] == "valid"
    # Whose token it is, which is the useful non-secret fact GitHub returned.
    assert row.after["login"] == "octocat"

    # A rotation: same action, and `before` now says there was a credential.
    second = client.put(f"/targets/{tid}/pat", json={"token": "ghp_second"})
    assert second.status_code == 200
    rotation, _original = [
        e for e in audit.entries(session) if e.action is Action.PAT_SAVE
    ]
    assert rotation.before == {"credential_state": "valid"}


def test_a_rejected_pat_records_nothing(client, session):
    """No mutation, no row. The route leaves the stored credential alone when
    validation fails (that is `save_pat`'s contract), so a row here would
    record a rotation that did not happen."""
    tid = _make_target(client)

    from app.api import get_token_validator
    from app.delivery.credentials import CredentialRejected
    from app.main import app as fastapi_app

    def refuse(token):
        raise CredentialRejected("missing the workflow scope")

    fastapi_app.dependency_overrides[get_token_validator] = lambda: refuse
    resp = client.put(f"/targets/{tid}/pat", json={"token": "ghp_bad"})

    assert resp.status_code == 422
    assert [e for e in audit.entries(session) if e.action is Action.PAT_SAVE] == []


def test_clearing_a_pat_is_recorded(client, session):
    tid = _make_target(client)
    client.put(f"/targets/{tid}/pat", json={"token": "ghp_first"})

    resp = client.delete(f"/targets/{tid}/pat")
    assert resp.status_code == 200

    (row,) = [e for e in audit.entries(session) if e.action is Action.PAT_CLEAR]
    assert row.actor == ADMIN
    assert row.before == {"credential_state": "valid"}
    assert row.after == {"credential_state": "absent"}


def test_no_audit_row_ever_carries_the_token(client, session):
    """The rule `app/delivery/credentials.py` holds for logs, held here too.

    A PAT save is the one audited mutation whose *input* is a secret, and
    `before`/`after` are free-form JSON -- so this asserts on every column of
    every row rather than on the two the save path happens to write. The
    credential's blast radius is the whole point of P5-03; a trail that
    recorded it would have reopened it.
    """
    tid = _make_target(client)
    client.put(f"/targets/{tid}/pat", json={"token": "ghp_supersecret"})
    client.delete(f"/targets/{tid}/pat")

    for row in audit.entries(session):
        rendered = repr([row.actor, row.action, row.target, row.before, row.after])
        assert "ghp_supersecret" not in rendered
        assert "supersecret" not in rendered


def test_resetting_a_target_repo_is_recorded(client, monkeypatch, session):
    """The other write into a customer's repo, and the destructive one."""
    from app import delivery

    tid = _make_target(client)
    monkeypatch.setattr(
        delivery,
        "reset_target",
        lambda a, **kw: delivery.ResetResult(
            app=a,
            repo="o/r",
            branch="master",
            already_empty=False,
            reset_branch=True,
            deleted_branches=("qa/SCRUM-1",),
            failed_branches=(),
            message="wiped",
        ),
    )

    resp = client.post(
        f"/targets/{tid}/reset", json={"confirm_repo": "o/r", "dry_run": False}
    )
    assert resp.status_code == 200

    (row,) = [e for e in audit.entries(session) if e.action is Action.TARGET_RESET]
    assert row.actor == ADMIN
    assert row.target == "target:saucedemo"
    # What was destroyed, which is the whole reason this one is audited.
    assert row.after["deleted_branches"] == ["qa/SCRUM-1"]
    assert row.after["repo"] == "o/r"


def test_an_infra_sync_at_target_creation_is_recorded(client, session):
    """`sync_infra` writes the harness's own files into the customer's repo, so
    it is a mutation of their repo even though the route it rides on is a
    create. Recorded as its own action rather than folded into the create: the
    create touches only our database."""
    tid = _make_target(client, sync_infra=True)
    assert tid

    (row,) = [e for e in audit.entries(session) if e.action is Action.INFRA_SYNC]
    assert row.actor == ADMIN
    assert row.target == "target:saucedemo"


def test_creating_a_target_without_sync_infra_records_no_infra_sync(client, session):
    """The flag is the mutation. Without it nothing reaches the customer's
    repo, so there is nothing to record."""
    _make_target(client, sync_infra=False)

    assert [e for e in audit.entries(session) if e.action is Action.INFRA_SYNC] == []


def test_a_quota_change_is_recorded_with_both_caps(session):
    """Audited at the repo function, because that is the only way to do it.

    `repo.set_tenant_caps` is deliberately not an API route -- "a tenant that
    could raise its own caps would not have caps" -- so this mutation is
    reached from a console. A mutation with no HTTP surface is still a
    mutation, and auditing it at the function is what covers the console as
    well as whatever route a later tenant-admin surface adds.

    The subject is the tenant, not a target, which is what `tenant:` says.
    """
    from app import repo

    with actor_scope(ADMIN):
        repo.set_tenant_caps(session, max_concurrent_runs=9)

    (row,) = [e for e in audit.entries(session) if e.action is Action.QUOTA_CHANGE]
    assert row.actor == ADMIN
    assert row.target == f"tenant:{DEFAULT_TENANT_ID}"
    # Both caps on both sides, not just the one that moved: "what were this
    # tenant's limits after that change?" is answerable from the row alone,
    # without replaying every earlier row to reconstruct the other cap.
    assert row.before == {"max_concurrent_runs": 3, "monthly_run_quota": 500}
    assert row.after == {"max_concurrent_runs": 9, "monthly_run_quota": 500}


def test_removing_a_cap_records_the_unmetered_value(session):
    """`None` means no cap, and is a value you can set on purpose. The trail
    has to distinguish "raised to unmetered" from "not changed"."""
    from app import repo

    with actor_scope(ADMIN):
        repo.set_tenant_caps(session, monthly_run_quota=None)

    (row,) = [e for e in audit.entries(session) if e.action is Action.QUOTA_CHANGE]
    assert row.before["monthly_run_quota"] == 500
    assert row.after["monthly_run_quota"] is None


def test_saving_a_prompt_override_records_who_saved_it(client, session):
    """Not in #37's list, recorded on purpose -- and #39 is why.

    A prompt steers an unattended agent against the customer's own
    application, so changing one is a control-plane mutation. `prompts` rows
    carry `created_at` but no actor, and #39 asks that the actor land here
    rather than becoming a column there, so that the two tickets do not end up
    as two half-answers. This is that answer.

    The revision is recorded, not the body: the body is already in `prompts`
    at that revision, and copying it would duplicate an unbounded blob into a
    table nothing can prune.
    """
    name = "qa_system_prompt.md"

    resp = client.put(f"/prompts/{name}", json={"content": "be careful"})
    assert resp.status_code == 200
    saved_rev = resp.json()["rev"]

    (row,) = [e for e in audit.entries(session) if e.action is Action.PROMPT_SAVE]
    assert row.actor == ADMIN
    assert row.target == f"prompt:{name}"
    assert row.after == {"rev": saved_rev}
    assert "be careful" not in repr(row.after)


def test_a_rejected_prompt_name_records_nothing(client, session):
    """A name the package never shipped is a 404 and writes no row, because it
    writes no prompt."""
    resp = client.put("/prompts/not-a-real-prompt.md", json={"content": "x"})

    assert resp.status_code == 404
    assert [e for e in audit.entries(session) if e.action is Action.PROMPT_SAVE] == []


# --- reads are scoped to the caller's tenant ------------------------------

def test_the_trail_is_not_readable_across_tenants(session):
    """#37's last criterion, and inherited rather than implemented.

    `AuditLog` is `TenantOwned`, so `tenancy.install_tenant_guard` filters the
    select in `audit.entries` like every other read in the tree. Asserted all
    the same: a trail that leaked would show one customer who approved what in
    another customer's repo, which is a worse disclosure than most of the rows
    this guard protects.
    """
    from sqlalchemy.orm import sessionmaker

    from app.models import Tenant
    from app.tenancy import tenant_scope

    session.add(Tenant(id=2, slug="second", name="Second"))
    session.commit()

    with actor_scope("admin@tenant-one.example"):
        audit.record(
            session, action=Action.DELIVERY_APPROVE, target="target:theirs"
        )

    # A fresh session, because a row already in the first one's identity map is
    # returned without a SELECT -- the documented limit of the read guard, and
    # the reason tests/test_tenant_isolation_repo.py uses the same shape.
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False, future=True)
    with factory() as fresh, tenant_scope(2):
        assert audit.entries(fresh) == []

    # and tenant 1 still sees its own
    with factory() as fresh:
        assert len(audit.entries(fresh)) == 1


def test_the_audit_route_returns_the_callers_rows_newest_first(client, session):
    """Through HTTP, which is the trust boundary the spec's isolation tests
    use. Newest first because a trail is read from the most recent event."""
    with actor_scope(ADMIN):
        audit.record(session, action=Action.PAT_CLEAR, target="target:one")
        audit.record(session, action=Action.TARGET_RESET, target="target:two")

    body = client.get("/audit").json()

    assert [e["action"] for e in body] == ["target.reset", "pat.clear"]
    assert body[0]["actor"] == ADMIN
    assert body[0]["target"] == "target:two"
    assert body[0]["at"]


def test_the_audit_route_is_tenant_admin_only(session):
    """A member can act on the surfaces that write these rows only where their
    role allows, but reading the whole tenant's trail -- who approved what, who
    rotated which credential -- is an admin's view of their own organisation."""
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from app.auth import require_auth, require_tenant_admin
    from app.db import get_session
    from app.main import app as fastapi_app

    def refuse():
        raise HTTPException(status_code=403, detail="tenant-admin role required")

    fastapi_app.dependency_overrides[get_session] = lambda: session
    fastapi_app.dependency_overrides[require_auth] = lambda: None
    fastapi_app.dependency_overrides[require_tenant_admin] = refuse
    try:
        assert TestClient(fastapi_app).get("/audit").status_code == 403
    finally:
        fastapi_app.dependency_overrides.clear()


# --- structural: the things that would fail quietly -----------------------

def test_every_action_fits_the_enum_column():
    """`models._enum_col` is VARCHAR(20), shared by every domain enum here.

    `delivery.approve` is 16 characters, so the margin is four. A longer action
    name added later would be refused by Postgres at the first write of it --
    at runtime, on the one mutation nobody is watching -- rather than here.
    """
    too_long = [a.value for a in Action if len(a.value) > 20]
    assert too_long == [], (
        f"these actions do not fit audit_log.action's VARCHAR(20): {too_long}; "
        "widen the column in a migration, or shorten the name"
    )


def test_the_actor_outside_a_request_is_the_system_actor(session):
    """The CLI and console path. `system` is a real answer -- those genuinely
    are not a logged-in user -- and must not be mistaken for a user the code
    failed to resolve, which is why `require_auth` binds the actor for every
    authenticated request rather than leaving it to each route."""
    from app.tenancy import SYSTEM_ACTOR, current_actor

    assert current_actor() == SYSTEM_ACTOR

    audit.record(session, action=Action.INFRA_SYNC, target="target:cli")
    (row,) = audit.entries(session)
    assert row.actor == SYSTEM_ACTOR


def test_the_actor_scope_does_not_leak_past_its_block(session):
    """The property that keeps one request's actor out of the next one's rows."""
    from app.tenancy import SYSTEM_ACTOR, current_actor

    with actor_scope("someone@example.com"):
        assert current_actor() == "someone@example.com"
    assert current_actor() == SYSTEM_ACTOR


def test_the_two_mutations_with_no_surface_are_recorded_as_a_gap():
    """#37 lists `user add/remove`; this asserts the absence is deliberate.

    There is no user-administration code path in the tree -- no route, no repo
    function, nothing but the migration that seeds the single operator. So
    there is no mutation to audit, and an `Action` member for it would read as
    covered while nothing could ever write it.

    This test fails the moment somebody adds that surface, which is exactly
    when the audit row has to be written: the assertion is "if you built user
    administration, come back and audit it". The sibling note is in
    `app/domain/audit.py`.
    """
    from app import repo
    from app.api import router

    paths = {route.path for route in router.routes}
    assert not [p for p in paths if "user" in p.lower()], (
        "a user-administration route now exists; #37 lists user add/remove as "
        "an audited mutation -- add the Action member and record it"
    )
    assert not [
        name
        for name in dir(repo)
        if not name.startswith("_")
        and "user" in name
        # `get_user_for_login` is a read, not a mutation.
        and name not in {"get_user_for_login"}
    ], "a user-administration repo function now exists; audit it (see #37)"


# --- a dry run is not a mutation ------------------------------------------

def test_a_dry_run_delivery_writes_no_row(client, monkeypatch, session):
    """It touches nothing in the customer's repo, so there is nothing to record.

    The first version of this recorded dry runs under `delivery.approve` with a
    flag, which would have left a compliance reader unable to trust the action
    alone: "every delivery into our repo last quarter" would have counted
    rehearsals. `delivery.approve` means a push happened.
    """
    from app import delivery

    tid = _make_target(client)
    monkeypatch.setattr(
        delivery,
        "push_artifacts",
        lambda a, s, **kw: delivery.PushResult(
            app=a, story_id=s, repo="o/r", branch="qa/x", committed=False,
            delivered_sha="", pr_url="", pr_number=None, pr_created=False,
            message="dry run",
        ),
    )

    resp = client.post(
        f"/targets/{tid}/deliver", json={"story_id": "SCRUM-201", "dry_run": True}
    )
    assert resp.status_code == 200
    assert [e for e in audit.entries(session) if e.action is Action.DELIVERY_APPROVE] == []


def test_a_dry_run_reset_writes_no_row(client, monkeypatch, session):
    from app import delivery

    tid = _make_target(client)
    monkeypatch.setattr(
        delivery,
        "reset_target",
        lambda a, **kw: delivery.ResetResult(
            app=a, repo="o/r", branch="master", already_empty=False,
            reset_branch=False, deleted_branches=("qa/SCRUM-1",),
            failed_branches=(), message="would wipe",
        ),
    )

    resp = client.post(
        f"/targets/{tid}/reset", json={"confirm_repo": "o/r", "dry_run": True}
    )
    assert resp.status_code == 200
    assert [e for e in audit.entries(session) if e.action is Action.TARGET_RESET] == []


# --- program output never carries a credential ----------------------------

def test_an_infra_sync_row_redacts_a_token_in_the_output(client, session):
    """`infra.sync` is the one action whose payload is program output.

    `apphub.run_bootstrap` turns a `DeliveryError` into `output=str(exc)`, and a
    git failure is built from the argv that failed -- which carries the PAT in
    the remote URL. This table is the worst place for that, because nothing
    prunes or deletes it, so the route redacts before recording.
    """
    from app.api import get_bootstrap_runner
    from app.apphub import BootstrapOutcome
    from app.main import app as fastapi_app

    leaky = (
        "git push failed: remote: Invalid username or password\n"
        "fatal: https://x-access-token:ghp_leakedtoken123@github.com/o/r.git"
    )
    fastapi_app.dependency_overrides[get_bootstrap_runner] = lambda: (
        lambda app_name: BootstrapOutcome(ok=False, output=leaky)
    )

    _make_target(client, sync_infra=True)

    (row,) = [e for e in audit.entries(session) if e.action is Action.INFRA_SYNC]
    assert row.after["ok"] is False
    assert "ghp_leakedtoken123" not in row.after["output"]
    # and the useful diagnosis survives the redaction
    assert "Invalid username or password" in row.after["output"]


def test_audit_text_is_bounded(client, session):
    """`audit_log` is the one table nothing may prune, so an unbounded field on
    it is growth that cannot be reclaimed."""
    from app.api import _AUDIT_TEXT_LIMIT, get_bootstrap_runner
    from app.apphub import BootstrapOutcome
    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_bootstrap_runner] = lambda: (
        lambda app_name: BootstrapOutcome(ok=True, output="x" * 50_000)
    )

    _make_target(client, sync_infra=True)

    (row,) = [e for e in audit.entries(session) if e.action is Action.INFRA_SYNC]
    assert len(row.after["output"]) < _AUDIT_TEXT_LIMIT + 100
    assert row.after["output"].endswith("(truncated)")
