"""P4: run_log, the live log read by cursor

The live log stops being a dictionary in one process. P4 executes a run in its
own container, so the lines have to land somewhere both the writer and the API
can reach -- and an in-process bus was already wrong for two other reasons: a
restart erased the history of every run that had ever streamed, and only the
replica that started a run could stream it.

`(run_id, seq)` is the primary key and `seq` is **not** a database identity: it
is counted by the one writer that executes the run (DESIGN.md §10, and
app/orchestrator/bus.py). A second writer therefore loses on the primary key,
which is the outcome worth having.

`at` is indexed because the only query that is not "this run, after this cursor"
is the reaper's prune past the retention window. These rows are the live view
and its recent history, not the archive: `session.jsonl` remains the durable
per-run record.

Revision ID: d41b8c6f2a07
Revises: c3a7e90b41d2
Create Date: 2026-10-25 10:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'd41b8c6f2a07'
down_revision = 'c3a7e90b41d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'run_log',
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('seq', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('line', sa.Text(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('run_id', 'seq'),
    )
    op.create_index('ix_run_log_tenant_id', 'run_log', ['tenant_id'])
    op.create_index('ix_run_log_at', 'run_log', ['at'])


def downgrade() -> None:
    op.drop_index('ix_run_log_at', table_name='run_log')
    op.drop_index('ix_run_log_tenant_id', table_name='run_log')
    op.drop_table('run_log')
