"""The live log is a table, read by cursor.

Before P4 the log was an in-process dictionary: a late subscriber saw whatever
one process happened to remember, a restart erased the history of every run that
had ever streamed, and only the replica that started a run could stream it.

These tests are written against the `LogBus` protocol rather than against either
implementation, so what they pin down is the contract both have to keep -- and
then the Postgres-backed one is held to the three properties the in-memory one
cannot have: real history for a late subscriber, history that survives a fresh
bus instance, and no replica affinity.
"""

from __future__ import annotations

import pytest

from app import repo
from app.orchestrator.bus import InMemoryLogBus, PostgresLogBus
from tests.target_helpers import create_target, public_resolver


@pytest.fixture()
def run_id(session_factory):
    with session_factory() as s:
        project = repo.create_project(s, name="demo")
        target = create_target(s, project.id, app="demo", name="Demo")
        return repo.start_run(s, target_id=target.id, story_id="SCRUM-1", mode="full").id


@pytest.fixture()
def pg_bus(session_factory):
    return PostgresLogBus(session_factory=session_factory)


# --- the contract both implementations keep -------------------------------

def test_lines_are_read_back_in_order_from_a_cursor(pg_bus, run_id):
    for line in ("one", "two", "three"):
        pg_bus.publish(run_id, line)

    lines, cursor = pg_bus.read_from(run_id, 0)

    assert lines == ["one", "two", "three"]
    assert cursor > 0


def test_a_cursor_read_returns_only_what_is_new(pg_bus, run_id):
    pg_bus.publish(run_id, "one")
    _first, cursor = pg_bus.read_from(run_id, 0)

    pg_bus.publish(run_id, "two")
    lines, _cursor = pg_bus.read_from(run_id, cursor)

    assert lines == ["two"]


def test_the_emitter_is_a_plain_callable_bound_to_the_run(pg_bus, run_id):
    emit = pg_bus.emitter(run_id)
    emit("from the driver")

    assert pg_bus.read_from(run_id, 0)[0] == ["from the driver"]


def test_one_runs_lines_are_not_another_runs(pg_bus, session_factory, run_id):
    with session_factory() as s:
        other_project = repo.create_project(s, name="other")
        other_target = create_target(s, other_project.id, app="other", name="Other")
        other = repo.start_run(
            s, target_id=other_target.id, story_id="SCRUM-2", mode="full"
        ).id

    pg_bus.publish(run_id, "mine")
    pg_bus.publish(other, "theirs")

    assert pg_bus.read_from(run_id, 0)[0] == ["mine"]
    assert pg_bus.read_from(other, 0)[0] == ["theirs"]


# --- what only the table can do -------------------------------------------

def test_history_survives_a_fresh_bus_instance(pg_bus, session_factory, run_id):
    """The restart case the in-memory bus fails: a new process, same history."""
    pg_bus.publish(run_id, "before the deploy")

    fresh = PostgresLogBus(session_factory=session_factory)

    assert fresh.read_from(run_id, 0)[0] == ["before the deploy"]


def test_two_readers_both_see_every_line(pg_bus, session_factory, run_id):
    """No replica affinity: a second reader is not a second subscription."""
    first = PostgresLogBus(session_factory=session_factory)
    second = PostgresLogBus(session_factory=session_factory)

    pg_bus.publish(run_id, "a")
    pg_bus.publish(run_id, "b")

    assert first.read_from(run_id, 0)[0] == ["a", "b"]
    assert second.read_from(run_id, 0)[0] == ["a", "b"]


def test_a_late_subscriber_gets_the_history_from_the_first_line(pg_bus, run_id):
    for i in range(50):
        pg_bus.publish(run_id, f"line {i}")

    lines, _cursor = pg_bus.read_from(run_id, 0)

    assert lines[0] == "line 0"
    assert len(lines) == 50


def test_the_in_memory_bus_loses_history_with_its_process(run_id):
    """Stated as a test because it is the reason the table exists."""
    first = InMemoryLogBus()
    first.publish(run_id, "a line")

    assert InMemoryLogBus().read_from(run_id, 0)[0] == []


# --- the route reads the table, not a process -----------------------------

@pytest.fixture()
def client(session_factory):
    """A client whose log bus is Postgres-backed, as a sandboxed run's is.

    `session_factory` only, never the `session` fixture as well: both truncate
    on teardown and a truncate blocks on the other's open transaction (the same
    rule test_reaper.py follows).
    """
    from fastapi.testclient import TestClient

    from app.api import get_log_bus, get_resolver, get_storage
    from app.auth import require_auth
    from app.db import get_session
    from app.main import app
    from tests.storage_helpers import FakeStorage

    def _session_dep():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _session_dep
    app.dependency_overrides[require_auth] = lambda: None
    # P4: the write path resolves a base URL, and no test may touch real DNS.
    app.dependency_overrides[get_resolver] = lambda: public_resolver
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_log_bus] = lambda: PostgresLogBus(
        session_factory=session_factory
    )
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_the_events_route_replays_a_finished_run_from_the_table(
    client, session_factory, run_id
):
    """The restart case, end to end: the API process never saw these lines."""
    writer = PostgresLogBus(session_factory=session_factory)
    writer.publish(run_id, "line one")
    writer.publish(run_id, "line two")
    with session_factory() as s:
        repo.begin_run(s, run_id)
        repo.complete_run(s, run_id)

    body = client.get(f"/runs/{run_id}/events").text

    assert "line one" in body
    assert "line two" in body
    assert "event: end" in body


def test_the_events_route_ends_when_the_run_is_terminal_without_a_bus_close(
    client, session_factory, run_id
):
    """Nothing in the API's process closed this stream: the run's status did."""
    PostgresLogBus(session_factory=session_factory).publish(run_id, "only line")
    with session_factory() as s:
        repo.fail_run(s, run_id, "boom")

    body = client.get(f"/runs/{run_id}/events").text

    assert "only line" in body
    assert "event: end" in body


# --- the live view is not an archive --------------------------------------

def test_the_reaper_prunes_log_lines_past_the_retention_window(session_factory, run_id):
    """`session.jsonl` is the durable record; these rows are the live view.

    An append-only table nobody prunes is the slowest kind of outage, so the
    reaper loop that frees dead runs' locks prunes these too.
    """
    from datetime import timedelta

    from sqlalchemy import update

    from app.domain import lease
    from app.models import RunLog
    from app.orchestrator.bus import prune_run_logs

    pg_bus = PostgresLogBus(session_factory=session_factory)
    pg_bus.publish(run_id, "old news")
    pg_bus.publish(run_id, "today's news")
    with session_factory() as s:
        s.execute(
            update(RunLog)
            .where(RunLog.seq == 1)
            .values(at=lease.utcnow() - timedelta(days=30))
        )
        s.commit()

    with session_factory() as s:
        pruned = prune_run_logs(s, days=7)

    assert pruned == 1
    assert pg_bus.read_from(run_id, 0)[0] == ["today's news"], "inside the window, kept"


def test_the_reaper_loop_prunes_as_well_as_reaps(session_factory, run_id, monkeypatch):
    """The prune rides the loop that already runs every 30 seconds."""
    import asyncio

    from app import reaper

    PostgresLogBus(session_factory=session_factory).publish(run_id, "a line")
    pruned: list[int] = []
    monkeypatch.setattr(
        reaper, "prune_run_logs", lambda session, **kw: pruned.append(1) or 0
    )

    async def one_pass():
        task = asyncio.create_task(
            reaper.reaper_loop(interval_s=0.01, session_factory=session_factory)
        )
        await asyncio.sleep(0.2)
        task.cancel()

    asyncio.run(one_pass())

    assert pruned, "the reaper loop pruned the log table"
