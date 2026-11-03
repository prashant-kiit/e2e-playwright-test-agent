"""The pipeline driver: runs steps in order, one at a time, checkpointing after
each so a run can resume at a step boundary.

It is deliberately synchronous and talks to the control plane through one
gateway (app/control/gateway.py). Each operation is its own short transaction on
the other side, which keeps the lease fresh and avoids holding a transaction open
across a long-running step.

**P5-05 replaced `session_factory` with `control`.** The driver used to take a
SQLAlchemy session factory and call `repo` functions itself; a run in a sandbox
has no database to open a session against any more, so it is handed a gateway
that performs those operations through the internal control-plane API instead.
The shape did not change: still one object in, still exactly one step-boundary
callable (DESIGN.md §13), and `LocalGateway` makes the thread path the same code.

What the rename bought, beyond removing the credential: the operations this
module performs are now a readable list -- `begin_run`, `start_step`,
`complete_step`, `fail_run` and four more -- rather than ninety `repo` functions
of which it happens to use eight.
"""

from __future__ import annotations

from collections.abc import Callable

from .. import config
from ..control.gateway import RunGateway
from ..domain.steps import STEP_ORDER, resume_step, step_index
from .runner import Emit, Runner, StepContext


def run_pipeline(
    control: RunGateway,
    run_id: int,
    runner: Runner,
    emit: Emit | None = None,
    collect: Callable[[int, object], None] | None = None,
) -> None:
    """`collect` is the driver's ONE step-boundary hook, fired after each
    completed step. Artifact collection and ingest are composed into it by the
    launcher, which decides which of them may fail a run.

    Keep it single (DESIGN.md §13). Work that needs to happen at a step boundary
    -- uploading blobs and committing revision N+1 -- is composed into this
    callable by the caller, not added as a second parameter. Hydrate and
    teardown run in the launcher *around* this function for the same reason.

    `run_id` is also on `control.scope`, and it is still a parameter because it
    is what `emit` and `collect` are given: the two are checked against each
    other below rather than one being derived from the other, so a gateway built
    for the wrong run fails here instead of driving the wrong row.
    """
    emit = emit or (lambda line: None)
    collect = collect or (lambda run_id, step: None)

    if control.scope.run_id != run_id:
        raise ValueError(
            f"the gateway is scoped to run {control.scope.run_id}, not {run_id}"
        )

    # The run's immutable facts and resume point, in one read. The fields that
    # change under a running run are read again at each boundary (`run_state`).
    facts = control.run_facts()
    run_key, app, story_id, mode = facts.run_key, facts.app, facts.story_id, facts.mode
    # Read once, here, where the run's other immutable facts are read: a Runner
    # must not need a session, least of all a sandboxed one -- and after P5-05
    # there is no session in a sandbox to need.
    target_cfg = facts.target
    # The prompt versions this run was pinned to at `repo.start_run`, read in
    # the same one call for the same reason: a Runner must not need a session,
    # and the pinning is what makes them immutable facts of the run rather than
    # something to look up per step (P5-06).
    prompts = facts.prompts

    start = resume_step(facts.last_completed_step)
    rd = config.run_dir(run_key)
    # The worktree the launcher hydrated, named by the same function it used.
    # Derived rather than passed in, so the driver keeps exactly one injected
    # callable (DESIGN.md §13) and the two cannot disagree about the path.
    worktree = config.worktree_dir(run_key)

    if start is None:  # every step already done; just finalize
        control.complete_run()
        emit(f"=== run {run_key} already complete ===")
        return

    control.begin_run()
    emit(f"=== run {run_key} started (begin at {start.value}) ===")

    for step in STEP_ORDER[step_index(start):]:
        # Honour pause/stop requests at the step boundary (step-level granularity).
        state = control.run_state()
        if state.stop_requested:
            control.stop_run()
            emit(f"=== run {run_key} stopped ===")
            return
        if state.pause_requested:
            control.pause_run()
            emit(f"=== run {run_key} paused (resume to continue at {step.value}) ===")
            return

        emit(f"=== step: {step.value} ===")
        control.start_step(step)
        # Taken from the boundary read above rather than re-read after
        # `start_step`: nothing between the two writes the session id, and on
        # the container path every read is a round trip.
        prev_sid = state.claude_session_id

        ctx = StepContext(
            run_id=run_id,
            run_key=run_key,
            app=app,
            story_id=story_id,
            mode=mode,
            step=step,
            run_dir=rd,
            worktree=worktree,
            target=target_cfg,
            prev_session_id=prev_sid,
            prompts=prompts,
        )

        try:
            result = runner.run_step(ctx, emit)
        except Exception as exc:  # a runner blew up; fail the run, free the app
            control.fail_step(step)
            control.fail_run(f"{step.value} crashed: {exc}")
            emit(f"=== step {step.value} crashed: {exc} ===")
            return

        if result.session_id:
            control.set_session_id(result.session_id)

        if not result.ok:
            control.fail_step(step)
            control.fail_run(result.error or f"{step.value} failed")
            emit(f"=== step {step.value} FAILED: {result.error} ===")
            return

        control.complete_step(step)

        # The step-boundary hook is NOT best-effort. Its ingest half is what
        # records the step's work, so a hook that raises means the work was
        # dropped -- and a run that reports success having dropped its work is
        # the failure mode P3 exists to make impossible. It therefore fails the
        # step and the run exactly as a crashed runner does, freeing the lock
        # and recording the reason. (P2 swallowed this, correctly, while `apps/`
        # was authoritative; that is the behaviour P3 inverts.)
        try:
            collect(run_id, step)
        except Exception as exc:
            control.fail_step(step)
            control.fail_run(f"{step.value} step boundary failed: {exc}")
            emit(f"=== step {step.value}: step boundary FAILED: {exc} ===")
            return
        emit(f"=== step {step.value} done ===")

    control.complete_run()
    emit(f"=== run {run_key} completed ===")
