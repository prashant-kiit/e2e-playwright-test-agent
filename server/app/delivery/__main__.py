"""CLI for the delivery tools: python -m app.delivery <command>

Replaces scripts/check-bootstrapped.sh, bootstrap-target.sh, push-artifacts.sh
and reset-target.sh. Exit codes match the scripts: `check` exits 1 when a target
is not bootstrapped, and any other failure exits 2.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bootstrap import bootstrap, is_bootstrapped
from .errors import DeliveryError
from .push import push_artifacts
from .reset import reset_target
from .tools import default_tools

EXIT_OK = 0
EXIT_NOT_BOOTSTRAPPED = 1
EXIT_ERROR = 2


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
            state = tools.state(args.app)
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
