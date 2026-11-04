"""The internal control plane's authorization boundary.

P5-05 takes `DATABASE_URL` and the `S3_*` credentials out of the sandbox, so
everything a run needs from Postgres and the blob store now arrives through one
module -- and that module is the only thing standing between a compromised
sandbox and every other run of every other tenant. These tests are about where
it says no.

The three refusals, which are the three acceptance criteria that matter:

- a token for one run may not act on another run, even in the same tenant;
- a token for one tenant may not act on another tenant's run or name another
  tenant's blobs;
- a token stops working once its run is no longer live.

Tested at the service rather than through HTTP because this is where the
decision is made; the routes get their own tests (tests/test_internal_api.py)
and the gateways theirs (tests/test_control_gateway.py). Prior art for the shape:
tests/test_tenant_isolation.py.
"""

from __future__ import annotations

import pytest

from app import repo, revisions
from app.control import service
from app.domain.status import RunStatus
from app.models import Tenant
from app.run_token import RunScope
from app.tenancy import tenant_scope
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def world(session, tmp_path):
    """Two tenants, each with a target at revision 1 and one live run.

    Two of everything on purpose: a single-tenant fixture cannot fail the test
    that matters most here.
    """
    store = FakeStorage()
    built = {}
    for tenant_id, app in ((1, "demo"), (None, "other")):
        if tenant_id is None:
            second = Tenant(name="Second", slug="second")
            session.add(second)
            session.commit()
            session.refresh(second)
            tenant_id = second.id
        with tenant_scope(tenant_id):
            project = repo.create_project(session, name=f"{app}-project")
            target = create_target(session, project.id, app=app, name=app.title())
            revisions.commit_revision(
                session,
                target,
                store,
                make_worktree(tmp_path / f"source-{app}"),
                author="operator",
            )
            run = repo.start_run(
                session, target_id=target.id, story_id="SCRUM-1", mode="full"
            )
            built[app] = {
                "tenant_id": tenant_id,
                "target_id": target.id,
                "run_id": run.id,
                "run_key": run.run_key,
                "scope": RunScope(
                    run_id=run.id, target_id=target.id, tenant_id=tenant_id
                ),
            }
    return built, store


# --- the scope is the whole of the authority -----------------------------

def test_a_run_can_read_its_own_facts(session, world):
    built, _ = world
    demo = built["demo"]

    with service.acting_as(demo["scope"]):
        facts = service.run_facts(session, demo["scope"])

    assert facts.run_key == demo["run_key"]
    assert facts.app == "demo"
    assert facts.story_id == "SCRUM-1"
    assert facts.target.base_url


def test_a_scope_whose_run_belongs_to_another_target_is_refused(session, world):
    """One tenant, two targets, so the tenant filter cannot be what refuses it.

    The target is in the token because it bounds the tree a run may commit to.
    A scope pairing this run with a target it does not belong to is therefore
    not a weaker token but an inconsistent one, and the service checks the pair
    against the row rather than trusting either half.
    """
    built, _ = world
    demo = built["demo"]
    with tenant_scope(demo["tenant_id"]):
        project = repo.create_project(session, name="second-project")
        sibling = create_target(session, project.id, app="sibling", name="Sibling")

    inconsistent = RunScope(
        run_id=demo["run_id"],
        target_id=sibling.id,
        tenant_id=demo["tenant_id"],
    )
    with service.acting_as(inconsistent), pytest.raises(service.NotAuthorized):
        service.run_facts(session, inconsistent)


def test_a_token_for_one_tenant_cannot_act_on_another_tenants_run(session, world):
    built, _ = world
    demo, other = built["demo"], built["other"]

    stolen = RunScope(
        run_id=other["run_id"],
        target_id=other["target_id"],
        tenant_id=demo["tenant_id"],
    )
    with service.acting_as(stolen), pytest.raises(service.NotAuthorized):
        service.run_facts(session, stolen)


@pytest.mark.parametrize(
    "finish",
    (RunStatus.COMPLETED, RunStatus.STOPPED, RunStatus.FAILED),
)
def test_a_token_is_refused_once_its_run_is_no_longer_live(session, world, finish):
    """Expiry is the backstop; this is the gate. A leaked token has to be
    worthless the moment the run it was minted for is over."""
    built, _ = world
    demo = built["demo"]
    with tenant_scope(demo["tenant_id"]):
        if finish is RunStatus.COMPLETED:
            repo.begin_run(session, demo["run_id"])
            repo.complete_run(session, demo["run_id"])
        elif finish is RunStatus.STOPPED:
            repo.stop_run(session, demo["run_id"])
        else:
            repo.fail_run(session, demo["run_id"], "whatever")

    with service.acting_as(demo["scope"]), pytest.raises(service.RunNotLive):
        service.run_facts(session, demo["scope"])


# --- blobs: a run may name its own tenant's, and its own run's -----------

def test_a_run_may_read_a_blob_of_its_own_head_revision(session, world):
    built, store = world
    demo = built["demo"]

    with service.acting_as(demo["scope"]):
        head = service.head_revision(session, demo["scope"])
        chunks, _ct = service.read_blob(
            session, demo["scope"], store, head.files[0].blob_key
        )

    assert b"".join(chunks)


def test_a_run_may_not_read_another_tenants_blob(session, world):
    """Story 25's half of this: no serve-by-key-alone. The key is a content
    hash, so a sandbox that learned one must still be refused."""
    built, store = world
    demo, other = built["demo"], built["other"]
    with service.acting_as(other["scope"]):
        other_head = service.head_revision(session, other["scope"])
    stolen_key = other_head.files[0].blob_key

    with service.acting_as(demo["scope"]), pytest.raises(service.NotAuthorized):
        service.read_blob(session, demo["scope"], store, stolen_key)


def test_a_run_may_not_write_an_artifact_under_another_runs_key(session, world):
    """Artifact keys are `<run_key>/<path>`, so the prefix is the authority."""
    built, store = world
    demo, other = built["demo"], built["other"]

    with service.acting_as(demo["scope"]), pytest.raises(service.NotAuthorized):
        service.authorize_artifact_key(
            demo["scope"], demo["run_key"], f"{other['run_key']}/trace.zip"
        )


# --- one tenant, two targets: the prefix is not the authority ------------
#
# Blob keys are `tenant/<id>/blobs/<sha>`, so two targets of one tenant share a
# content-address space. The tenant prefix therefore cannot be what authorizes a
# blob -- it would let one target's run read and overwrite another's tree, which
# #33's "the token authorizes exactly that run's target" forbids and #30's "no
# serve-by-key-alone" names directly.

@pytest.fixture()
def sibling(session, world, tmp_path):
    """A second target of the *same* tenant, holding a blob only it has.

    The distinctive file matters and is the point of the comment: blob keys are
    content hashes scoped per tenant, so two targets with identical trees share
    every blob -- and a row check correctly authorizes those for both, because
    they *are* both targets' content. Dedup is not a leak. What must be refused
    is a blob only the sibling's revision references, which is why this writes
    one.
    """
    built, store = world
    demo = built["demo"]
    source = make_worktree(tmp_path / "source-sibling")
    unique = source / "tests" / "checkout" / "sibling-only.spec.ts"
    unique.parent.mkdir(parents=True, exist_ok=True)
    unique.write_text("// only the sibling target has this\n")
    with tenant_scope(demo["tenant_id"]):
        project = repo.create_project(session, name="sibling-project")
        target = create_target(session, project.id, app="sibling", name="Sibling")
        revisions.commit_revision(
            session, target, store, source, author="operator"
        )
        head = revisions.head_revision(session, target.id)
        rows = {r.path: r.blob_key for r in revisions.list_files(session, head.id)}
    key = rows["tests/checkout/sibling-only.spec.ts"]
    # The premise: this blob belongs to the sibling and to nothing of demo's.
    assert not revisions.blob_is_referenced_by_target(
        session, demo["target_id"], key
    )
    return {"target_id": target.id, "blob_key": key}


def test_a_run_cannot_read_a_sibling_targets_blob_of_its_own_tenant(
    session, world, sibling
):
    """The same tenant, so the tenant filter cannot be what refuses this, and
    the same prefix, so the prefix rule cannot be either. The row is."""
    built, store = world
    demo = built["demo"]

    with service.acting_as(demo["scope"]), pytest.raises(service.NotAuthorized):
        service.read_blob(session, demo["scope"], store, sibling["blob_key"])


def test_a_run_cannot_overwrite_a_sibling_targets_blob(
    session, world, sibling, tmp_path
):
    """The one way this seam could corrupt data it cannot read.

    `commit_revision` confirms a blob exists rather than what is in it, so bytes
    written under a sibling's blob key would be materialized into *that*
    target's next hydrate -- and verified against the key, which would then
    fail the sibling's run rather than this one. Content addressing closes it:
    the only bytes writable under a key are the bytes it already names.
    """
    built, store = world
    demo = built["demo"]
    poison = tmp_path / "poison.spec.ts"
    poison.write_bytes(b"// not what that key names\n")

    with service.acting_as(demo["scope"]), pytest.raises(service.NotAuthorized):
        service.write_blob(
            session, demo["scope"], store, sibling["blob_key"], poison
        )

    # ...and the sibling's blob is untouched.
    assert store.objects[sibling["blob_key"]][0] != poison.read_bytes()
