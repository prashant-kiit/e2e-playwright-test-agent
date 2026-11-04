"""CLI for the delivery tools: python -m app.delivery <command>

Replaces scripts/check-bootstrapped.sh, bootstrap-target.sh, push-artifacts.sh
and reset-target.sh. Exit codes match the scripts: `check` exits 1 when a target
is not bootstrapped, and any other failure exits 2.

**These commands write audit rows too** (P5-07, #37). `bootstrap`, `push` and
`reset` each mutate the customer's repo, and the first version of the audit log
covered only the HTTP routes -- so `make deliver` pushed a commit into a
customer's repo and left no trail, which is the exact question #37 exists to
answer. The reviewer that caught it was right that the actor being `system`
here is not a reason to skip the row: "a human at a console did this, and we
cannot say which human" is a far better answer than silence, and it is the
honest one while the CLI binds no user (see the `--tenant` follow-up, item 20
in the verification record -- an actor option belongs with it).

`check` writes nothing, because it reads.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..domain.audit import Action
from .bootstrap import bootstrap, is_bootstrapped
from .errors import DeliveryError, redact
from .push import push_artifacts
from .reset import reset_target
from .tools import default_tools

EXIT_OK = 0
EXIT_NOT_BOOTSTRAPPED = 1
EXIT_ERROR = 2


def _record(action: Action, app: str, after: dict) -> None:
    """Append one audit row for a CLI mutation.

`app.audit` is imported inside the function rather than at module scope,
    because it pulls in the ORM and the models; `Action` is a pure-domain enum
    and is imported normally at the top. Keeping the ORM out of the import
    graph until a command actually mutates something preserves the property the
    delivery package is arranged around -- see the lazy export table in
    `__init__.py`.

    The session is opened and closed here because the CLI has none, and the
    tenant is whatever `current_tenant_id()` answers with nothing bound: the
    seeded default, which is already what every other thing these commands
    touch resolves to (the `--tenant` option in follow-up 20 is what changes
    that, for this and for the rest of the CLI at once).

    **A failure to record must not undo a push that already happened**, and
    must not turn a successful delivery into a non-zero exit. The mutation is
    the customer's repo, which this cannot roll back; so the row is attempted,
    and a failure is reported on stderr and otherwise swallowed. That is the
    one place in the audit design where a missing row is tolerated rather than
    prevented, and it is tolerated because the alternative is worse.
    """
    try:
        from ..audit import record
        from ..db import SessionLocal

        with SessionLocal() as session:
            record(session, action=action, target=f"target:{app}", after=after)
    except AssertionError:
        # The suite's guards (tests/conftest.py) raise this to say a test
        # reached a seam it should have substituted. Swallowing it would make a
        # misconfigured test pass quietly, which is the one failure mode the
        # guards exist to prevent -- so it is re-raised while every real
        # runtime failure below is not.
        raise
    except Exception as exc:  # noqa: BLE001 - see the docstring
        print(
            f"WARNING: the {action.value} succeeded but could not be recorded "
            f"in the audit log: {redact(str(exc))}",
            file=sys.stderr,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.delivery",
        description="Deliver QA artifacts to an app's target repo.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser(
        "check", help="is this target delivered, or N revisions ahead? (read-only)"
    )
    p_check.add_argument("app")

    p_boot = sub.add_parser("bootstrap", help="push this repo's infra files to the target repo")
    p_boot.add_argument("app")
    p_boot.add_argument("--dry-run", action="store_true")

    p_push = sub.add_parser("push", help="deliver one story's artifacts as a PR")
    p_push.add_argument("app")
    p_push.add_argument("story_id", metavar="STORY_ID")
    p_push.add_argument("--body-file", type=Path, default=None)
    p_push.add_argument("--run-id", default=None)
    p_push.add_argument("--dry-run", action="store_true")

    p_reset = sub.add_parser(
        "reset", help="DESTRUCTIVE: wipe the target repo so bootstrap starts clean"
    )
    p_reset.add_argument("app")
    p_reset.add_argument(
        "--confirm-repo",
        default=None,
        help="the target repo name, echoed back to confirm (required unless --dry-run)",
    )
    p_reset.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        tools = default_tools()

        if args.command == "check":
            ready, target = is_bootstrapped(args.app, tools=tools)
            state = tools.catalog.state(args.app)
            print(f"Target: {target.repo} ({target.branch})")
            print(f"State:  {state.describe()}")
            if state.delivered_sha:
                print(f"Commit: {state.delivered_sha}")
            if ready:
                return EXIT_OK
            print(
                f"NOT bootstrapped: nothing has been delivered to {target.repo} yet. "
                f"The first approved delivery sets the repo up.",
                file=sys.stderr,
            )
            return EXIT_NOT_BOOTSTRAPPED

        if args.command == "bootstrap":
            result = bootstrap(args.app, dry_run=args.dry_run, tools=tools)
            if not args.dry_run:
                # The "infra re-sync" #37 names: the route's `sync_infra` flag
                # is only the *first* sync, at target creation. This is how a
                # re-sync is actually performed.
                _record(
                    Action.INFRA_SYNC,
                    result.app,
                    {
                        "ok": True,
                        "repo": result.repo,
                        "branch": result.branch,
                        "files": list(result.files),
                        "via": "cli",
                    },
                )
            print(f"App:    {result.app}")
            print(f"Target: {result.repo} ({result.branch})")
            print(f"Files:  {' '.join(result.files)}")
            if result.changes:
                print("Changes to push:")
                for line in result.changes.splitlines():
                    print(f"  {line}")
            print(result.message)
            return EXIT_OK

        if args.command == "push":
            result = push_artifacts(
                args.app,
                args.story_id,
                body_file=args.body_file,
                run_id=args.run_id,
                dry_run=args.dry_run,
                tools=tools,
            )
            if not args.dry_run:
                _record(
                    Action.DELIVERY_APPROVE,
                    result.app,
                    {
                        "story_id": result.story_id,
                        "run_id": args.run_id,
                        "repo": result.repo,
                        "branch": result.branch,
                        "committed": result.committed,
                        "delivered_sha": result.delivered_sha,
                        "pr_url": result.pr_url,
                        "pr_number": result.pr_number,
                        "via": "cli",
                    },
                )
            print(f"App:    {result.app} -> {result.repo}")
            print(f"Story:  {result.story_id}  branch {result.branch}")
            if result.delivered_sha:
                print(f"Commit: {result.delivered_sha} (recorded as delivered)")
            print(result.message)
            return EXIT_OK

        if args.command == "reset":
            if not args.dry_run and not args.confirm_repo:
                print(
                    "reset needs --confirm-repo <owner/repo> (or --dry-run to preview)",
                    file=sys.stderr,
                )
                return EXIT_ERROR
            result = reset_target(
                args.app,
                confirm_repo=args.confirm_repo or "",
                dry_run=args.dry_run,
                tools=tools,
            )
            if not args.dry_run:
                _record(
                    Action.TARGET_RESET,
                    result.app,
                    {
                        "repo": result.repo,
                        "branch": result.branch,
                        "already_empty": result.already_empty,
                        "reset_branch": result.reset_branch,
                        "deleted_branches": list(result.deleted_branches),
                        "failed_branches": list(result.failed_branches),
                        "via": "cli",
                    },
                )
            print(f"App:    {result.app}")
            print(f"Target: {result.repo} ({result.branch})")
            if result.deleted_branches:
                label = "deleted" if result.reset_branch else "would delete"
                print(f"Branches {label}:")
                for branch in result.deleted_branches:
                    print(f"  {branch}")
            for branch in result.failed_branches:
                print(f"  WARN: could not delete branch {branch}")
            print(result.message)
            return EXIT_OK

    except DeliveryError as exc:
        print(f"{args.command}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
