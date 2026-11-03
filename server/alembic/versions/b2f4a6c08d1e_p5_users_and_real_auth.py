"""P5: users table and real per-user auth

Replaces the single shared password (QA_ADMIN_PASSWORD) with a `users` table:
per-tenant membership, a role, and a password hash. `tenancy.current_tenant_id`
now resolves from the authenticated user's session; this migration is the
backfill half of that -- the data that lets a session name a tenant.

The existing single-operator access is *preserved*, not dropped: it is seeded
here as one admin user in the default tenant, so the person who logged in with
the shared password yesterday logs in as themselves today -- **with the same
password**. That is what the QA_ADMIN_PASSWORD fallback below is for: an
operator deployed with QA_ADMIN_PASSWORD=s3cret must not wake up to an account
whose password is "admin". The variable is dead as a *login path* (there is no
code left that compares against it) and read here once, as the thing whose
access this row inherits.

Unlike P2's tenant column, `users` is a brand-new table with no pre-existing
rows, so it needs no backfill server default: the one row is seeded with its
`tenant_id` set explicitly, exactly as application inserts must.

**The hash is computed here rather than imported from app/auth.py.** A
migration is frozen history: the other six import no application code, and a
later change to the app's hashing would otherwise silently change what this
revision does when replayed from zero (which CI does on every run). The format
is self-describing -- algorithm, cost and salt all live in the string -- so
`auth.verify_password` still reads this row after the app raises its iteration
count.

Revision ID: b2f4a6c08d1e
Revises: f6a31d05c8e9
Create Date: 2026-11-02 12:00:00.000000
"""
import hashlib
import os
import secrets

import sqlalchemy as sa

from alembic import op

revision = 'b2f4a6c08d1e'
down_revision = 'f6a31d05c8e9'
branch_labels = None
depends_on = None

# The tenant the seeded operator belongs to (tenancy.DEFAULT_TENANT_ID).
_DEFAULT_TENANT_ID = 1
# A fixed id so the test fixture can preserve the seeded row across truncation,
# the way it preserves the seeded tenant.
_SEED_ADMIN_ID = 1

# Frozen copy of app/auth.py's hash format at the time of this revision. See the
# module docstring for why this is not an import.
_PBKDF2_ITERATIONS = 240_000


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _seed_password() -> str:
    """The password the seeded admin inherits.

    QA_ADMIN_PASSWORD is the pre-P5 shared password: honouring it is what makes
    "the migration preserves existing access" true rather than nearly true.
    QA_SEED_ADMIN_PASSWORD overrides it for a fresh install that never had one.
    """
    return (
        os.environ.get("QA_SEED_ADMIN_PASSWORD")
        or os.environ.get("QA_ADMIN_PASSWORD")
        or "admin"
    )


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
    op.execute(
        sa.text(
            "INSERT INTO users (id, tenant_id, email, role, credential) "
            "VALUES (:id, :tid, :email, 'admin', :cred)"
        ).bindparams(
            id=_SEED_ADMIN_ID,
            tid=_DEFAULT_TENANT_ID,
            email=email,
            cred=_hash_password(_seed_password()),
        )
    )
    # Leave the sequence past the seeded row so the first invited user does not
    # collide with it (mirrors how P2 seeded the one tenant).
    op.execute("SELECT setval('users_id_seq', (SELECT MAX(id) FROM users))")


def downgrade() -> None:
    op.drop_index('ix_users_tenant_id', table_name='users')
    op.drop_table('users')
