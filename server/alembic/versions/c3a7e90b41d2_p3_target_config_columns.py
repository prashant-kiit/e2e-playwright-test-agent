"""P3: a target's configuration becomes columns on `targets`

apps/<app>/app.json held `baseURL`, `locators`, `agentNotes`, `targetRepo` and
`targetBranch`. P3 moves truth into Postgres (DESIGN.md §4), so they become
columns here and the file stops existing.

Added non-null with a backfill default that is **dropped in the same revision**,
following P2's `tenant_id` pattern: rows that already exist need a value, and no
future insert may rely on the database having one. The cutover command
(`python -m app.cutover`) replaces the backfilled placeholders with each
target's real configuration, read from the app.json still on disk while the
mount is there.

`agent_notes` is JSON because it is a list in app.json and is injected into the
agent's prompt context as a list. `locators` is free text. There are no PAT
columns: per-tenant encrypted credentials are P5, and `GITHUB_PAT` stays a
process-level environment variable.

The backfilled `target_repo` is deliberately the template placeholder, which
app/target_config.py refuses on the write path: a backfilled row is not a
configured row, and the cutover is what configures it.

Revision ID: c3a7e90b41d2
Revises: 8f21c4b07e3a
Create Date: 2026-10-24 15:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'c3a7e90b41d2'
down_revision = '8f21c4b07e3a'
branch_labels = None
depends_on = None

# What an unconfigured row looks like until the cutover imports its app.json.
# The repo placeholder is the one app/target_config.clean_target_repo refuses.
_BACKFILL = {
    "base_url": "",
    "locators": "",
    "agent_notes": "[]",
    "target_repo": "owner/repo-that-receives-the-tests",
    "target_branch": "master",
}

_COLUMNS = (
    ("base_url", sa.String(length=500)),
    ("locators", sa.Text()),
    ("agent_notes", sa.JSON()),
    ("target_repo", sa.String(length=200)),
    ("target_branch", sa.String(length=200)),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        # server_default backfills the rows already there...
        op.add_column(
            "targets",
            sa.Column(
                name,
                type_,
                nullable=False,
                server_default=sa.text(f"'{_BACKFILL[name]}'"),
            ),
        )
        # ...and is dropped immediately, so no insert can rely on it.
        op.alter_column("targets", name, server_default=None)


def downgrade() -> None:
    for name, _type in reversed(_COLUMNS):
        op.drop_column("targets", name)
