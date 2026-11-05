"""CLI for artifact maintenance: python -m app.artifacts rekey

One command, and it exists because P5-10 (#42) changed where artifacts live:
`tenant/<id>/runs/<run_key>/<path>` instead of `<run_key>/<path>`, so that a
tenant's whole storage is one prefix an operator can list and story 32's purge
can delete. New uploads already use the new shape; this moves the old ones.

Why it is not an Alembic revision is in `rekey.py`: the rows are in Postgres
and the bytes are in an object store, and a revision that rewrote the keys
without moving the bytes would point every existing row at nothing.

Exit codes follow `python -m app.delivery` and `python -m app.accounts`: 0 if
the pass completed, 2 if any row failed. A pass that moved nothing because
everything was already migrated is a success, and says so.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .. import storage
from .rekey import rekey_all

EXIT_OK = 0
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.artifacts",
        description="Maintenance for stored run artifacts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "rekey",
        help=(
            "move artifact objects written before P5-10 under their tenant's "
            "prefix; safe to re-run and safe to interrupt"
        ),
    )
    return parser


def main(argv: list[str] | None = None, *, store=None, session_factory=None) -> int:
    """`store` and `session_factory` are injected by the tests.

    Keywords rather than module-level globals for the reason the delivery CLI
    keeps its seams explicit: the suite's two guards (tests/conftest.py) exist
    precisely to stop a test reaching a real S3 client or the *developer's*
    database by accident, and a command that resolved both from the
    environment unconditionally would be a way round them. Both default to
    None so the production invocation takes no arguments at all.
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.command == "rekey":
        return _rekey(
            store if store is not None else storage.from_env(),
            session_factory=session_factory,
        )
    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


def _rekey(store, *, session_factory=None) -> int:
    outcome = rekey_all(store, session_factory=session_factory)
    print(f"rekey: {outcome}")
    if outcome.missing:
        print(
            f"note: {outcome.missing} row(s) name bytes that are not in the "
            f"store and were left alone. 'Blob before row' means this should "
            f"be zero; the rows are listed in the log above.",
            file=sys.stderr,
        )
    if outcome.failed:
        print(
            f"error: {outcome.failed} row(s) could not be moved. The pass is "
            f"safe to re-run and will skip what already moved.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())
