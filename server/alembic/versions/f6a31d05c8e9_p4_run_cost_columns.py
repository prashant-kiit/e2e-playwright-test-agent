"""P4: runs.spend_usd and runs.sandbox_seconds

What a run cost: the spend the agent runtime reported (the `result` events the
runner already parses, which is why this is a budget rather than a new
accounting system) and how long its sandbox existed. Recorded so cost is
attributable per run before per-tenant quotas exist -- those are P5's, where
tenants do.

Both nullable, and both only ever written at the end of a run. A sandbox killed
outright records neither, which is the case the lease reaper reconciles and the
one case where "what did it cost?" has no answer worth inventing.

`Numeric(10, 4)` rather than a float: fractions of a cent are what the runtime
reports, and a column that rounds them is a column that disagrees with the
invoice.

Revision ID: f6a31d05c8e9
Revises: e52c9a71f3b4
Create Date: 2026-10-25 12:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'f6a31d05c8e9'
down_revision = 'e52c9a71f3b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('runs', sa.Column('spend_usd', sa.Numeric(precision=10, scale=4),
                                    nullable=True))
    op.add_column('runs', sa.Column('sandbox_seconds', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('runs', 'sandbox_seconds')
    op.drop_column('runs', 'spend_usd')
