"""P2: tenants, revisions, file_index, and tenant_id on every table

Three new tables plus the tenant column that makes P5 a data backfill rather
than a migration across the whole system (DESIGN.md §13).

Two deliberate departures from DESIGN.md §3, amended there in the same change:

  * **No `occ_version`.** `unique(target_id, rev)` *is* the optimistic-
    concurrency check -- committing rev N+1 with parent N loses the insert if
    someone else got there first -- so a version column would misdescribe where
    the check happens.
  * **No `bundle_key`.** Git bundles presuppose a per-run worktree with its own
    history, which arrives with the sandbox in P4. This phase adds only columns
    it writes, so the models-match-migrations check stays a meaningful signal.

`delivered_sha` is added and stays null for the whole of P2: delivery still
works off the filesystem.

`tenant_id` is added non-null with a server default so existing rows backfill,
and that default is **dropped in the same revision** -- application code sets
the column from tenancy.current_tenant_id(), never from a database guess.

Revision ID: 8f21c4b07e3a
Revises: 1729d6db6790
Create Date: 2026-10-23 23:40:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = '8f21c4b07e3a'
down_revision = '1729d6db6790'
branch_labels = None
depends_on = None

# Every table that existed before P2 and therefore needs backfilling.
_EXISTING_TABLES = ("projects", "targets", "runs", "run_steps", "artifacts", "app_locks")

# The single tenant every pre-P2 row belongs to (tenancy.DEFAULT_TENANT_ID).
_DEFAULT_TENANT_ID = 1


def upgrade() -> None:
    op.create_table(
        'tenants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # Seed the one tenant before anything references it, and leave the id
    # sequence past it so a future insert does not collide.
    op.execute(
        sa.text("INSERT INTO tenants (id, name) VALUES (:id, 'default')").bindparams(
            id=_DEFAULT_TENANT_ID
        )
    )
    op.execute("SELECT setval('tenants_id_seq', (SELECT MAX(id) FROM tenants))")

    for table in _EXISTING_TABLES:
        # server_default backfills the rows already there...
        op.add_column(
            table,
            sa.Column(
                'tenant_id',
                sa.Integer(),
                nullable=False,
                server_default=sa.text(str(_DEFAULT_TENANT_ID)),
            ),
        )
        # ...and is dropped immediately, so no insert can rely on it.
        op.alter_column(table, 'tenant_id', server_default=None)
        op.create_index(f'ix_{table}_tenant_id', table, ['tenant_id'])
        op.create_foreign_key(
            f'fk_{table}_tenant_id_tenants', table, 'tenants',
            ['tenant_id'], ['id'], ondelete='RESTRICT',
        )

    op.create_table(
        'revisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('rev', sa.Integer(), nullable=False),
        sa.Column('parent_rev', sa.Integer(), nullable=True),
        sa.Column('tree_hash', sa.String(length=64), nullable=False),
        sa.Column('produced_by_run_id', sa.Integer(), nullable=True),
        sa.Column('author', sa.String(length=100), nullable=False),
        sa.Column('delivered_sha', sa.String(length=40), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['produced_by_run_id'], ['runs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['target_id'], ['targets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'],
                                name='fk_revisions_tenant_id_tenants', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        # This phase's OCC point. See the module docstring.
        sa.UniqueConstraint('target_id', 'rev', name='uq_revisions_target_rev'),
    )
    op.create_index('ix_revisions_tenant_id', 'revisions', ['tenant_id'])

    op.create_table(
        'file_index',
        sa.Column('revision_id', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(length=500), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('blob_key', sa.String(length=500), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['revision_id'], ['revisions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'],
                                name='fk_file_index_tenant_id_tenants', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('revision_id', 'path'),
    )
    op.create_index('ix_file_index_tenant_id', 'file_index', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_file_index_tenant_id', table_name='file_index')
    op.drop_table('file_index')
    op.drop_index('ix_revisions_tenant_id', table_name='revisions')
    op.drop_table('revisions')

    for table in _EXISTING_TABLES:
        op.drop_constraint(f'fk_{table}_tenant_id_tenants', table, type_='foreignkey')
        op.drop_index(f'ix_{table}_tenant_id', table_name=table)
        op.drop_column(table, 'tenant_id')

    op.drop_table('tenants')
