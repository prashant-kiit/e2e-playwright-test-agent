"""P5-16: runs.attempt, the generation a run-scoped token names

#48 / #30's story 22: "the run-scoped token … rejected after the run ends, so
that a leaked token is useless beyond the run it was minted for". A pause ends
the *sandbox* -- the pause route destroys the container at once (DESIGN.md §5)
-- so a token minted for it has to die with it.

Liveness alone cannot do that, and refusing a paused run outright does not
work: a resumed sandbox calls `run_facts` *before* `begin_run` has moved the
row out of PAUSED, so that reading refuses the resume itself. A status check
also cannot help after the resume, when the run is RUNNING again and looks
exactly like the one that was paused. So a run gets a **generation counter**: the
token carries the attempt it was minted for, `repo.pause_run` moves it on, and
`control.service.authorized_run` refuses a token whose attempt is not the run's
current one. One column and one comparison, instead of the token table
app/run_token.py declines to pay for -- and the comparison is against a row
that is already read on every call.

`server_default="1"` for the rows that exist, and **kept** afterwards, for the
reason the quota caps keep theirs: a run that arrived with no attempt would
match no token at all, and unlike a quota there is no "unset" reading of this
column that means anything. New rows get 1 from the ORM default as well, so
the two paths into this table agree without either depending on the other.

Revision ID: c4f91b280e36
Revises: b7e04c91a2d5
Create Date: 2026-11-04 00:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'c4f91b280e36'
down_revision = 'b7e04c91a2d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "sandbox_attempt",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "sandbox_attempt")
