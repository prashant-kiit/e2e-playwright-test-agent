"""How a run starts working: one protocol, one factory, no new injection point.

`get_launcher` -- the FastAPI dependency returning `Callable[[int], None]`, and
already the point tests override to a no-op -- stays the **only** injection point
for "a run starts working" (DESIGN.md §13). What P4 adds behind it is a choice of
implementation, read from the environment exactly as `make_runner` reads which
Runner to build:

    QA_SANDBOX=docker   dispatch a container per run   (the compose stack)
    QA_SANDBOX=thread   today's daemon thread          (tests, CI, development)

and one protocol for the thing that does the dispatching:

    dispatch(run_id) -> handle      an opaque string, recorded on the run row
    destroy(handle)  -> None        idempotent; the stop and pause paths use it

The handle is opaque on purpose. A Docker container id, a K8s job name and a
Fargate task ARN are all strings the API should record and hand back rather than
parse, and a scheduler the control plane has to understand is a scheduler the
control plane is coupled to. It is recorded on the run so an SRE can find the
sandbox behind a live run and the stop path has something to kill.

K8s and Fargate are the reason this seam exists, not its contents. What ships is
`DockerScheduler` (app/sandbox/docker.py) and the recording fake below.

**A dispatch failure is a platform failure, reported as one.** A missing image,
an unreachable daemon or a refused quota ends the run `failed` with that reason
and frees the app lock, so a broken platform is never reported as a broken run
and never leaves a target held by something that never started.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from .. import config, repo
from ..db import SessionLocal
from ..launcher import launch_run
from ..orchestrator.driver import SessionFactory

log = logging.getLogger(__name__)

# What `get_launcher` returns: "start working on this run".
Launcher = Callable[[int], None]

THREAD = "thread"
DOCKER = "docker"
KINDS = (THREAD, DOCKER)


@runtime_checkable
class Scheduler(Protocol):
    """Somewhere a sandbox can be started and stopped."""

    def dispatch(self, run_id: int) -> str:
        """Start a sandbox for this run. Returns an opaque handle.

        Raises if the sandbox could not be started, and the caller turns that
        into a failed run rather than a retry: capacity, images and daemons are
        not things a second immediate attempt fixes.
        """

    def destroy(self, handle: str) -> None:
        """Stop and remove the sandbox `handle` names, if it is still there.

        Idempotent: pause, stop and the reaper may all reach for the same
        handle, and a sandbox that already exited is the outcome they wanted.
        """


class RecordingScheduler:
    """The seam's test double: records what it was asked to do.

    It lives beside the protocol rather than in the test tree for the reason
    `tests/storage_helpers.py` exists -- three copies of a protocol double is
    three places to forget a method -- and because this is the one substitution
    the whole phase's tests are allowed to make.
    """

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.dispatched: list[int] = []
        self.destroyed: list[str] = []
        self.handles: list[str] = []
        self._fail_with = fail_with
        self._ids = itertools.count(1)

    def dispatch(self, run_id: int) -> str:
        if self._fail_with is not None:
            raise self._fail_with
        self.dispatched.append(run_id)
        handle = f"recording-sandbox-{next(self._ids)}"
        self.handles.append(handle)
        return handle

    def destroy(self, handle: str) -> None:
        self.destroyed.append(handle)


def make_scheduler() -> Scheduler | None:
    """The scheduler this process should use, or None on the thread path.

    None rather than a raise, because "there is no sandbox to schedule" is the
    truth about a thread run and the paths that reap a sandbox have to be able
    to ask without handling an exception. An unknown kind still raises: a typo
    in `QA_SANDBOX` must not quietly run the agent in the API process.
    """
    kind = config.sandbox_kind()
    if kind == THREAD:
        return None
    if kind == DOCKER:
        from .docker import DockerScheduler

        return DockerScheduler()
    raise ValueError(f"QA_SANDBOX={kind!r} is not one of {KINDS}")


def dispatching_launcher(
    scheduler: Scheduler, *, session_factory: SessionFactory = SessionLocal
) -> Launcher:
    """A launcher that starts a sandbox and records its handle.

    The run row is already written and the lock already held when this is
    called, so the only two outcomes are "a sandbox is working on it" and "the
    run failed and the target is free". There is deliberately no third: a
    pending run with no sandbox is the state an operator cannot act on.

    Nothing is published to the log bus here. There is one writer per run and it
    is the sandbox; a run that never got one has its reason on the row, where
    the portal already shows it, and its stream ends at once because the run is
    terminal.
    """

    def launch(run_id: int) -> None:
        try:
            handle = scheduler.dispatch(run_id)
        except Exception as exc:
            log.exception("dispatching a sandbox for run %s failed", run_id)
            with session_factory() as session:
                repo.fail_run(session, run_id, f"sandbox dispatch failed: {exc}")
            return
        with session_factory() as session:
            repo.set_sandbox_handle(session, run_id, handle)

    return launch


def make_launcher() -> Launcher:
    """What `get_launcher` returns, chosen by `QA_SANDBOX`.

    An unknown value raises rather than falling back to the thread: the fallback
    would run an agent inside the API process on a typo, which is the one thing
    this phase exists to make impossible.
    """
    if config.sandbox_kind() == THREAD:
        return launch_run
    scheduler = make_scheduler()
    assert scheduler is not None  # only THREAD has none, and it returned above
    return dispatching_launcher(scheduler)


def destroy_handle(handle: str, scheduler: Scheduler | None = None) -> bool:
    """Reap one sandbox by its handle. Returns whether the reap went through.

    Tolerant by design: a sandbox that already exited, a handle belonging to a
    scheduler that is no longer configured, and the thread path's absence of one
    are all "nothing left to reap" rather than errors to report to an operator
    who asked for the work to stop.
    """
    if not handle:
        return False
    if scheduler is None:
        try:
            scheduler = make_scheduler()
        except Exception:
            log.warning("no scheduler configured to destroy %s", handle)
            return False
    if scheduler is None:
        return False  # the thread path: there was never a sandbox to reap
    try:
        scheduler.destroy(handle)
    except Exception:  # pragma: no cover - a failed reap must not fail the ask
        log.warning("destroying sandbox %s failed", handle, exc_info=True)
        return False
    return True


def destroy_sandbox(
    run_id: int,
    scheduler: Scheduler | None = None,
    *,
    session_factory: SessionFactory = SessionLocal,
) -> bool:
    """Reap the sandbox behind a run id. What the reaper is handed.

    A run id rather than a handle, because the reaper knows which runs it
    failed and not what was executing them.
    """
    with session_factory() as session:
        handle = repo.get_run(session, run_id).sandbox_handle
    return destroy_handle(handle or "", scheduler)
