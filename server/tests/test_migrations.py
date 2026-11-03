"""The Alembic chain and the ORM models must describe the same schema.

conftest builds the test schema by running the migrations, so everything else in
the suite already exercises them. This adds the check that the migrations are
also *complete*: autogenerate against the migrated database must find nothing
left to do. Without it, a model change committed without a revision is invisible
until deploy.
"""

from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

import app.models  # noqa: F401  (register the ORM tables on Base.metadata)
from app.db import Base

SERVER_DIR = Path(__file__).resolve().parents[1]


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


def test_running_the_migrations_does_not_disable_application_logging():
    """`alembic/env.py` must pass `disable_existing_loggers=False` to `fileConfig`.

    The default is True, which switches off every logger alembic.ini does not
    itself name -- all of `app.*`. conftest runs `alembic upgrade head` in
    process to build the test schema, so the default disabled application
    logging for every test that ran afterwards, and it failed *open*: a test
    asserting something was logged saw an empty `caplog`, and a test asserting
    nothing was logged passed for the wrong reason.

    Asserted on the **source**, not by observing a logger, and that is
    deliberate. `disable_existing_loggers` only disables loggers that already
    exist, so the observable version of this test passes or fails on whether
    some other module happened to be imported first -- which is exactly the
    order-dependence that hid the bug. The structural check cannot be fooled
    that way (the sibling of `test_dispatch.py`'s source assertions).
    """
    env = (SERVER_DIR / "alembic" / "env.py").read_text()

    assert "fileConfig(" in env, "env.py no longer configures logging; update this test"
    call = env[env.index("fileConfig(config.config_file_name") :]
    call = call[: call.index(")") + 1]
    assert "disable_existing_loggers=False" in call, (
        "alembic/env.py calls fileConfig without disable_existing_loggers=False, "
        "which disables every app.* logger for the rest of the process"
    )
