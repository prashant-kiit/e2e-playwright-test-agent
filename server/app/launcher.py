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
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from . import config, repo, revisions, storage
from .artifacts import ArtifactCollector
from .db import SessionLocal
from .domain.steps import Step
from .orchestrator.bus import LogBus, bus_from_env
from .orchestrator.claude import ClaudeRunner
from .orchestrator.driver import SessionFactory, run_pipeline
from .orchestrator.fake import FakeRunner
from .orchestrator.runner import Emit, Runner
from .reaper import heartbeat_during
from .sandbox import hydrate
from .storage import Storage
from .target_config import config_of

# A step-boundary half: it is handed the run and the step that just completed.
# One of the two may raise, and that is deliberate -- see make_step_boundary_hook.
BoundaryHalf = Callable[[int, Step], None]


def make_runner() -> Runner:
    if config.runner_kind() == "fake":
        return FakeRunner(delay=config.fake_delay())
    return ClaudeRunner()


def make_collector(
    *, session_factory: SessionFactory = SessionLocal, store: Storage | None = None
) -> BoundaryHalf:
    """A collect(run_id, step) callback that sweeps the run dir into storage."""
    collector = ArtifactCollector(store or storage.from_env())

    def collect(run_id: int, step: Step) -> None:
        with session_factory() as s:
            run = repo.get_run(s, run_id)
            collector.collect(s, run, config.run_dir(run.run_key), step)

    return collect


def make_ingest(
    *, session_factory: SessionFactory = SessionLocal, store: Storage | None = None
) -> BoundaryHalf:
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

    Raises on failure, and the caller does not catch it. See
    make_step_boundary_hook.
    """
    store = store or storage.from_env()

    def ingest(run_id: int, step: Step) -> None:
        with session_factory() as s:
            run = repo.get_run(s, run_id)
            root = config.worktree_dir(run.run_key)
            hydrate.render_generated(root, config_of(run.target))
            revisions.commit_revision(
                s,
                run.target,
                store,
                root,
                # Fits Revision.author's 100 chars: run_key is at most 80.
                author=f"run:{run.run_key}",
                produced_by_run_id=run.id,
            )

    return ingest


def make_step_boundary_hook(
    emit: Emit,
    *,
    session_factory: SessionFactory = SessionLocal,
    store: Storage | None = None,
    collect: BoundaryHalf | None = None,
    ingest: BoundaryHalf | None = None,
) -> BoundaryHalf:
    """The driver's ONE step-boundary callable, with both halves composed in.

    Order is deliberate: **artifacts first, then ingest.** Evidence collection
    runs first and is never delayed by the work that matters more.

    The two halves are treated differently, and the asymmetry is the phase:

    - **Artifact collection stays best-effort.** Its failure is reported to the
      run's log and swallowed. Evidence is not the work; losing a trace is not a
      reason to fail a run that produced a healed suite.
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
    # Both halves talk to the same object store, so build the client once
    # rather than once per half.
    if store is None and (collect is None or ingest is None):
        store = storage.from_env()

    collect_half = (
        collect if collect is not None
        else make_collector(session_factory=session_factory, store=store)
    )
    ingest_half = (
        ingest if ingest is not None
        else make_ingest(session_factory=session_factory, store=store)
    )

    def on_step_boundary(run_id: int, step: Step) -> None:
        try:
            collect_half(run_id, step)
        except Exception as exc:
            emit(f"=== step {step.value}: artifact collection failed: {exc} ===")

        try:
            ingest_half(run_id, step)
        except Exception as exc:
            # Reported *and* propagated: the run fails, and the operator reading
            # the log does not have to infer the reason from a status.
            emit(f"=== step {step.value}: ingest failed: {exc} ===")
            raise

    return on_step_boundary


def hydrate_worktree(
    run_id: int,
    emit: Emit,
    *,
    session_factory: SessionFactory = SessionLocal,
    store: Storage | None = None,
) -> Path:
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
    store = store or storage.from_env()
    with session_factory() as s:
        run = repo.get_run(s, run_id)
        dest = config.worktree_dir(run.run_key)
        # A worktree left behind by a crashed previous attempt at this run_key is
        # not a tree to inherit: hydrate is the only author of this directory.
        hydrate.teardown(dest)
        hydrate.hydrate(s, run.target, store, dest, emit=emit)
    return dest


def run_with_worktree(
    run_id: int,
    emit: Emit,
    runner: Runner,
    *,
    session_factory: SessionFactory = SessionLocal,
    store: Storage | None = None,
    collect: BoundaryHalf | None = None,
) -> None:
    """Hydrate, drive the pipeline in that worktree, then tear it down.

    The composition the whole phase turns on, and it is deliberately boring:
    three function calls and a `finally`. Teardown runs at every terminal state
    and on pause, so disk use is bounded by live runs rather than by history; a
    resumed run comes back through here and re-hydrates from the head.
    """
    store = store or storage.from_env()
    try:
        worktree = hydrate_worktree(
            run_id, emit, session_factory=session_factory, store=store
        )
    except Exception as exc:
        # No tree, so no step may be attempted. Fail the run and free the app.
        with session_factory() as s:
            repo.fail_run(s, run_id, f"hydrate failed: {exc}")
        emit(f"=== run failed before it started: {exc} ===")
        return

    hook = make_step_boundary_hook(
        emit, session_factory=session_factory, store=store, collect=collect
    )
    try:
        run_pipeline(session_factory, run_id, runner, emit=emit, collect=hook)
    finally:
        hydrate.teardown(worktree)
        emit("=== teardown: worktree removed ===")


def drive_run(
    run_id: int,
    *,
    runner: Runner | None = None,
    log: LogBus | None = None,
    session_factory: SessionFactory = SessionLocal,
    store: Storage | None = None,
) -> None:
    """Work the run: heartbeat, runner, the composition, close the stream.

    The one function both call sites use. Its keyword arguments are the three
    things a container gets from its environment -- a bus, a database and an
    object store -- passed in rather than read from `env` so that the entrypoint
    is testable without a container, exactly as `run_with_worktree` already
    allows.

    The heartbeat is taken **here**, inside whichever process does the work, so
    the reaper's crash detection measures the thing that is actually working
    rather than a thread in a process that may be fine while the run is not. It
    wraps hydrate too: the lease is otherwise refreshed only at step boundaries,
    and `npm ci` on a cold cache outlasts the TTL easily.
    """
    log = log or bus_from_env()
    emit = log.emitter(run_id)
    try:
        with heartbeat_during(run_id, session_factory=session_factory):
            run_with_worktree(
                run_id,
                emit,
                runner or make_runner(),
                session_factory=session_factory,
                store=store,
            )
    finally:
        log.close(run_id)


def launch_run(run_id: int) -> None:
    """Start the pipeline for run_id on a daemon thread.

    The thread call site. `QA_SANDBOX=thread` selects it (app/sandbox/dispatch.py);
    it keeps CI fast and token-free and it is what lets the existing suite prove
    the behaviour did not move when the work did.
    """
    threading.Thread(
        target=drive_run, args=(run_id,), name=f"run-{run_id}", daemon=True
    ).start()
