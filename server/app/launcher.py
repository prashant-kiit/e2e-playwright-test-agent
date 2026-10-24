"""Launches the orchestrator for a run on a background thread.

Kept separate from the API so tests can override it with a no-op (they drive the
driver directly with a FakeRunner). The real launcher picks the configured
runner, streams log lines to the bus, and closes the stream when the run ends.

It is also where everything that happens *around* a run is composed: the
baseline revision before the pipeline starts, and the step-boundary hook the
driver fires after each completed step. The driver keeps exactly one injection
point (DESIGN.md §13) and this module is what composes into it -- which is also
where P4's hydrate will go.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from . import config, monorepo, repo, revisions, storage
from .artifacts import ArtifactCollector
from .db import SessionLocal
from .domain.steps import Step
from .orchestrator.bus import bus
from .orchestrator.claude import ClaudeRunner
from .orchestrator.driver import SessionFactory, run_pipeline
from .orchestrator.fake import FakeRunner
from .orchestrator.runner import Emit, Runner
from .reaper import heartbeat_during
from .storage import Storage

# A step-boundary half: it is handed the run and the step that just completed.
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


def make_sync_out(
    *, session_factory: SessionFactory = SessionLocal, store: Storage | None = None
) -> BoundaryHalf:
    """A sync_out(run_id, step) callback that commits a revision of the tree.

    P2's dual-write: upload the tracked tree's blobs, then commit one revision
    naming them. A step that changed no tracked file commits nothing.
    """
    store = store or storage.from_env()

    def sync_out(run_id: int, step: Step) -> None:
        with session_factory() as s:
            run = repo.get_run(s, run_id)
            # Staged while apps/ is still the tree the run works in; P3-03
            # replaces this with the run's own hydrated worktree.
            with monorepo.staged_tree(run.target.app) as root:
                revisions.commit_revision(
                    s,
                    run.target,
                    store,
                    root,
                    # Fits Revision.author's 100 chars: run_key is at most 80.
                    author=f"run:{run.run_key}",
                    produced_by_run_id=run.id,
                )

    return sync_out


def make_step_boundary_hook(
    emit: Emit,
    *,
    session_factory: SessionFactory = SessionLocal,
    store: Storage | None = None,
    collect: BoundaryHalf | None = None,
    sync_out: BoundaryHalf | None = None,
) -> BoundaryHalf:
    """The driver's ONE step-boundary callable, with both halves composed in.

    Order is deliberate: **artifacts first, then the revision snapshot.** The
    existing behavior runs first and is never delayed by the new work.

    Each half catches its own failures. The driver wraps the whole callable in a
    single best-effort try/except, so without per-half isolation an exception
    from artifact collection would skip the revision commit entirely -- and vice
    versa. Both failures are reported to the run's log stream instead.

    **A failed revision write must never fail a run in P2.** While `apps/` is
    authoritative, the driver's best-effort treatment of this hook is exactly
    right, and it is what makes the phase's "no behavior change" promise true: a
    total failure of the revision model costs nothing today. P3 inverts this --
    once truth has moved into Postgres, a failed sync-out *has* to fail the run.
    Do not "fix" the swallowed exception before then.
    """
    # Both halves talk to the same object store, so build the client once
    # rather than once per half.
    if store is None and (collect is None or sync_out is None):
        store = storage.from_env()

    halves: tuple[tuple[str, BoundaryHalf], ...] = (
        (
            "artifact collection",
            collect if collect is not None
            else make_collector(session_factory=session_factory, store=store),
        ),
        (
            "revision snapshot",
            sync_out if sync_out is not None
            else make_sync_out(session_factory=session_factory, store=store),
        ),
    )

    def on_step_boundary(run_id: int, step: Step) -> None:
        for name, half in halves:
            try:
                half(run_id, step)
            except Exception as exc:
                emit(f"=== step {step.value}: {name} failed: {exc} ===")

    return on_step_boundary


def ensure_baseline_revision(
    run_id: int,
    emit: Emit,
    *,
    session_factory: SessionFactory = SessionLocal,
    store: Storage | None = None,
) -> None:
    """Give a target with no history a revision of the tree as it stands now.

    Taken **before the pipeline starts**, not at the first sync-out: a snapshot
    taken at the first boundary would conflate the tree the run inherited with
    the tree its first step produced, and revision 1 of every target would be
    unreadable (user story 22). It is not a one-shot backfill script either --
    that is code which runs once and is never exercised again.

    The baseline is the *inherited* tree, so it records no producing run even
    though a run triggered it.

    Best-effort, for the same reason the step-boundary hook is: this is P2
    scaffolding and must not be able to stop a run.
    """
    try:
        with session_factory() as s:
            run = repo.get_run(s, run_id)
            if revisions.head_revision(s, run.target_id) is not None:
                return
            with monorepo.staged_tree(run.target.app) as root:
                committed = revisions.commit_revision(
                    s,
                    run.target,
                    store or storage.from_env(),
                    root,
                    author="baseline",
                )
        if committed is not None:
            emit(
                f"=== baseline revision {committed.rev} recorded "
                f"(the tree this run inherited) ==="
            )
    except Exception as exc:
        emit(f"=== baseline revision failed: {exc} ===")


def launch_run(run_id: int) -> None:
    """Start the pipeline for run_id on a daemon thread."""
    emit = bus.emitter(run_id)
    on_step_boundary = make_step_boundary_hook(emit)

    def _target() -> None:
        try:
            # A target with no history gets its baseline before any step runs.
            ensure_baseline_revision(run_id, emit)
            # The lease is otherwise refreshed only at step boundaries, so a step
            # longer than the TTL would look like a crash to the reaper.
            with heartbeat_during(run_id):
                run_pipeline(
                    SessionLocal, run_id, make_runner(), emit=emit, collect=on_step_boundary
                )
        finally:
            bus.close(run_id)

    threading.Thread(target=_target, name=f"run-{run_id}", daemon=True).start()
