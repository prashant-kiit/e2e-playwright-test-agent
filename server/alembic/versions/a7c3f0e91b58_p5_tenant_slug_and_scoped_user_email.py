"""P5: tenant login slug, and user email unique per tenant

Two halves of one change: **who an email address identifies.**

P5-01 left `users.email` globally unique and said so out loud -- login was by
email alone, so one address had to mean one account. That is the wrong shape for
a multi-tenant portal: two customers who both employ `ops@contractor.com` cannot
both have an account, and the first tenant to claim an address locks every other
tenant out of it. Uniqueness becomes composite on `(tenant_id, email)`, which is
the same move P5-02 makes for `projects.name` and `targets.app`.

That costs login its unambiguous lookup, so this revision also gives `tenants` a
`slug`: the short, stable handle a person types at the sign-in form. Login
resolves the tenant by slug first and the user by email *within* it. The slug is
globally unique -- a handle that named two tenants would just move the ambiguity
up a level.

The seeded tenant is backfilled to `default`, matching the name P2 seeded it
with, so the existing operator's login becomes `default` / `admin@example.com`
and nothing else about their account changes. It is a constant rather than an
environment knob on purpose: the slug is echoed by the login form's prefill and
by the tests, and a variable only one of the three reads would prefill a slug no
tenant has. Further tenants get their slugs from the tenant-admin surface.

Order matters in `upgrade`: the column is added nullable, backfilled, and only
then made NOT NULL, because the seeded row already exists.

Revision ID: a7c3f0e91b58
Revises: b2f4a6c08d1e
Create Date: 2026-11-03 09:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'a7c3f0e91b58'
down_revision = 'b2f4a6c08d1e'
branch_labels = None
depends_on = None

# The name P2 seeded the single tenant with; its slug matches by default.
_DEFAULT_TENANT_SLUG = "default"


def upgrade() -> None:
    # --- tenants.slug ---
    op.add_column('tenants', sa.Column('slug', sa.String(length=63), nullable=True))
    op.execute(
        sa.text("UPDATE tenants SET slug = :slug WHERE slug IS NULL").bindparams(
            slug=_DEFAULT_TENANT_SLUG
        )
    )
    op.alter_column('tenants', 'slug', nullable=False)
    op.create_unique_constraint('uq_tenants_slug', 'tenants', ['slug'])

    # --- users.email: global -> per-tenant ---
    # `users_email_key` is the name Postgres gave the inline UniqueConstraint
    # ('email') in the P5-01 create_table.
    op.drop_constraint('users_email_key', 'users', type_='unique')
    op.create_unique_constraint('uq_users_tenant_id_email', 'users', ['tenant_id', 'email'])


def downgrade() -> None:
    op.drop_constraint('uq_users_tenant_id_email', 'users', type_='unique')
    # Only safe while no two tenants share an address; a downgrade past this
    # point with a collision present is meant to fail loudly rather than pick a
    # winner.
    op.create_unique_constraint('users_email_key', 'users', ['email'])

    op.drop_constraint('uq_tenants_slug', 'tenants', type_='unique')
    op.drop_column('tenants', 'slug')
