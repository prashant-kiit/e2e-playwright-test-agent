"""#56: revoked_users, so a removal takes effect now rather than in 15 minutes

UAT 3 (#54) removed an admin and watched the removed account go on working:
`/auth/refresh` minted it a fresh cookie, and with that cookie it read
`/users`, created another admin and changed the tenant's quotas. The refresh
half was fixed in the UAT's own pass -- the route re-reads the `users` row now.
What was left, and what #56 decided, is the cookie the removed user *already*
holds: it verifies on its signature alone, so it was good for the remainder of
`auth.ACCESS_MAX_AGE`.

This table is the chosen option of four. `require_auth` reads it once per
authenticated request and refuses a user id removed within the window. It is
not the session or token table `app/auth.py` and `app/run_token.py` both
declined: a revocation stops mattering once no cookie minted before it can
still verify, so the table holds a row per *removal* rather than per session,
and `app/revocation.py` deletes the expired ones as it writes the next (within
the acting tenant, since the prune is an ORM bulk delete under the tenant
guard).

`user_id` has **no foreign key to `users`**, for the reason
`purge_log.purged_tenant_id` has none to `tenants`: the row it would reference
is the row the operation deletes. `CASCADE` would delete the revocation along
with the user, erasing the one fact the row exists to record, and `RESTRICT`
would refuse the removal.

It *is* tenant-owned -- `tenant_id` with the same FK and index every other
table carries -- so the per-request check is filtered to the acting tenant and
a tenant purge removes these rows with the rest.

Revision ID: e3b1f70c4d92
Revises: d5e82a013f47
Create Date: 2026-11-05 00:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'e3b1f70c4d92'
down_revision = 'd5e82a013f47'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'revoked_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'],
                                name='fk_revoked_users_tenant_id_tenants',
                                ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_revoked_users_tenant_id', 'revoked_users', ['tenant_id'])
    op.create_index('ix_revoked_users_user_id', 'revoked_users', ['user_id'])
    op.create_index('ix_revoked_users_revoked_at', 'revoked_users', ['revoked_at'])


def downgrade() -> None:
    op.drop_index('ix_revoked_users_revoked_at', table_name='revoked_users')
    op.drop_index('ix_revoked_users_user_id', table_name='revoked_users')
    op.drop_index('ix_revoked_users_tenant_id', table_name='revoked_users')
    op.drop_table('revoked_users')
