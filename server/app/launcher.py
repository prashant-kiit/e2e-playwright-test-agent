"""Starts the orchestrator for a run, and composes everything around it.

Kept separate from the API so tests can override it with a no-op (they drive the
driver directly with a FakeRunner). The real launcher picks the configured
runner, streams log lines to the configured bus, and closes the stream when the
run ends.

**One composition, two call sites.** `drive_run` is the whole of "work a run":
heartbeat, runner, composition, close the stream. The thread launcher calls it
on a daemon thread (`launch_run`); the sandbox entrypoint calls it as a process
(`app/sandbox/run.py`). There is no second pipeline for the container to use,
which is the thing a structural test keeps true
(tests/test_sandbox_entrypoint.py) because a second pipeline is invisible to a
behavioural test for as long as it happens to agree.

It is also where everything that happens *around* a run is composed: hydrate
before the pipeline, teardown after it, and the step-boundary hook the driver
fires after each completed step. The driver keeps exactly one injection point
(DESIGN.md §13) and this module is what composes into it.

Hydrate, ingest and teardown are plain functions composed here rather than
driver parameters, which is what makes P4's move into a container-per-run a
change of *where* they run and not of *what* they do.

**P5-05 replaced the pair `(session_factory, store)` with one gateway.** Every
database read, every database write and every blob a run touches goes through
`control` (app/control/gateway.py), which is a run-scoped token's worth of
authority and nothing more. The composition did not move: the same three calls
in the same order, with the same `finally`. What changed is that a sandbox no
longer holds `DATABASE_URL` or the `S3_*` credentials, and so the question "what
can a compromised run reach?" has a readable answer -- the gateway's method list.

The store is **not** a separate parameter any more, deliberately: it is always
`GatewayStorage(control)`, so a run's only way to a blob is its own token. A
`store=` beside a `control=` would be a second authority, and the one place it
would get used is the one place it should not be.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import config, revisions
from .artifacts import ArtifactCollector
from .control import factory
from .control.gateway import GatewayStorage, RunGateway
from .control.model import TrackedBlob
from .domain.status import RunStatus
from .domain.steps import Step
from .orchestrator.bus import LogBus, bus_from_env
from .orchestrator.claude import ClaudeRunner
from .orchestrator.driver import run_pipeline
from .orchestrator.fake import FakeRunner
from .orchestrator.limits import LimitedRunner
from .orchestrator.runner import Emit, Runner
from .reaper import heartbeat_during
from .sandbox import hydrate
from .sandbox import session as agent_session

log = logging.getLogger(__name__)

# A step-boundary half: it is handed the run and the step that just completed.
# One of the two may raise, and that is deliberate -- see make_step_boundary_hook.
BoundaryHalf = Callable[[int, Step], None]


def make_runner() -> Runner:
    """The configured Runner, with P4's limits around it.

    The limits wrap whichever runner is configured rather than living in one of
    them: a wall clock only the real runner respects is a wall clock the fake
    path cannot be tested against, and a budget only the fake reports is no
    budget at all.
    """
    inner: Runner
    if config.runner_kind() == "fake":
        inner = FakeRunner(
            delay=config.fake_delay(), writes_tree=config.fake_tree_writes()
        )
    else:
        inner = ClaudeRunner()
    return LimitedRunner(inner)


def make_collector(control: RunGateway, run_key: str) -> BoundaryHalf:
    """A collect(run_id, step) callback that sweeps the run dir into storage."""
    collector = ArtifactCollector(GatewayStorage(control), control)

    def collect(run_id: int, step: Step) -> None:
        collector.collect(run_key, config.run_dir(run_key), step)

    return collect


def make_ingest(control: RunGateway, run_key: str) -> BoundaryHalf:
    """An ingest(run_id, step) callback that commits a revision of the worktree.

    Upload the tracked tree's blobs, then commit one revision naming them. A
    step that changed no tracked file commits nothing: three of the five steps
    routinely change nothing, and a revision per step would make `rev` a step
    counter rather than a count of real changes.

    It reads the run's own hydrated worktree, which is the only tree the agent
    worked in, so a revision describes that run's work and nothing else.

    **The generated entries are re-rendered before the scan.** Paired with
    hydrate's render step, that gives the generated config exactly one author:
    whatever the agent did to it is overwritten by the row's version before the
    tree is decided, so an edit to it is not a tree change and never reaches a
    revision. An edit to a real file in the same step still is one.

    **The scan is here and the row is written there**, which is P5-05's split:
    the worktree is on the sandbox's disk and the `revisions` row is in a
    database the sandbox cannot reach. So this scans, uploads the blobs through
    the gateway, and hands over a manifest; the control plane recomputes the tree
    hash from that manifest and confirms every blob arrived before it writes
    anything (app/control/service.py). Neither half can be told what the other
    found.

    **The target's configuration is read once, here, not per boundary.** It
    cannot change under a live run -- `repo.assert_no_live_run` refuses a config
    write while one holds the target -- and `RunFacts` is documented as a run's
    *immutable* facts, read once. Fetching it inside the closure meant five
    round trips per run on the container path for a value that cannot have
    moved.

    Raises on failure, and the caller does not catch it. See
    make_step_boundary_hook.
    """
    store = GatewayStorage(control)
    cfg = control.run_facts().target

    def ingest(run_id: int, step: Step) -> None:
        root = config.worktree_dir(run_key)
        hydrate.render_generated(root, cfg)
        scan = revisions.scan_tracked_tree(root)
        revisions.upload_blobs(store, scan, control.scope.tenant_id)
        control.commit_revision(
            [
                TrackedBlob(path=f.path, sha256=f.sha256, size=f.size)
                for f in scan.files
            ],
            # Fits Revision.author's 100 chars: run_key is at most 80.
            author=f"run:{run_key}",
        )

    return ingest


def make_step_boundary_hook(
    emit: Emit,
    control: RunGateway,
    run_key: str,
    *,
    collect: BoundaryHalf | None = None,
    ingest: BoundaryHalf | None = None,
) -> BoundaryHalf:
    """The driver's ONE step-boundary callable, with every half composed in.

    Order is deliberate: **artifacts, then the session, then ingest.** What is
    cheapest to lose goes first and never delays the work that matters more.

    The halves are treated differently, and the asymmetry is the phase:

    - **Artifact collection stays best-effort.** Its failure is reported to the
      run's log and swallowed. Evidence is not the work; losing a trace is not a
      reason to fail a run that produced a healed suite.
    - **The session archive stays best-effort too**, and it is here rather than
      only at the end of a run because pause destroys the container at once
      (app/api.py): a sandbox killed without warning archives nothing, so the
      boundary is the last moment the session is known good. A pause costs the
      exploration of the step it interrupted and no more.
    - **A failed ingest fails the run.** It is reported to the log and then
      re-raised. P2's code said so in a comment, because while `apps/` was
      authoritative a swallowed failure cost nothing -- and once truth has moved
      into Postgres, a swallowed failure means a run that reports success having
      dropped its work. That inversion is not a regression in robustness; it is
      the point at which a dropped write stops being free.

    Catching the artifact half here (rather than relying on the driver) is what
    lets the ingest half still run when the sweep fails, and what lets ingest's
    exception reach the driver rather than being lost behind the first failure.
    """
    collect_half = collect if collect is not None else make_collector(control, run_key)
    ingest_half = ingest if ingest is not None else make_ingest(control, run_key)

    def on_step_boundary(run_id: int, step: Step) -> None:
        try:
            collect_half(run_id, step)
        except Exception as exc:
            emit(f"=== step {step.value}: artifact collection failed: {exc} ===")

        # Already swallows its own failures, and already a no-op off a sandbox.
        _persist_session(control, run_key, emit)

        try:
            ingest_half(run_id, step)
        except Exception as exc:
            # Reported *and* propagated: the run fails, and the operator reading
            # the log does not have to infer the reason from a status.
            emit(f"=== step {step.value}: ingest failed: {exc} ===")
            raise

    return on_step_boundary


def hydrate_worktree(control: RunGateway, run_key: str, emit: Emit) -> Path:
    """Build the run's worktree from its target's head revision. Returns the path.

    Raises on anything that would leave the agent working in a tree we cannot
    vouch for -- no head revision, a missing blob, bytes that do not match their
    content hash -- and the caller fails the run on it. That is the inversion P3
    is: before the flip a failed revision write cost nothing, and now a run
    without a verified tree must not start.

    There is no baseline-from-disk fallback. P2 had one because `apps/` was the
    tree a run inherited; there is no disk to baseline from now, and every target
    gets revision 1 when it is created.
    """
    dest = config.worktree_dir(run_key)
    # A worktree left behind by a crashed previous attempt at this run_key is
    # not a tree to inherit: hydrate is the only author of this directory.
    hydrate.teardown(dest)
    hydrate.hydrate(control, GatewayStorage(control), dest, emit=emit)
    return dest


def run_with_worktree(
    control: RunGateway,
    run_key: str,
    emit: Emit,
    runner: Runner,
    *,
    collect: BoundaryHalf | None = None,
) -> None:
    """Hydrate, drive the pipeline in that worktree, then tear it down.

    The composition the whole phase turns on, and it is deliberately boring:
    three function calls and a `finally`. Teardown runs at every terminal state
    and on pause, so disk use is bounded by live runs rather than by history; a
    resumed run comes back through here and re-hydrates from the head.
    """
    try:
        worktree = hydrate_worktree(control, run_key, emit)
    except Exception as exc:
        # No tree, so no step may be attempted. Fail the run and free the app.
        control.fail_run(f"hydrate failed: {exc}")
        emit(f"=== run failed before it started: {exc} ===")
        return

    hook = make_step_boundary_hook(emit, control, run_key, collect=collect)
    try:
        run_pipeline(control, control.scope.run_id, runner, emit=emit, collect=hook)
    finally:
        hydrate.teardown(worktree)
        emit("=== teardown: worktree removed ===")


def drive_run(
    control: RunGateway,
    *,
    runner: Runner | None = None,
    bus: LogBus | None = None,
) -> None:
    """Work the run: heartbeat, runner, the composition, close the stream.

    The one function both call sites use. Its keyword arguments are the things a
    container otherwise takes from its environment -- the runner and the log bus
    -- passed in rather than read from `env` so the entrypoint is testable
    without a container, exactly as `run_with_worktree` already allows. The
    database and the object store are no longer among them: they arrive as the
    one `control` gateway, which is the whole of P5-05.

    **There is no tenant scope opened here any more.** `_run_tenant_scope` used
    to read the run in order to bind its tenant for the work -- the background
    equivalent of `require_auth` -- and it needed a cross-tenant read to do it,
    which is why it was on the bypass allowlist. The token carries the tenant
    now, and the gateway binds it per operation (`service.acting_as`), so the
    chicken-and-egg that function existed to resolve does not arise: nothing on
    this path reads a row without a scope, because nothing on this path reads a
    row at all.

    The heartbeat is taken **here**, inside whichever process does the work, so
    the reaper's crash detection measures the thing that is actually working
    rather than a thread in a process that may be fine while the run is not. It
    wraps hydrate too: the lease is otherwise refreshed only at step boundaries,
    and `npm ci` on a cold cache outlasts the TTL easily.
    """
    bus = bus or bus_from_env()
    run_id = control.scope.run_id
    emit = bus.emitter(run_id)
    runner = runner or make_runner()
    started = time.monotonic()
    # Read once, before anything can end the run: the run key is immutable, and
    # the paths in the `finally` below need it after the liveness gate has shut.
    run_key = control.run_facts().run_key
    try:
        # Inside the `try`, so a failure here still closes the stream a reader
        # is waiting on rather than leaving it open on a run nothing is driving.
        _restore_session(control, run_key, emit)
        with heartbeat_during(run_id, control.heartbeat):
            run_with_worktree(control, run_key, emit, runner)
    finally:
        # Both in a `finally`, so every way out of a run records what it cost
        # and leaves the agent's session where a resume can find it. A pause
        # does not come through here at all -- its container is killed outright
        # -- which is why the session is archived at each step boundary too.
        _persist_session(control, run_key, emit)
        _record_cost(control, runner, started)
        bus.close(run_id)


def _restore_session(control: RunGateway, run_key: str, emit: Emit) -> None:
    """Put a resumed run's agent session back before the pipeline starts.

    Before, rather than inside, the composition: the CLI is invoked by the first
    step, and the session has to be on disk by then. A run with no recorded
    session is a first run and says nothing -- a line about continuity on every
    fresh run would be noise.

    If the restore fails the run continues **without** continuity, and the
    recorded session id is cleared so the next step does not tell the CLI to
    `--resume` a session that is not there (a failed step rather than a
    forgotten exploration).
    """
    if not control.run_state().claude_session_id:
        return
    if agent_session.restore(control, run_key, GatewayStorage(control), emit=emit):
        return
    control.clear_session_id()


def _persist_session(control: RunGateway, run_key: str, emit: Emit) -> None:
    """Archive the agent's session as this run's reserved artifact.

    Never allowed to fail the run: the tree is the carrier of the work, and the
    session is the context for continuing it.

    **Skipped unless the run is still RUNNING**, and that is not a workaround
    for the token's authorization gate but the same judgement the gate encodes.
    Two readings of "not running", with the same answer:

    - *completed, stopped or failed*: a terminal run cannot be resumed, so
      there is nothing for an archive of its session to be **for**.
    - *paused*: the sandbox this archive would come from has been destroyed,
      and `repo.pause_run` has already retired the token it would be written
      with (#48). The save that matters on this path is the one at **each step
      boundary**, which exists precisely because a pause gives no warning --
      so by here the session is already in the store as of the last boundary,
      and the only thing a second attempt could add is the exploration of the
      step the pause interrupted, which the pause cost by definition.

    Checked rather than attempted-and-swallowed so that a run ending normally
    does not log a failure every time.

    **Through `run_status`, which is exempt from the token's liveness gate.**
    The obvious read, `run_state()`, is not: it goes through `authorized_run`
    and raises `RunNotLive` for exactly the runs this guard exists to skip, so
    the guard against logging a failure logged one -- with a traceback -- on
    the way out of every run that succeeded. `run_status` is the first of the
    three operations app/control/service.py exempts, and the reason it gives is
    this one: a read of one field, made after the run has ended.
    """
    try:
        # Re-parsed from a string because the gateway seam is JSON: the HTTP
        # transport can only carry the value, so the enum is rebuilt on this
        # side rather than the two transports disagreeing about the wire.
        if RunStatus(control.run_status()) is not RunStatus.RUNNING:
            return
        agent_session.save(control, run_key, GatewayStorage(control), emit=emit)
    except Exception:  # pragma: no cover - never lose a run over its session
        log.warning("could not persist the session of run %s", run_key, exc_info=True)


def _record_cost(control: RunGateway, runner: Runner, started: float) -> None:
    """What the run spent of money and sandbox time, on the row.

    In a `finally`, so every path through the composition records it -- success,
    failure, pause and stop alike. A sandbox killed outright records nothing,
    which is the case the lease reaper reconciles and the one case where "what
    did it cost?" has no answer worth inventing.

    This is one of the two operations deliberately exempt from the token's
    liveness gate (app/control/service.py), because it is recorded *about* a run
    that has just ended and would otherwise be refused on every successful run.

    Never allowed to fail the run: accounting is not the work.
    """
    try:
        control.record_cost(
            spend_usd=float(getattr(runner, "spent_usd", 0.0) or 0.0),
            sandbox_seconds=int(time.monotonic() - started),
        )
    except Exception:  # pragma: no cover - never lose a run over a cost column
        log.warning("could not record the cost of run %s", control.scope.run_id, exc_info=True)


def launch_run(run_id: int) -> None:
    """Start the pipeline for run_id on a daemon thread.

    The thread call site. `QA_SANDBOX=thread` selects it (app/sandbox/dispatch.py);
    it keeps CI fast and token-free and it is what lets the existing suite prove
    the behaviour did not move when the work did.

    **The gateway is built here, not on the thread.** Minting a token reads the
    run, and that read is tenant-filtered: this function runs on the request
    thread, where `require_auth` has made the run's own tenant the acting one,
    and the daemon thread it starts has no request and therefore no acting
    tenant. Building it the other side of `Thread(...)` would mint nothing and
    fail every run. A test says so, because the failure would otherwise be a
    puzzling `NotFound` from inside a thread.
    """
    control = factory.local_for_run(run_id)
    threading.Thread(
        target=drive_run, args=(control,), name=f"run-{run_id}", daemon=True
    ).start()
