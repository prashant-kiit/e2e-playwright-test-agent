"""P5-15: purge_log, the record that survives a tenant purge

#47 / #30's story 32: "deleting a tenant to purge that tenant's entire storage
prefix and rows, so that offboarding is clean". One of the criteria is that the
purge "records what it did somewhere that survives it", and that rules out
every table the purge touches -- including `audit_log`, which is where every
other control-plane mutation is recorded and which the purge is the one
operation permitted to delete from.

So `purge_log` is **not** tenant-owned: no `tenant_id` foreign key, not under
`install_tenant_guard`, and not something a customer can read. It is a platform
record, and it is the only thing that can answer "what happened to Acme?" after
Acme's rows are gone.

**`purged_tenant_id`, not `tenant_id`.** It names a tenant that no longer
exists, which is the opposite of what `TenantOwned.tenant_id` means, and the
structural test in `tests/test_tenant_isolation_repo.py` fails any mapped class
carrying the latter name without inheriting the mixin. It caught this table on
the first run and was right to: a reader seeing `tenant_id` would assume the
tenant guard applied here.

It is a plain integer for the same reason `audit_log.actor` is a string rather
than an FK to `users`: the row it would point at is the row the operation
deletes. `RESTRICT` would block the purge and `SET NULL` would forget which
tenant it was.

`removed` is JSON rather than a column per table, because the set of
tenant-owned tables changes with the schema and a column each would need a
migration every time one is added -- which is exactly when nobody would
remember to add it.

Revision ID: d5e82a013f47
Revises: c4f91b280e36
Create Date: 2026-11-04 00:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'd5e82a013f47'
down_revision = 'c4f91b280e36'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purge_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purged_tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("removed", sa.JSON(), nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("purge_log")
