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
there (app/sandbox/env.py): `DATABASE_URL`, the `S3_*` credentials hydrate and
ingest need, `ANTHROPIC_API_KEY`, the scratch paths and the runner kind. Never a
GitHub credential, never a portal credential, and no mounted repo.

**The exit code is read off the run row, not inferred.** A run that ends
`failed` for any reason -- a hydrate that could not build a tree, a step that
crashed, an ingest that dropped its work -- exits non-zero, so the scheduler and
an operator reading `docker ps -a` agree with the database about what happened.
"""

from __future__ import annotations

import logging
import sys

from .. import repo
from ..db import SessionLocal
from ..domain.status import RunStatus
from ..launcher import drive_run
from ..orchestrator.bus import LogBus
from ..orchestrator.driver import SessionFactory
from ..orchestrator.runner import Runner
from ..storage import Storage

USAGE = "usage: python -m app.sandbox.run <run_id>"

EXIT_OK = 0
EXIT_RUN_FAILED = 1
EXIT_USAGE = 2


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner | None = None,
    log: LogBus | None = None,
    session_factory: SessionFactory = SessionLocal,
    store: Storage | None = None,
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
    drive_run(
        run_id,
        runner=runner,
        log=log,
        session_factory=session_factory,
        store=store,
    )

    with session_factory() as session:
        status = repo.get_run(session, run_id).status
    return EXIT_RUN_FAILED if status is RunStatus.FAILED else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
