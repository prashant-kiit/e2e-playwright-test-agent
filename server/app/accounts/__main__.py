"""CLI for onboarding: python -m app.accounts create-tenant ...

The surface that replaces hand-written SQL for creating a customer (P5-14 /
#46, story 1). **Why this is a command and not a route** is
docs/adr/0002-tenant-creation-is-an-operator-action.md; the short version is
that every authenticated surface in this application acts *as a tenant*, and
the person creating one belongs to no tenant yet -- so the authority is shell
access to the control plane, which on a single-operator deployment is exactly
who should have it.

What a customer does for themselves -- inviting and removing their own users --
is a portal surface (`/users`, admin-gated). This is the once-per-customer half.

Exit codes follow `python -m app.delivery`: 0 for success, 2 for any failure,
so a wrapper script can tell them apart without parsing output. There is no
"partial" code because there is no partial outcome -- the tenant and its first
admin are one transaction.

**The password is printed to a terminal and exists nowhere else.** No mail path
exists in this deployment, so the choice was between a password we generate and
show once, one the operator invents and therefore knows for ever, and an
account with no way in. The first is the least bad, and the ADR says so.
"""

from __future__ import annotations

import argparse
import sys

from ..db import SessionLocal
from . import AccountError, create_tenant

EXIT_OK = 0
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.accounts",
        description="Onboard a customer: create a tenant and its first admin.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser(
        "create-tenant",
        help="create a tenant and its first admin user, and print the password",
    )
    p_create.add_argument("--name", required=True, help="the customer's display name")
    p_create.add_argument(
        "--slug",
        required=True,
        metavar="SLUG",
        help=(
            "the login handle users type at the sign-in form; unique across "
            "customers, because it is what decides whose user table an email "
            "is looked up in"
        ),
    )
    p_create.add_argument(
        "--admin",
        required=True,
        metavar="EMAIL",
        help="the first admin's email address; they can then invite the rest",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "create-tenant":
        return _create_tenant(name=args.name, slug=args.slug, admin=args.admin)
    # argparse's `required=True` already refuses an unknown command, so this is
    # unreachable rather than a fallback worth inventing behaviour for.
    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


def _create_tenant(*, name: str, slug: str, admin: str) -> int:
    try:
        with SessionLocal() as session:
            added = create_tenant(
                session, name=name, slug=slug, admin_email=admin
            )
            # Read inside the session: the fields are wanted after it closes,
            # and `expire_on_commit=False` is a property of the app's factory
            # rather than of every session this might be handed.
            email = added.user.email
            tenant_slug = slug.strip().lower()
    except AccountError as exc:
        # The message is written to be read by a person -- it is the same text
        # the portal shows for the user-administration refusals -- so it is
        # printed as-is rather than wrapped in a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    # Deliberately three labelled lines rather than prose: an operator is about
    # to copy two of these somewhere, and `password:` on its own line is what
    # makes that possible without re-reading a sentence.
    print(f"tenant: {name} (log in with slug {tenant_slug!r})")
    print(f"admin: {email}")
    print(f"password: {added.password}")
    print(
        "Pass these to the customer. The password is not shown again and "
        "nothing here can recover it -- if it is lost, remove the account "
        "from the portal and invite it again."
    )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())
