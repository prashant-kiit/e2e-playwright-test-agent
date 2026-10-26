"""P4: runs.sandbox_handle, the dispatch seam's one column

The sandbox executing a run, as its scheduler names it -- a container id, a
Kubernetes job name, a Fargate task ARN. Opaque to the control plane: it is
recorded so an SRE can find the sandbox behind a live run and so the stop and
pause paths have something to kill, and it is never parsed here.

Nullable, because a run on the thread path has no sandbox to name and a column
that guessed one would be a column that lies. One column this phase *writes*,
which is P2's rule kept -- the thing that keeps
`test_migrations_match_the_models` a signal rather than a column inventory.

Revision ID: e52c9a71f3b4
Revises: d41b8c6f2a07
Create Date: 2026-10-25 11:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'e52c9a71f3b4'
down_revision = 'd41b8c6f2a07'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('runs', sa.Column('sandbox_handle', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('runs', 'sandbox_handle')
