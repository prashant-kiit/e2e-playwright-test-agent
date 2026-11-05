"""The enforced read path, at the repository (P5-02, #32).

The other half of the seam `test_tenant_isolation.py` opens. That file asks the
question through HTTP, which is the trust boundary; this one asks it of the read
functions directly, for two reasons the HTTP tests cannot cover:

* **a read path with no route over it is still a read path.** The delivery
  catalog, the log bus and `revisions` are all reachable from the CLI, the
  orchestrator and the sandbox, not only from a browser;
* **enumerating the functions is what keeps this exhaustive.** A reader can see
  at a glance which reads are asserted, and a read added later is a line here.

The last two tests are different in kind: they do not test a read, they test
that the *mechanism* cannot be quietly dropped -- a new table that forgets the
mixin, or a new query that opts out without saying so.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import delete, update
from sqlalchemy.orm import sessionmaker

from app import audit, repo, revisions
from app.db import Base
from app.domain.audit import Action
from app.models import (
    Artifact,
    FileIndex,
    Project,
    Revision,
    RunLog,
    Tenant,
    TenantOwned,
)
from app.orchestrator.bus import PostgresLogBus
from app.tenancy import (
    DEFAULT_TENANT_ID,
    across_tenants,
    actor_scope,
    current_tenant_id,
    tenant_scope,
)
from tests.target_helpers import create_target

OTHER = 2  # the tenant that owns nothing here


@pytest.fixture()
def mine(session):
    """A session of my own, for the reads that must come up empty.

    Separate from the fixture's session on purpose, and the reason is the one
    documented limit of the read guard: a row already in a session's **identity
    map** is returned by `Session.get()` without a SELECT, so the filter never
    runs. The fixture below writes the estate through `session`, which leaves
    every one of those rows in its map -- read back through that same session,
    `get_project` would hand them over and this file would have reported
    isolation that does not exist.

    A request never shares a session with another tenant's writes (each gets
    its own from `get_session`), so this is also the realistic shape. It is
    kept as a fixture rather than hidden in a helper because the distinction is
    the point: these tests only mean something read through a fresh session.
    """
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False, future=True)
    with factory() as fresh:
        yield fresh


@pytest.fixture()
def theirs(session):
    """A full estate owned by the default tenant, and a second empty tenant.

    Every test then reads *as* tenant 2 and must come up empty: one fixture, so
    the reads are the only thing that varies between them.
    """
    session.add(Tenant(id=OTHER, slug="second", name="Second"))
    session.commit()

    project = repo.create_project(session, name="theirs")
    target = create_target(session, project.id, app="theirs", name="Theirs")
    run = repo.start_run(session, target_id=target.id, story_id="SCRUM-1", mode="full")
    step = repo.start_step(session, run.id, repo.Step.READ_STORY)
    artifact = Artifact(
        tenant_id=DEFAULT_TENANT_ID,
        run_id=run.id,
        step="heal",
        kind="report",
        s3_key=f"{run.run_key}/report.html",
        sha256="x" * 64,
        version=1,
    )
    session.add(artifact)
    session.add(
        RunLog(run_id=run.id, seq=1, tenant_id=DEFAULT_TENANT_ID, line="a secret line")
    )
    # A revision, inserted rather than committed through `revisions`: this is
    # the repository layer, where `create_target` does not commit revision 1 --
    # the API route does, and it needs a blob store to do it.
    revision = Revision(
        tenant_id=DEFAULT_TENANT_ID,
        target_id=target.id,
        rev=1,
        tree_hash="a" * 64,
        author="test",
    )
    session.add(revision)
    session.flush()
    session.add(
        FileIndex(
            revision_id=revision.id,
            path="README.md",
            tenant_id=DEFAULT_TENANT_ID,
            blob_key="tenant/1/blobs/" + "a" * 64,
            size=3,
        )
    )
    session.commit()
    # A control-plane mutation of theirs (P5-07): the trail says who approved a
    # delivery into *their* repo, so it is one of the reads that must come up
    # empty for anyone else.
    with actor_scope("admin@theirs.example"):
        audit.record(
            session,
            action=Action.DELIVERY_APPROVE,
            target=audit.target_ref(target.app),
            after={"story_id": "SCRUM-1"},
        )
    return {
        "project": project,
        "target": target,
        "run": run,
        "step": step,
        "artifact": artifact,
        "revision": revision,
    }


# --- listings return only the caller's rows -------------------------------

def test_listings_are_empty_for_a_tenant_that_owns_nothing(mine, theirs):
    """Every list read, in one test: none of them may show a foreign row.

    Asserted as emptiness rather than as a filtered subset because the fixture
    gives tenant 2 nothing at all -- so any row at all coming back is a leak,
    and the assertion cannot pass by accident of ordering or of a limit.
    """
    with tenant_scope(OTHER):
        assert repo.list_projects(mine) == []
        assert repo.list_targets(mine) == []
        assert repo.list_targets(mine, project_id=theirs["project"].id) == []
        assert repo.list_runs(mine) == []
        assert repo.list_runs(mine, target_id=theirs["target"].id) == []
        assert revisions.list_revisions_with_file_counts(
            mine, theirs["target"].id
        ) == []
        assert audit.entries(mine) == []


def test_direct_id_reads_fail_closed_for_another_tenants_rows(mine, theirs):
    """Knowing the id is not authorization. Ids here are small integers.

    `NotFound` rather than a 403-shaped error on purpose: a reader who does not
    own the row should not be able to tell "exists, not yours" from "does not
    exist", or the ids become an inventory of what other tenants have.
    """
    with tenant_scope(OTHER):
        for read, arg in (
            (repo.get_project, theirs["project"].id),
            (repo.get_target, theirs["target"].id),
            (repo.get_run, theirs["run"].id),
        ):
            with pytest.raises(repo.NotFound):
                read(mine, arg)


def test_revision_reads_fail_closed_for_another_tenants_target(mine, theirs):
    """The blob-authorizing reads (DESIGN.md §9).

    `revisions.get_revision` is what makes a blob fetch authorized by a row
    rather than by knowledge of a key, so a foreign revision answering here
    would hand over the tree behind it -- the target's stories, plans and test
    suite.
    """
    head = theirs["revision"]
    assert revisions.get_file(mine, head.id, "README.md") is not None  # mine to read

    with tenant_scope(OTHER):
        assert revisions.head_revision(mine, theirs["target"].id) is None
        assert revisions.get_revision(mine, head.id) is None
        assert revisions.list_files(mine, head.id) == []
        assert revisions.get_file(mine, head.id, "README.md") is None
        assert revisions.count_files(mine, head.id) == 0


def test_the_live_log_of_another_tenants_run_is_not_readable(session, theirs):
    """The log carries the agent's output verbatim -- URLs, selectors, failures."""
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False, future=True)
    bus = PostgresLogBus(session_factory=factory)
    assert bus.read_from(theirs["run"].id, 0) == (["a secret line"], 1)

    with tenant_scope(OTHER):
        assert bus.read_from(theirs["run"].id, 0) == ([], 0)


def test_a_write_to_another_tenants_row_is_refused_before_it_writes(mine, theirs, session):
    """The mutators are guarded too, because each reads before it writes.

    `repo.py`'s writes all resolve their row through `get_run`/`get_target`
    first, so the read guard is what refuses them: a foreign id fails closed
    rather than being updated. That is the property that makes "the guard is a
    *read* guard" an acceptable boundary -- not that writes are separately
    filtered, but that none of them finds its row without a filtered read.
    """
    with tenant_scope(OTHER):
        for write, args in (
            (repo.request_stop, (theirs["run"].id,)),
            (repo.request_pause, (theirs["run"].id,)),
            (repo.update_target_config, (theirs["target"].id,)),
            (repo.set_sandbox_handle, (theirs["run"].id, "abc")),
        ):
            with pytest.raises(repo.NotFound):
                write(mine, *args)

    # ...and the row is untouched: nothing was half-written before the refusal.
    session.refresh(theirs["run"])
    assert theirs["run"].stop_requested is False
    assert theirs["run"].pause_requested is False
    assert theirs["run"].sandbox_handle is None


def test_a_tenant_still_reads_its_own_rows(mine, theirs):
    """The control. A filter that hid everything would pass every test above.

    Worth stating explicitly: the failure mode of a guard like this is not only
    "leaks" but "refuses the owner too", and nothing else in this file would
    notice.
    """
    assert current_tenant_id() == DEFAULT_TENANT_ID
    assert [p.id for p in repo.list_projects(mine)] == [theirs["project"].id]
    assert repo.get_run(mine, theirs["run"].id).id == theirs["run"].id
    assert revisions.head_revision(mine, theirs["target"].id) is not None


# --- the mechanism cannot be quietly dropped ------------------------------

def test_every_tenant_owned_table_inherits_the_mixin():
    """A new table with a `tenant_id` must inherit `TenantOwned`, or it has no
    filter at all.

    `install_tenant_guard` filters the mapped subclasses of that one mixin, so
    inheriting it is not decoration -- it is the whole of what makes a table's
    rows readable only by their owner. `test_tenancy.py` asserts the *column*
    exists everywhere; this asserts the column arrives by the route the guard
    can see.
    """
    offenders = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if "tenant_id" in mapper.columns and not issubclass(cls, TenantOwned):
            offenders.append(cls.__name__)
    assert offenders == [], (
        f"{offenders} carry tenant_id without inheriting TenantOwned, so the "
        "tenant guard does not apply to them"
    )


# Every place in `app/` allowed to reach across tenants, as "module: function".
# A bypass is legitimate only where no tenant is acting yet or where every
# tenant is; each of these says which in its own docstring.
#
# **Reads *and* writes, since P5-12.** This list was a read allowlist while the
# guard was a SELECT-time filter. The guard now covers ORM bulk UPDATE and
# DELETE too, so a cross-tenant *write* takes the same opt-out and belongs on
# the same list -- `bus.prune_run_logs` is the first. Leaving the name and the
# docs saying "read" would have reproduced one file over the exact defect P5-12
# renamed `install_read_guard` to remove: a reviewer assuming the mechanism
# does not reach writes.
#
# **If this test fails, do not simply add the new name.** Ask first whether the
# read can be done inside a tenant scope instead -- `reaper._for_each_tenant`
# is what that looks like, and it is why the sweeps are not on this list.
ALLOWED_BYPASSES = {
    # Login resolves *which* tenant is acting, so it cannot already be scoped.
    "repo: get_user_for_login",
    # The cross-tenant primary-key read itself, used by the two below.
    "repo: get_run_across_tenants",
    # P5-05 deleted the third entry that used to be here,
    # `launcher: _run_tenant_scope`. It read a run across tenants in order to
    # discover whose it was, so that the background path could bind a tenant the
    # way `require_auth` does for a request -- a genuine chicken-and-egg while
    # the sandbox read the database itself. It does not any more: the run-scoped
    # token carries the tenant, it is minted while that tenant is acting (so the
    # read is filtered), and `control.service.acting_as` binds it per operation.
    # The honest version of this allowlist got shorter, which is the direction
    # the comment above asks for.
    # Resolves a reaped run's tenant before its sandbox is destroyed.
    "reaper: _tenant_of",
    # The retention sweep, which is the one bulk write whose job *is* every
    # tenant's rows. It arrived here when P5-12 put ORM UPDATE/DELETE under the
    # guard: before that it needed no opt-out because the guard did not reach
    # writes, and the honest way to keep it spanning tenants is to declare it
    # rather than to leave the guard not covering deletes at all.
    "bus: prune_run_logs",
}

# The identifiers that mean "this read is not tenant-filtered". `ACROSS_TENANTS`
# and the raw option string are here as well as the helpers, so that writing
# `.execution_options(qa_across_tenants=True)` by hand -- going round
# `across_tenants()` entirely -- is caught too. That spelling is the one a scan
# of the helpers alone would miss, and it is the easiest one to reach for.
_BYPASS_NAMES = frozenset(
    {
        "across_tenants",
        "ACROSS_TENANTS",
        "ACROSS_TENANTS_OPTION",
        "get_run_across_tenants",
    }
)
_BYPASS_STRINGS = frozenset({"qa_across_tenants"})
_APP = Path(__file__).resolve().parents[1] / "app"


def _mentions_a_bypass(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in _BYPASS_NAMES:
            return True
        if isinstance(child, ast.Attribute) and child.attr in _BYPASS_NAMES:
            return True
        if isinstance(child, ast.keyword) and child.arg in _BYPASS_STRINGS:
            return True
        if isinstance(child, ast.Constant) and child.value in _BYPASS_STRINGS:
            return True
    return False


def _bypass_sites() -> set[str]:
    """Every place in `app/` that mentions a cross-tenant read or write, by name.

    A source scan rather than a runtime hook because the claim is about the code
    as written: the point is that a *new* unfiltered query is visible, including
    one on a path no test happens to execute. `tenancy.py` is skipped -- it
    defines the mechanism.

    Module-level code is reported as `<module>` rather than skipped. A scan that
    only walked function bodies would miss a bypassed statement built at import
    time, which is both legal and exactly the shape that would not look like a
    query to a reviewer.
    """
    sites: set[str] = set()
    for path in sorted(_APP.rglob("*.py")):
        if path.name == "tenancy.py":
            continue
        tree = ast.parse(path.read_text())
        functions = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        for node in functions:
            if _mentions_a_bypass(node):
                sites.add(f"{path.stem}: {node.name}")
        # Whatever is left once every function body is excluded.
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            if _mentions_a_bypass(node):
                sites.add(f"{path.stem}: <module>")
    return sites


def test_reaching_across_tenants_is_a_short_allowlist():
    """#32's criterion, as a test: a bypass is the detectable exception.

    Named for reaching rather than reading since P5-12: the guard covers bulk
    UPDATE and DELETE now, so this pins the cross-tenant *writes* as well, and
    a name that said "reading" would invite the assumption that a write bypass
    is not on this list.

    The guard means a query cannot *forget* the tenant filter -- forgetting now
    takes an explicit opt-out. This is what makes that opt-out detectable: the
    set of places that take it is pinned, so adding one is a deliberate edit to
    a list with instructions on it, and not a line in a diff that reads like
    every other query.
    """
    assert _bypass_sites() == ALLOWED_BYPASSES


def test_the_bypass_scan_catches_a_hand_written_opt_out():
    """The allowlist is only worth something if its scanner sees every spelling.

    The easy way round `across_tenants()` is to write the execution option
    directly, which mentions none of the helper names. If the scanner missed
    that, the allowlist test would pass while an unfiltered query sat in the
    tree -- the failure mode that makes a guard worse than none, because it
    looks guarded.
    """
    assert _mentions_a_bypass(
        ast.parse("stmt = select(Run).execution_options(qa_across_tenants=True)")
    )
    assert _mentions_a_bypass(ast.parse("row = session.get(Run, 1, **ACROSS_TENANTS_OPTION)"))
    assert _mentions_a_bypass(ast.parse("opts = {'qa_across_tenants': True}"))
    # ...and does not fire on an ordinary query.
    assert not _mentions_a_bypass(ast.parse("rows = session.scalars(select(Run)).all()"))


# --- the guard covers writes, not only reads (P5-12) ---------------------

def test_a_bulk_update_cannot_reach_another_tenants_row_by_id(session, theirs):
    """Story 6's "a missing filter is a bug that fails closed rather than a
    leak" applies to writes with the same force it applies to reads.

    The guard was a `SELECT`-time loader filter, and its own docstring said so:
    `is_select` is false for an ORM bulk `UPDATE`, so `update(Project).where(
    Project.id == n)` reached any tenant's row by id. The decision in #30 that
    reads go through "a single enforced path ... so a new query cannot forget
    the filter" has no reading under which writes are exempt -- a bulk update
    that forgets `tenant_id` looks exactly like one that does not need it,
    which is the property the guard exists to remove.

    Asserted on the row being *unchanged* rather than on a raised error,
    because the filter is a `WHERE` clause and not an assertion: the statement
    runs, matches nothing, and the other tenant's row is untouched.
    """
    project_id = theirs["project"].id
    before = session.scalars(
        across_tenants(repo.select(Project).where(Project.id == project_id))
    ).one().name

    # Acting as the tenant that owns nothing here.
    with tenant_scope(OTHER):
        session.execute(
            update(Project).where(Project.id == project_id).values(name="stolen")
        )
        session.commit()

    after = session.scalars(
        across_tenants(repo.select(Project).where(Project.id == project_id))
    ).one().name
    assert after == before == "theirs", (
        f"another tenant renamed project {project_id} to {after!r}; a bulk "
        f"UPDATE reached outside the acting tenant"
    )


def test_a_bulk_delete_cannot_reach_another_tenants_row_by_id(session, theirs):
    """The sibling, and the more consequential half: an unfiltered bulk delete
    by id destroys another tenant's data rather than merely disclosing it."""
    run_id = theirs["run"].id

    with tenant_scope(OTHER):
        session.execute(delete(RunLog).where(RunLog.run_id == run_id))
        session.commit()

    survived = session.scalars(
        across_tenants(repo.select(RunLog).where(RunLog.run_id == run_id))
    ).all()
    assert survived, (
        f"another tenant deleted every log line of run {run_id}; a bulk "
        f"DELETE reached outside the acting tenant"
    )


def test_a_bulk_update_still_reaches_the_acting_tenants_own_rows(session, theirs):
    """The guard filters writes; it does not block them.

    Without this the two tests above would pass against a guard that made every
    bulk write match nothing at all, which would be a silent data-loss bug
    rather than isolation.
    """
    project_id = theirs["project"].id

    session.execute(
        update(Project).where(Project.id == project_id).values(name="renamed")
    )
    session.commit()

    assert session.scalars(
        repo.select(Project).where(Project.id == project_id)
    ).one().name == "renamed"
