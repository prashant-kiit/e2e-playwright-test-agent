"""P5-07: the immutable audit_log

`audit_log(id, tenant_id, actor, action, target, before, after, at)`: one row
per control-plane mutation, naming the user who authorized it. #37 / #30's
stories 26-28.

**The trigger is the point of this revision, not the table.** "Append-only"
asserted only in application code is a property of `app/audit.py`'s API surface
-- true until someone writes an UPDATE somewhere else, or opens psql. Story 28
asks for a trail that "cannot be quietly altered", so the refusal lives in the
database: `BEFORE UPDATE OR DELETE ... FOR EACH ROW` raises, and every path
into Postgres hits it.

Deliberately **row-level**, which means it does not fire on TRUNCATE. The test
fixture truncates between tests and would otherwise be unable to reset the
table; TRUNCATE needs table-owner rights, so what is given up is small and what
is bought is a suite that can still assert this at all.

The one exception the spec allows is tenant purge (#30, story 32, unbuilt). It
will have to `ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only`
inside its transaction -- an explicit, reviewable line, which is the right
shape for the single write permitted to erase part of the trail.

**Nothing is backfilled.** The mutations that happened before this revision
were not recorded, and there is nowhere honest to recover them from: inventing
rows for them would make the trail's earliest entries the only untrustworthy
ones, which is worse than a trail that visibly starts here.

Revision ID: b7e04c91a2d5
Revises: a3f70c2e8b91
Create Date: 2026-11-04 00:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'b7e04c91a2d5'
down_revision = 'a3f70c2e8b91'
branch_labels = None
depends_on = None

# Matches `models._enum_col`: VARCHAR-backed, length 20, storing the member
# `.value`. `test_migrations.py` compares types, so this has to agree with the
# model rather than merely be wide enough.
_ACTION = sa.Enum(
    'delivery.approve', 'pat.save', 'pat.clear', 'infra.sync',
    'target.reset', 'quota.change', 'prompt.save',
    name='action', native_enum=False, length=20,
)

# Raising rather than silently discarding the write: a rule with `DO INSTEAD
# NOTHING` would let an UPDATE appear to succeed, which is how a caller comes
# to believe it changed a row it did not. `TG_OP` names which of the two was
# attempted, so the error says what was refused.
_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION audit_log_refuse_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'audit_log is append-only: % is not permitted (row id %)',
        TG_OP, OLD.id
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('actor', sa.String(length=320), nullable=False),
        sa.Column('action', _ACTION, nullable=False),
        sa.Column('target', sa.String(length=500), nullable=False),
        sa.Column('before', sa.JSON(), nullable=True),
        sa.Column('after', sa.JSON(), nullable=True),
        sa.Column('at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'],
                                name='fk_audit_log_tenant_id_tenants',
                                ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_log_tenant_id', 'audit_log', ['tenant_id'])
    op.create_index('ix_audit_log_at', 'audit_log', ['at'])

    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER audit_log_append_only "
        "BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_refuse_mutation()"
    )


def downgrade() -> None:
    # The trigger goes with the table, but the function does not, so it is
    # dropped explicitly -- otherwise a downgrade/upgrade cycle meets an
    # existing function and `CREATE OR REPLACE` is what keeps that working.
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
    op.drop_index('ix_audit_log_at', table_name='audit_log')
    op.drop_index('ix_audit_log_tenant_id', table_name='audit_log')
    op.drop_table('audit_log')
    op.execute("DROP FUNCTION IF EXISTS audit_log_refuse_mutation()")
