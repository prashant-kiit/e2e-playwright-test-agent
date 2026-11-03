"""The sandbox entrypoint: `python -m app.sandbox.run <run_id>`.

This is the container's command, and it is deliberately thin. It parses a run
id, calls the **one** composition function the thread launcher calls, and turns
the run's outcome into an exit code. Everything that happens around a run --
hydrate, the step-boundary hook, teardown in a `finally` -- lives in
app/launcher.py and is not repeated here, because two pipelines that happen to
agree today are two pipelines that will disagree later. A structural test
asserts that this module composes nothing of its own
(tests/test_sandbox_entrypoint.py).

What the process gets from its environment is what the environment builder put
there (app/sandbox/env.py). After P5-05 that is: a **run-scoped token** and the
URL of the internal control-plane API, `ANTHROPIC_API_KEY`, the scratch paths and
the runner kind. Never `DATABASE_URL`, never the `S3_*` credentials, never a
GitHub credential, never a portal credential, and no mounted repo. The stores are
not reachable from a sandbox at all; everything this process needs from Postgres
and from the blob store it asks the control plane for, as the one run its token
names.

**The run id is on the command line *and* in the token**, and the gateway refuses
a mismatch. Two spellings because the argument is what makes `docker ps` and a
crash log readable, and the token is what makes the request authorized; the
refusal is what stops them ever meaning different things.

**The exit code is read off the run row, not inferred.** A run that ends
`failed` for any reason -- a hydrate that could not build a tree, a step that
crashed, an ingest that dropped its work -- exits non-zero, so the scheduler and
an operator reading `docker ps -a` agree with the database about what happened.
It is the one thing this process asks about a run that has already finished, and
the control plane answers it for exactly that reason.
"""

from __future__ import annotations

import logging
import sys

from ..control import factory
from ..control.gateway import RunGateway
from ..domain.status import RunStatus
from ..launcher import drive_run
from ..orchestrator.bus import GatewayLogBus, LogBus
from ..orchestrator.runner import Runner

USAGE = "usage: python -m app.sandbox.run <run_id>"

EXIT_OK = 0
EXIT_RUN_FAILED = 1
EXIT_USAGE = 2


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner | None = None,
    bus: LogBus | None = None,
    control: RunGateway | None = None,
) -> int:
    """Drive one run to its end. Returns the process's exit code."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    try:
        run_id = int(args[0])
    except ValueError:
        print(f"{USAGE}\nnot a run_id: {args[0]!r}", file=sys.stderr)
        return EXIT_USAGE

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    control = control or factory.from_env()
    if control.scope.run_id != run_id:
        print(
            f"{USAGE}\nthis sandbox's token is for run {control.scope.run_id}, "
            f"not {run_id}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    drive_run(control, runner=runner, bus=bus or GatewayLogBus(control))

    status = control.run_status()
    return EXIT_RUN_FAILED if RunStatus(status) is RunStatus.FAILED else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
