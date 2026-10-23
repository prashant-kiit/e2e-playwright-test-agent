"""Alembic environment. Uses the app's Base.metadata and DATABASE_URL so a single
`alembic upgrade head` (run by the container entrypoint) manages the schema.

URL precedence, highest first:
  1. a `sqlalchemy.url` the caller already set on the Config (the test harness,
     which migrates a throwaway `qa_test` database);
  2. ALEMBIC_DATABASE_URL, for when migrations need different credentials from
     the running app (a privileged owner role vs. the app's own);
  3. DATABASE_URL, via app.db.database_url().

Overriding `sqlalchemy.url` unconditionally -- as this did -- silently pointed
every programmatic upgrade at DATABASE_URL instead.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  (register tables on Base.metadata)
from alembic import context
from app.db import Base, database_url

config = context.config


def _url() -> str:
    preset = config.get_main_option("sqlalchemy.url", None)
    if preset:
        return preset
    return os.environ.get("ALEMBIC_DATABASE_URL") or database_url()


config.set_main_option("sqlalchemy.url", _url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
