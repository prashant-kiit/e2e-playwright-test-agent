"""P5: users table and real per-user auth

Replaces the single shared password (QA_ADMIN_PASSWORD) with a `users` table:
per-tenant membership, a role, and a password hash. `tenancy.current_tenant_id`
now resolves from the authenticated user's session; this migration is the
backfill half of that -- the data that lets a session name a tenant.

The existing single-operator access is *preserved*, not dropped: it is seeded
here as one admin user in the default tenant, so the person who logged in with
the shared password yesterday logs in as themselves today. Its email and
initial password come from QA_SEED_ADMIN_EMAIL / QA_SEED_ADMIN_PASSWORD
(admin@example.com / admin by default), hashed by the same function the login
path verifies against, so there is one source of truth for the algorithm.

Unlike P2's tenant column, `users` is a brand-new table with no pre-existing
rows, so it needs no backfill server default: the one row is seeded with its
`tenant_id` set explicitly, exactly as application inserts must.

Revision ID: b2f4a6c08d1e
Revises: f6a31d05c8e9
Create Date: 2026-11-02 12:00:00.000000
"""
import os

import sqlalchemy as sa

from alembic import op
from app.auth import hash_password

revision = 'b2f4a6c08d1e'
down_revision = 'f6a31d05c8e9'
branch_labels = None
depends_on = None

# The tenant the seeded operator belongs to (tenancy.DEFAULT_TENANT_ID).
_DEFAULT_TENANT_ID = 1
# A fixed id so the test fixture can preserve the seeded row across truncation,
# the way it preserves the seeded tenant.
_SEED_ADMIN_ID = 1


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('role', sa.Enum('member', 'admin', name='userrole', native_enum=False, length=20), nullable=False),
        sa.Column('credential', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'],
                                name='fk_users_tenant_id_tenants', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )
    op.create_index('ix_users_tenant_id', 'users', ['tenant_id'])

    email = os.environ.get("QA_SEED_ADMIN_EMAIL", "admin@example.com")
    password = os.environ.get("QA_SEED_ADMIN_PASSWORD", "admin")
    op.execute(
        sa.text(
            "INSERT INTO users (id, tenant_id, email, role, credential) "
            "VALUES (:id, :tid, :email, 'admin', :cred)"
        ).bindparams(
            id=_SEED_ADMIN_ID,
            tid=_DEFAULT_TENANT_ID,
            email=email,
            cred=hash_password(password),
        )
    )
    # Leave the sequence past the seeded row so the first invited user does not
    # collide with it (mirrors how P2 seeded the one tenant).
    op.execute("SELECT setval('users_id_seq', (SELECT MAX(id) FROM users))")


def downgrade() -> None:
    op.drop_index('ix_users_tenant_id', table_name='users')
    op.drop_table('users')
