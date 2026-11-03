"""P5-04: a tenant's concurrency cap and monthly run quota

The two caps DESIGN.md §6 named ("Enforced at enqueue: per-tenant
concurrent-run cap and monthly run quota") and that nothing has carried until
now. Both live on `tenants` because they are a property of the customer's plan,
not of a project or an app: a cap per target would be a different product.

- `max_concurrent_runs` -- how many of this tenant's runs may be live at once,
  across all of its apps. The per-target `AppLock` already allows only one live
  run per app, so this is the limit that bounds a tenant with fifty apps.
- `monthly_run_quota` -- how many runs this tenant may *start* in a calendar
  month. Counted on `runs.created_at`, so a run that failed still spent quota:
  it consumed a sandbox, and a quota that only counted successes would make
  "retry until it works" free.

**Nullable, and `NULL` means no cap** rather than "zero allowed". The useful
third state: a tenant whose plan is genuinely unmetered, said explicitly
instead of spelled as a very large number that some later reader has to
recognise as a sentinel. It also means this revision cannot retroactively
refuse a run that was legal before it ran.

**Every tenant that already exists gets concrete caps**, which is the one thing
this revision writes rather than leaves null. A platform whose existing
customers are all unmetered would ship the feature inert, and the portal's
"usage against caps" panel would have no caps to show. New tenants are created
`NULL`/unmetered until the tenant-admin surface sets them -- that surface does
not exist yet (`VERIFICATION-P5.md` follow-up 6), which is exactly why the
default for a row nobody has configured must not be "refuse everything".

No server default and so nothing to drop: unlike P2's `tenant_id` and P5-03's
`credential_state`, there is no value the database should guess for a new
tenant. `NULL` is the correct initial state and the application never has to
write one to mean "unset".

`downgrade` drops both, which forgets every tenant's plan limits. Honest: the
previous schema has nowhere to keep them, and an unmetered platform is the
behaviour it had.

Revision ID: e9c41a7d3f28
Revises: d7b4e82f1c05
Create Date: 2026-11-03 16:55:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'e9c41a7d3f28'
down_revision = 'd7b4e82f1c05'
branch_labels = None
depends_on = None

# What an already-existing tenant is given. Spelled out here rather than
# imported from the application, for the reason every migration in this chain
# spells its values out: a revision has to keep describing the schema it wrote,
# and an import would make it describe whatever the constant says today.
_EXISTING_TENANT_CONCURRENCY = 3
_EXISTING_TENANT_MONTHLY_QUOTA = 500


def upgrade() -> None:
    op.add_column('tenants', sa.Column('max_concurrent_runs', sa.Integer(), nullable=True))
    op.add_column('tenants', sa.Column('monthly_run_quota', sa.Integer(), nullable=True))
    # Every tenant that exists at this point gets real caps; see the docstring.
    # Guarded on IS NULL so re-running against a partly-migrated database
    # cannot overwrite a cap somebody has already set deliberately.
    op.execute(
        sa.text(
            "UPDATE tenants SET max_concurrent_runs = :concurrency, "
            "monthly_run_quota = :monthly "
            "WHERE max_concurrent_runs IS NULL AND monthly_run_quota IS NULL"
        ).bindparams(
            concurrency=_EXISTING_TENANT_CONCURRENCY,
            monthly=_EXISTING_TENANT_MONTHLY_QUOTA,
        )
    )


def downgrade() -> None:
    op.drop_column('tenants', 'monthly_run_quota')
    op.drop_column('tenants', 'max_concurrent_runs')
