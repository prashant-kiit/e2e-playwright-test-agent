"""Unit tests for the pure domain layer (no DB, no services)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.domain import lease
from app.domain.status import (
    IllegalTransition,
    RunStatus,
    assert_transition,
    can_transition,
    is_live,
    is_terminal,
)
from app.domain.steps import (
    STEP_ORDER,
    Step,
    first_step,
    is_last,
    last_step,
    next_step,
    resume_step,
    step_index,
)


# --- steps ---------------------------------------------------------------

def test_step_order_is_the_five_pipeline_steps():
    assert STEP_ORDER == (
        Step.READ_STORY,
        Step.PLAN,
        Step.EXPLORE,
        Step.GENERATE,
        Step.HEAL,
    )
    assert first_step() is Step.READ_STORY
    assert last_step() is Step.HEAL


def test_next_step_walks_the_pipeline_then_stops():
    assert next_step(Step.READ_STORY) is Step.PLAN
    assert next_step(Step.GENERATE) is Step.HEAL
    assert next_step(Step.HEAL) is None


def test_step_index_matches_order():
    assert step_index(Step.READ_STORY) == 0
    assert step_index(Step.HEAL) == 4


def test_is_last():
    assert is_last(Step.HEAL) is True
    assert is_last(Step.PLAN) is False


def test_resume_from_nothing_starts_at_first():
    assert resume_step(None) is first_step()


def test_resume_after_a_step_is_the_next_one():
    assert resume_step(Step.PLAN) is Step.EXPLORE


def test_resume_after_last_step_is_nothing_left():
    assert resume_step(Step.HEAL) is None


# --- status transitions --------------------------------------------------

def test_happy_path_transitions_allowed():
    assert can_transition(RunStatus.PENDING, RunStatus.RUNNING)
    assert can_transition(RunStatus.RUNNING, RunStatus.COMPLETED)


def test_pause_and_resume_cycle_allowed():
    assert can_transition(RunStatus.RUNNING, RunStatus.PAUSED)
    assert can_transition(RunStatus.PAUSED, RunStatus.RUNNING)


def test_stop_allowed_from_running_and_paused():
    assert can_transition(RunStatus.RUNNING, RunStatus.STOPPED)
    assert can_transition(RunStatus.PAUSED, RunStatus.STOPPED)


def test_fail_allowed_from_any_live_status():
    for s in (RunStatus.PENDING, RunStatus.RUNNING, RunStatus.PAUSED):
        assert can_transition(s, RunStatus.FAILED)


def test_terminal_statuses_have_no_exits():
    for s in (RunStatus.COMPLETED, RunStatus.STOPPED, RunStatus.FAILED):
        assert is_terminal(s)
        for to in RunStatus:
            assert not can_transition(s, to)


def test_cannot_skip_pending_straight_to_completed():
    assert not can_transition(RunStatus.PENDING, RunStatus.COMPLETED)
    assert not can_transition(RunStatus.PAUSED, RunStatus.COMPLETED)


def test_is_live_covers_non_terminal():
    assert is_live(RunStatus.PENDING)
    assert is_live(RunStatus.RUNNING)
    assert is_live(RunStatus.PAUSED)
    assert not is_live(RunStatus.COMPLETED)


def test_assert_transition_raises_on_illegal():
    with pytest.raises(IllegalTransition):
        assert_transition(RunStatus.COMPLETED, RunStatus.RUNNING)
    # legal one does not raise
    assert_transition(RunStatus.RUNNING, RunStatus.PAUSED)


# --- lease ---------------------------------------------------------------

def test_new_expiry_is_ttl_in_the_future():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    exp = lease.new_expiry(now=now, ttl=timedelta(seconds=60))
    assert exp == now + timedelta(seconds=60)


def test_is_expired_before_and_after():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    exp = lease.new_expiry(now=now, ttl=timedelta(seconds=60))
    assert not lease.is_expired(exp, now=now + timedelta(seconds=30))
    assert lease.is_expired(exp, now=now + timedelta(seconds=61))


def test_is_expired_treats_naive_db_timestamp_as_utc():
    naive = datetime(2026, 1, 1, 0, 1, 0)  # no tzinfo, as psycopg may return
    now_before = datetime(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc)
    now_after = datetime(2026, 1, 1, 0, 2, 0, tzinfo=timezone.utc)
    assert not lease.is_expired(naive, now=now_before)
    assert lease.is_expired(naive, now=now_after)
