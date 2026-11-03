"""P5-03: a tenant's own GitHub credential, sealed, on the target row

The three columns DESIGN.md §3 named and P4 never built. Until now there was
one operator `GITHUB_PAT` in the API's environment, so every delivery into
every customer's repository was authored by the same identity, with no
per-customer credential, no scope check at save, no expiry warning and no way
to record that GitHub had stopped accepting it.

- `github_pat_ciphertext` -- the PAT envelope-sealed by `app/envelope.py`:
  AES-GCM ciphertext plus a KMS-wrapped data key, in one self-describing
  string. `Text`, not a fixed width: the sealed form grows with the format
  version, and a column that silently truncates a credential is a very bad
  column. Nullable, because "no credential yet" is the state every target
  starts in.
- `pat_expires_at` -- what GitHub reported at save time, so the portal can warn
  before it lapses. Nullable: a fine-grained or non-expiring token reports
  nothing, which is "no expiry known" rather than "expires now".
- `credential_state` -- `absent` | `valid` | `invalid`. Non-null, because every
  row has one of those three states and nothing should have to infer it from a
  null ciphertext (the rejected case *has* ciphertext and is still unusable).

**The backfill and the dropped default, in this one revision**, the pattern P2
set for `tenant_id` and P3 set for the config columns: the column is added with
a server default so existing rows get `absent`, the backfill is implicit in
that default, and the default is then dropped so application code must set the
column from `CredentialState` rather than letting the database guess. Every
pre-existing target becomes `absent`, which is exactly true of it -- it has no
credential of its own, and until its customer pastes one its deliveries cannot
run.

Nothing is migrated *into* these columns. The operator `GITHUB_PAT` is not
copied onto every target row: it is one identity that was never any tenant's,
sealing it per target would silently give every customer the same credential
under a per-tenant name, and the environment variable is retired by this
ticket rather than laundered through it. A deployment that was delivering
before this revision has to save a PAT per target afterwards, and the portal
says so.

`downgrade` drops all three, which destroys every stored credential. That is
the honest behaviour: the ciphertext is meaningless to the previous schema, and
there is nowhere else to put it.

Revision ID: d7b4e82f1c05
Revises: c8d2e5f71a94
Create Date: 2026-11-03 14:10:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'd7b4e82f1c05'
down_revision = 'c8d2e5f71a94'
branch_labels = None
depends_on = None

# Spelled out rather than imported from app.domain.credentials: a migration has
# to keep describing the schema it wrote, and an import would make it describe
# whatever the enum says *today* -- so the day a member is added, every past
# revision silently changes meaning.
#
# `native_enum=False` makes this a VARCHAR(20) and, in SQLAlchemy 2.x,
# `create_constraint` defaults off, so there is **no CHECK constraint** -- the
# same shape `runstatus` and `step` have had since the initial schema. The
# values are enforced in the application by `_enum_col`'s
# `validate_strings=True`, not by the database. Stated here because the
# absence is easy to mistake for an oversight.
_STATES = ('absent', 'valid', 'invalid')


def upgrade() -> None:
    op.add_column('targets', sa.Column('github_pat_ciphertext', sa.Text(), nullable=True))
    op.add_column(
        'targets', sa.Column('pat_expires_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'targets',
        sa.Column(
            'credential_state',
            sa.Enum(*_STATES, name='credentialstate', native_enum=False, length=20),
            nullable=False,
            server_default='absent',
        ),
    )
    # The backfill is the server default above; dropping it here, in the same
    # revision, is what keeps "no column acquires a value the database guessed"
    # true for new rows (P2's `tenant_id`, P3's config columns).
    op.alter_column('targets', 'credential_state', server_default=None)


def downgrade() -> None:
    op.drop_column('targets', 'credential_state')
    op.drop_column('targets', 'pat_expires_at')
    op.drop_column('targets', 'github_pat_ciphertext')
