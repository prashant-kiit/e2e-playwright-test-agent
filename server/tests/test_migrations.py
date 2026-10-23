"""The Alembic chain and the ORM models must describe the same schema.

conftest builds the test schema by running the migrations, so everything else in
the suite already exercises them. This adds the check that the migrations are
also *complete*: autogenerate against the migrated database must find nothing
left to do. Without it, a model change committed without a revision is invisible
until deploy.
"""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

import app.models  # noqa: F401  (register the ORM tables on Base.metadata)
from app.db import Base


def test_migrations_match_the_models(pg_engine):
    with pg_engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == [], (
        "models and migrations disagree; add an Alembic revision for:\n"
        + "\n".join(repr(d) for d in diff)
    )


def test_every_table_is_covered_by_a_migration(pg_engine):
    from sqlalchemy import inspect

    migrated = set(inspect(pg_engine).get_table_names())
    declared = {t.name for t in Base.metadata.sorted_tables}
    assert declared - migrated == set(), "declared but never migrated"
