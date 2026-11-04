"""P5-06: the prompts table, and the prompt versions a run used

Prompts stop being one set of bytes for every customer. `prompts(id, tenant_id,
name, body, rev)` holds a tenant's versions of a prompt, and `runs.prompt_revs`
records which version of each the run was actually given.

**Nothing is seeded here, and that is deliberate.** The other P5 revisions that
introduced a table seeded it (`users` seeds the operator the shared password
became). This one does not, because seeding prompts in a migration would answer
the question for the tenants that exist *now* and leave it open for every tenant
created afterwards -- so the hook on tenant creation would have to exist anyway,
and the migration would be a second implementation of it that drifts the first
time a prompt file is added to the package. `app/prompt_store.py` seeds a
tenant's missing defaults at the resolution seam instead, which covers the
tenants this revision would have seeded and every later one with one mechanism.
A tenant therefore has no prompt rows until something resolves a prompt for it,
and that is the correct state rather than a pending backfill.

`prompt_revs` is nullable: every run that already exists predates the column and
there is no version it can honestly be given. A reader must treat null as "not
recorded" rather than "no prompts" -- see the column comment in app/models.py.

Revision ID: a3f70c2e8b91
Revises: f1a62c90d4e7
Create Date: 2026-11-04 00:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'a3f70c2e8b91'
down_revision = 'f1a62c90d4e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'prompts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('rev', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'],
                                name='fk_prompts_tenant_id_tenants', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', 'rev',
                            name='uq_prompts_tenant_id_name_rev'),
    )
    op.create_index('ix_prompts_tenant_id', 'prompts', ['tenant_id'])

    op.add_column('runs', sa.Column('prompt_revs', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('runs', 'prompt_revs')
    op.drop_index('ix_prompts_tenant_id', table_name='prompts')
    op.drop_table('prompts')
