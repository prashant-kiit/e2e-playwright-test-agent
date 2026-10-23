"""The CI guard on the DB-backed tests.

conftest skips the DB-backed tests when Postgres is unreachable so the pure
domain tests still run offline. That is right locally and dangerous in CI, where
a job without a database would report success having run almost nothing. The
guard keeps the local default and lets CI demand a database instead.
"""

from __future__ import annotations

import pytest

from tests.conftest import db_unavailable


def test_unreachable_postgres_skips_by_default(monkeypatch):
    monkeypatch.delenv("QA_REQUIRE_DB", raising=False)
    with pytest.raises(pytest.skip.Exception):
        db_unavailable("no postgres")


def test_unreachable_postgres_fails_when_ci_requires_a_database(monkeypatch):
    """A green tick must never mean "the DB-backed tests all skipped"."""
    monkeypatch.setenv("QA_REQUIRE_DB", "1")
    with pytest.raises(pytest.fail.Exception, match="QA_REQUIRE_DB"):
        db_unavailable("no postgres")
