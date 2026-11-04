"""P5-04 follow-up: a tenant nobody configured is bounded, not unmetered

Closes the hole `e9c41a7d3f28` shipped with. That revision added the two cap
columns as plain nullable integers, where `NULL` means *no cap*, and backfilled
the tenants that existed at the time. Every tenant created afterwards therefore
arrived unmetered, and #35's own premise -- "bound each tenant's usage so one
busy or abusive tenant cannot starve the platform" -- was true only of a tenant
somebody had remembered to configure. Nothing remembered: there is no
`create_tenant` function anywhere in this application, so a tenant comes from
the previous revision's seed or from a hand-written `INSERT`.

**A server default is the fix because it is the only thing both of those paths
go through.** An application-side default would have covered neither the seed
nor the `INSERT`, and the second is how every real second tenant has been made
so far (there is still no tenant-admin surface).

**The default is kept, not dropped, and that is a departure from this chain's
usual pattern** -- P2's `tenant_id` and P5-03's `credential_state` both add a
server default, backfill with it, then drop it in the same revision so that
application code must set the column rather than let the database guess. That
rule exists to stop a column acquiring a meaningless value nobody chose. Here
the default *is* the choice, and it has to outlive the revision: its whole job
is to apply to rows inserted next year by code or by hand that does not mention
these columns.

`NULL` still means **no cap**. An unmetered plan is a real product state and is
still expressible -- it is now something a plan asks for explicitly, rather than
what a tenant gets by nobody thinking about it. `repo.set_tenant_caps(..., None)`
writes that `NULL` on purpose.

The values match `app.domain.quotas.DEFAULT_*` and the previous revision's
backfill, and are spelled out literally here for the reason every revision in
this chain spells its values out: a revision has to keep describing the schema
it wrote, and an import would make it describe whatever the constant says today.

`downgrade` drops the defaults and leaves the columns and their data alone,
which returns the schema to `e9c41a7d3f28` exactly: a new tenant is unmetered
again.

Revision ID: f1a62c90d4e7
Revises: e9c41a7d3f28
Create Date: 2026-11-03 18:20:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'f1a62c90d4e7'
down_revision = 'e9c41a7d3f28'
branch_labels = None
depends_on = None

_DEFAULT_CONCURRENCY = 3
_DEFAULT_MONTHLY_QUOTA = 500


def upgrade() -> None:
    op.alter_column(
        'tenants',
        'max_concurrent_runs',
        existing_type=sa.Integer(),
        existing_nullable=True,
        server_default=str(_DEFAULT_CONCURRENCY),
    )
    op.alter_column(
        'tenants',
        'monthly_run_quota',
        existing_type=sa.Integer(),
        existing_nullable=True,
        server_default=str(_DEFAULT_MONTHLY_QUOTA),
    )


def downgrade() -> None:
    op.alter_column(
        'tenants',
        'monthly_run_quota',
        existing_type=sa.Integer(),
        existing_nullable=True,
        server_default=None,
    )
    op.alter_column(
        'tenants',
        'max_concurrent_runs',
        existing_type=sa.Integer(),
        existing_nullable=True,
        server_default=None,
    )
