"""The limits around a run: a step's wall clock, a run's wall clock, a budget.

Without these a wedged agent is unbounded. A Claude session that opens a browser
and hangs holds a browser and a billing meter until somebody notices, and the
lease reaper only frees the *lock* -- the work keeps going. §6 calls the
wall-clock timeout the most expensive failure mode in the system.

    per-step wall clock   here, around whatever the inner Runner starts
    per-run wall clock    here at a step boundary, and in the reaper for a run
                          nobody is driving any more (app/reaper.py)
    per-run spend         here, from the `result` events the runner already parses

**Where the run's deadline really bites is the reaper**, and that is deliberate.
The check here is cheap and early -- it refuses to start another step -- but a
run wedged *inside* a step would otherwise outlive its deadline by the whole
step timeout. So the reaper's overdue sweep both fails the row and destroys the
sandbox (`reap_sandbox` over `reaped + overdue + idle`), which bounds the
overrun by one reap interval rather than by one step, and bounds it in the place
that costs money rather than in the one that keeps the status tidy.

**A wrapper around a Runner, not a change to the driver.** The driver keeps
exactly one injected step-boundary callable (DESIGN.md §13) and knows nothing
about limits: a breach is an ordinary failed step, so the driver fails the step
and the run, frees the lock and records the reason through the paths it already
has. That is also what makes every breach leave the **last committed revision
intact** -- invariant 4, unchanged, for free.

The kill is the inner runner's, through an optional `abort()`: this module knows
when patience has run out, and only `ClaudeRunner` knows that what it started is
a process group with a browser in it. A Runner without `abort` is still subject
to the limit; its step is abandoned rather than killed, which is why the worker
is a daemon thread -- an abandoned step must not be able to keep a container
alive after the run that owned it has failed.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol

from .. import config
from .runner import Emit, Runner, StepContext, StepResult


@dataclass(frozen=True)
class RunLimits:
    """What one run may spend of time and money.

    Defaults are deliberately generous (config.py says why): the failure mode
    being bounded is an agent wedged for hours, and a limit that interrupts
    healthy work is a limit an operator turns off.
    """

    step_timeout_s: float = config.DEFAULT_STEP_TIMEOUT_S
    run_timeout_s: float = config.DEFAULT_RUN_TIMEOUT_S
    spend_budget_usd: float = config.DEFAULT_SPEND_BUDGET_USD

    @classmethod
    def from_env(cls) -> RunLimits:
        return cls(
            step_timeout_s=config.step_timeout_s(),
            run_timeout_s=config.run_timeout_s(),
            spend_budget_usd=config.spend_budget_usd(),
        )


class Abortable(Protocol):
    """A Runner that can kill what it started."""

    def abort(self) -> None: ...


class LimitedRunner:
    """A Runner with the three limits around it.

    `spent_usd` and `elapsed_s` are read back by the launcher at the end of a
    run and recorded on the row, so cost is attributable per run before
    per-tenant quotas exist (P5's).
    """

    def __init__(
        self,
        inner: Runner,
        limits: RunLimits | None = None,
        *,
        started_at: float | None = None,
        clock=time.monotonic,
    ) -> None:
        self.inner = inner
        self.limits = limits or RunLimits.from_env()
        self._clock = clock
        self._started_at = started_at if started_at is not None else clock()
        self.spent_usd = 0.0

    @property
    def elapsed_s(self) -> float:
        return self._clock() - self._started_at

    def run_step(self, ctx: StepContext, emit: Emit) -> StepResult:
        """Run one step, or refuse to, or give up on it.

        Checked before the step rather than during it: a run past its deadline
        or its budget must not start a sixth step, and interrupting one already
        in flight would throw away work that is about to be committed for no
        gain -- the step boundary is close by definition.
        """
        if self.elapsed_s >= self.limits.run_timeout_s:
            return self._breach(
                emit,
                f"run timed out after {self.elapsed_s:.0f}s "
                f"(limit {self.limits.run_timeout_s:.0f}s)",
            )
        if self.spent_usd >= self.limits.spend_budget_usd:
            return self._breach(
                emit,
                f"spend budget exhausted: ${self.spent_usd:.2f} of "
                f"${self.limits.spend_budget_usd:.2f}",
            )

        result = self._with_step_timeout(ctx, emit)
        self.spent_usd += _cost_of(self.inner)
        if not result.ok:
            return result

        if self.spent_usd > self.limits.spend_budget_usd:
            # The step that crossed the line is the one that fails, so the run
            # ends on the work that caused it rather than one step later.
            return self._breach(
                emit,
                f"spend budget exceeded: ${self.spent_usd:.2f} of "
                f"${self.limits.spend_budget_usd:.2f}",
                session_id=result.session_id,
            )
        return result

    def _with_step_timeout(self, ctx: StepContext, emit: Emit) -> StepResult:
        done = threading.Event()
        box: dict[str, object] = {}

        def work() -> None:
            try:
                box["result"] = self.inner.run_step(ctx, emit)
            except BaseException as exc:  # re-raised on the caller's thread
                box["error"] = exc
            finally:
                done.set()

        # Daemon: a step we have given up on must not hold the process open.
        thread = threading.Thread(
            target=work, name=f"step-{ctx.step.value}-{ctx.run_key}", daemon=True
        )
        thread.start()
        if not done.wait(self.limits.step_timeout_s):
            abort = getattr(self.inner, "abort", None)
            if callable(abort):
                abort()  # kill the process group; a browser does not stop politely
            return self._breach(
                emit,
                f"step {ctx.step.value} timed out after "
                f"{self.limits.step_timeout_s:.0f}s",
            )
        if "error" in box:
            raise box["error"]  # type: ignore[misc]
        return box["result"]  # type: ignore[return-value]

    def _breach(
        self, emit: Emit, reason: str, *, session_id: str | None = None
    ) -> StepResult:
        """Name the breach in the log as well as on the result.

        Both, because an operator has to be able to tell "wedged" from "failed"
        without reading a trace: the run's error says it and the stream they are
        already watching says it.
        """
        emit(f"=== limit reached: {reason} ===")
        return StepResult(ok=False, session_id=session_id, error=reason)


def _cost_of(runner: object) -> float:
    """What the inner runner reported for its last step, if it reports costs.

    `ClaudeRunner` already parses the `result` event that carries
    `total_cost_usd`, which is why this is a budget rather than a new accounting
    system. A runner that reports nothing spends nothing, which is true of the
    fake one.
    """
    try:
        return float(getattr(runner, "last_cost_usd", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
