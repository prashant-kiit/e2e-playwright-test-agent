"""P5: a project name and an app slug are unique per tenant, not globally

The read half of P5-02 is enforcement in code (`tenancy.install_read_guard`);
this is the write half, and it is the half that decides whether two customers
can coexist at all.

`projects.name` and `targets.app` were globally unique, which is the shape of a
single-tenant system. In a multi-tenant one it means **the first customer to
register a name takes it from every other customer**, and the slug is not a
label they choose freely -- `targets.app` is the application under test, so two
customers testing the same public demo site, or the same vendor's product,
collide by nature. The refusal arrives as a 409 on target creation that the
operator can do nothing about, and it leaks the fact that someone else has
registered that name.

Both become composite on `(tenant_id, ...)`, the same move
`uq_users_tenant_id_email` made for `users.email`. Within one tenant each is
still unique, which is what keeps "the target with this slug" a lookup
returning one row -- the thing its revisions, its blob keys and its delivered
branch name are all keyed on.

**The old constraints are dropped, not left beside the new ones.** An orphaned
global unique would make the whole change decorative while every test still
passed, because nothing in the suite asserts a constraint's *absence*; that
exact trap was caught by hand in the `users.email` flip, so this revision was
replayed the same way -- upgrade, downgrade, upgrade, reading `pg_constraint` at
each stop. That check is **not performed here**: it is by hand, and its result
is recorded in VERIFICATION-P5.md.

No backfill is needed and none is attempted: `tenant_id` has been non-null on
both tables since P2 (`8f21c4b07e3a`), which added it with a server default,
backfilled the existing rows to the seeded tenant and dropped the default in
that same revision. There is no row without a tenant to repair.

`downgrade` restores the global constraints and is **meant to fail loudly** if
two tenants have by then registered the same name: picking a winner would
silently delete one customer's target, and there is no right winner to pick.

Revision ID: c8d2e5f71a94
Revises: a7c3f0e91b58
Create Date: 2026-11-03 11:30:00.000000
"""
from alembic import op

revision = 'c8d2e5f71a94'
down_revision = 'a7c3f0e91b58'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `projects_name_key` is the name Postgres gave the unnamed
    # UniqueConstraint('name') in the initial schema's create_table.
    op.drop_constraint('projects_name_key', 'projects', type_='unique')
    op.create_unique_constraint(
        'uq_projects_tenant_id_name', 'projects', ['tenant_id', 'name']
    )

    op.drop_constraint('uq_targets_app', 'targets', type_='unique')
    op.create_unique_constraint(
        'uq_targets_tenant_id_app', 'targets', ['tenant_id', 'app']
    )


def downgrade() -> None:
    op.drop_constraint('uq_targets_tenant_id_app', 'targets', type_='unique')
    op.create_unique_constraint('uq_targets_app', 'targets', ['app'])

    op.drop_constraint('uq_projects_tenant_id_name', 'projects', type_='unique')
    op.create_unique_constraint('projects_name_key', 'projects', ['name'])
