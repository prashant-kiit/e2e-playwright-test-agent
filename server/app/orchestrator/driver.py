"""The pipeline driver: runs steps in order, one at a time, checkpointing after
each so a run can resume at a step boundary.

It is deliberately synchronous and takes a session *factory* (not a session):
each DB touch is a short transaction, which keeps the lease fresh and avoids
holding a transaction open across a long-running step. The API runs it on a
background thread (M2 wiring); tests call it directly with a FakeRunner.
"""

from __future__ import annotations

from collections.abc import Callable

from .. import config, repo
from ..domain.steps import STEP_ORDER, resume_step, step_index
from .runner import Emit, Runner, StepContext

SessionFactory = Callable[[], "object"]  # a callable returning a SQLAlchemy Session


def run_pipeline(
    session_factory: SessionFactory,
    run_id: int,
    runner: Runner,
    emit: Emit | None = None,
    collect: Callable[[int, object], None] | None = None,
) -> None:
    """`collect` is the driver's ONE step-boundary hook, fired after each
    completed step. Artifact collection is composed into it by the launcher.

    Keep it single (DESIGN.md §13). Work that needs to happen at a step boundary
    -- P2's sync-out, uploading blobs and committing a revision -- is composed
    into this callable by the caller, not added as a second parameter.
    """
    emit = emit or (lambda line: None)
    collect = collect or (lambda run_id, step: None)

    # Read the run's immutable facts and resume point.
    with session_factory() as s:
        run = repo.get_run(s, run_id)
        run_key, app, story_id, mode = run.run_key, run.target.app, run.story_id, run.mode
        last_completed = run.last_completed_step

    start = resume_step(last_completed)
    rd = config.run_dir(run_key)

    if start is None:  # every step already done; just finalize
        with session_factory() as s:
            repo.complete_run(s, run_id)
        emit(f"=== run {run_key} already complete ===")
        return

    with session_factory() as s:
        repo.begin_run(s, run_id)
    emit(f"=== run {run_key} started (begin at {start.value}) ===")

    for step in STEP_ORDER[step_index(start):]:
        # Honour pause/stop requests at the step boundary (step-level granularity).
        with session_factory() as s:
            run = repo.get_run(s, run_id)
            if run.stop_requested:
                repo.stop_run(s, run_id)
                emit(f"=== run {run_key} stopped ===")
                return
            if run.pause_requested:
                repo.pause_run(s, run_id)
                emit(f"=== run {run_key} paused (resume to continue at {step.value}) ===")
                return

        emit(f"=== step: {step.value} ===")
        with session_factory() as s:
            repo.start_step(s, run_id, step)
            prev_sid = repo.get_run(s, run_id).claude_session_id

        ctx = StepContext(
            run_id=run_id,
            run_key=run_key,
            app=app,
            story_id=story_id,
            mode=mode,
            step=step,
            run_dir=rd,
            prev_session_id=prev_sid,
        )

        try:
            result = runner.run_step(ctx, emit)
        except Exception as exc:  # a runner blew up; fail the run, free the app
            with session_factory() as s:
                repo.fail_step(s, run_id, step)
                repo.fail_run(s, run_id, f"{step.value} crashed: {exc}")
            emit(f"=== step {step.value} crashed: {exc} ===")
            return

        if result.session_id:
            with session_factory() as s:
                repo.set_session_id(s, run_id, result.session_id)

        if not result.ok:
            with session_factory() as s:
                repo.fail_step(s, run_id, step)
                repo.fail_run(s, run_id, result.error or f"{step.value} failed")
            emit(f"=== step {step.value} FAILED: {result.error} ===")
            return

        with session_factory() as s:
            repo.complete_step(s, run_id, step)
        try:  # artifact collection is best-effort; never fail the run on it
            collect(run_id, step)
        except Exception as exc:
            emit(f"=== step {step.value}: artifact collection failed: {exc} ===")
        emit(f"=== step {step.value} done ===")

    with session_factory() as s:
        repo.complete_run(s, run_id)
    emit(f"=== run {run_key} completed ===")
