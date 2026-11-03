""""Is this tenant allowed one more run?" — the caps checked at enqueue.

P5-04. One busy or abusive tenant must not be able to starve the platform, and
a breach has to read as a *refusal* rather than as a run that failed: the
customer who pressed Start is told why, nothing is dispatched, and no run row
is left behind to explain.

The checks live **above** the per-target `AppLock FOR UPDATE` trio, which this
slice does not touch (DESIGN.md §5: "adding the queue means adding a scheduler
*above* it, not changing it"). The trio answers "is this app busy?"; these
answer "is this tenant over its allowance?", and those are different questions
with different remedies -- wait, versus buy more or stop a run.

These tests are about external behaviour: what `start_run` refuses and why.
`tests/test_api_quotas.py` covers the same refusals over HTTP, which is where
the status code and the launcher-never-called half live.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app import repo
from app.domain import lease, quotas
from app.domain.status import RunStatus
from app.models import Tenant
from app.tenancy import tenant_scope
from tests.target_helpers import create_target

OTHER = 2  # a second tenant, to prove the counts do not span tenants


def _tenant_with_targets(session, count, **caps):
    """One project, `count` targets, and the tenant's caps set.

    Several targets because the concurrency cap is a *tenant* limit and only one
    run per target can be live at once (the `AppLock` trio) -- so breaching a
    cap of N takes N+1 apps, not N+1 runs on one app.
    """
    project = repo.create_project(session, name="demo")
    targets = [
        create_target(session, project.id, app=f"app-{i}", name=f"App {i}")
        for i in range(count)
    ]
    if caps:
        repo.set_tenant_caps(session, **caps)
    return targets


def test_a_tenant_at_its_concurrency_cap_cannot_start_another_run(session):
    """The cap counts a tenant's *live* runs across all of its apps."""
    a, b, c = _tenant_with_targets(session, 3, max_concurrent_runs=2)

    repo.start_run(session, target_id=a.id, story_id="SCRUM-1", mode="full")
    repo.start_run(session, target_id=b.id, story_id="SCRUM-2", mode="full")

    with pytest.raises(repo.ConcurrencyLimitReached):
        repo.start_run(session, target_id=c.id, story_id="SCRUM-3", mode="full")


def test_a_tenant_out_of_monthly_quota_cannot_start_another_run(session):
    """Counted on runs *started* this month, so finished runs still count --
    the sandbox was spent either way."""
    a, b = _tenant_with_targets(session, 2, monthly_run_quota=1)

    first = repo.start_run(session, target_id=a.id, story_id="SCRUM-1", mode="full")
    repo.begin_run(session, first.id)
    repo.complete_run(session, first.id)

    with pytest.raises(repo.MonthlyQuotaExhausted):
        repo.start_run(session, target_id=b.id, story_id="SCRUM-2", mode="full")


def test_another_tenants_runs_do_not_count_against_this_tenants_caps(session):
    """The counts go through the ordinary read guard, so they are per tenant.

    This is the test that matters most here. A quota that counted somebody
    else's runs would be worse than no quota: a busy neighbour would lock a
    customer out of a platform they are paying for, and the portal would show
    usage the customer cannot account for or reduce.
    """
    session.add(Tenant(id=OTHER, slug="second", name="Second"))
    session.commit()

    # The neighbour fills what would be *our* cap of 1, in their own tenant.
    with tenant_scope(OTHER):
        theirs = _tenant_with_targets(session, 1)
        repo.start_run(session, target_id=theirs[0].id, story_id="SCRUM-9", mode="full")

    mine = _tenant_with_targets(session, 1, max_concurrent_runs=1, monthly_run_quota=1)
    # Must not raise: our own usage is zero whatever the neighbour is doing.
    run = repo.start_run(session, target_id=mine[0].id, story_id="SCRUM-1", mode="full")

    assert run.id is not None
    assert repo.tenant_usage(session) == quotas.Usage(live_runs=1, runs_this_month=1)


def test_a_tenant_with_no_caps_is_unmetered(session):
    """`NULL` on both columns means no cap, not "nothing allowed". A tenant
    nobody has configured must not be locked out -- and there is still no
    tenant-admin surface to configure one with."""
    targets = _tenant_with_targets(
        session, 3, max_concurrent_runs=None, monthly_run_quota=None
    )

    for i, target in enumerate(targets):
        repo.start_run(session, target_id=target.id, story_id=f"SCRUM-{i}", mode="full")

    assert repo.tenant_usage(session).live_runs == 3


def test_one_run_under_the_cap_still_starts(session):
    """The boundary from the allowed side: `>=` on the cap means a tenant with
    two live runs and a cap of three is still free to start the third."""
    a, b, c = _tenant_with_targets(session, 3, max_concurrent_runs=3)

    repo.start_run(session, target_id=a.id, story_id="SCRUM-1", mode="full")
    repo.start_run(session, target_id=b.id, story_id="SCRUM-2", mode="full")
    third = repo.start_run(session, target_id=c.id, story_id="SCRUM-3", mode="full")

    assert third.status is RunStatus.PENDING


# --- a refusal is not a run -----------------------------------------------

def test_a_breach_leaves_no_run_row_and_no_lock(session):
    """The difference between a rejection and a `failed` run, asserted.

    A breach must leave *nothing* behind: no run for the operator to wonder
    about, and no app lock. A run row created and then rolled back would also
    have burned the monthly quota it was refused for, so the next attempt would
    be refused for a run that never happened.
    """
    a, b = _tenant_with_targets(session, 2, max_concurrent_runs=1)

    repo.start_run(session, target_id=a.id, story_id="SCRUM-1", mode="full")
    with pytest.raises(repo.ConcurrencyLimitReached):
        repo.start_run(session, target_id=b.id, story_id="SCRUM-2", mode="full")

    # Only the first run exists, and only its app is locked.
    assert [r.story_id for r in repo.list_runs(session)] == ["SCRUM-1"]
    assert repo.live_run_holding(session, b.id) is None
    assert repo.tenant_usage(session).runs_this_month == 1


def test_a_breach_is_not_a_run_conflict(session):
    """Two different refusals with two different remedies, so two different
    types -- `api.py` maps them to two different status codes."""
    a, b = _tenant_with_targets(session, 2, max_concurrent_runs=1)
    repo.start_run(session, target_id=a.id, story_id="SCRUM-1", mode="full")

    with pytest.raises(repo.QuotaExceeded) as caught:
        repo.start_run(session, target_id=b.id, story_id="SCRUM-2", mode="full")

    assert not isinstance(caught.value, repo.RunConflict)
    assert caught.value.kind is quotas.QuotaKind.CONCURRENCY
    assert (caught.value.used, caught.value.limit) == (1, 1)


def test_the_quota_is_checked_above_the_app_lock(session):
    """Ordering, and it is the ticket's one structural requirement: the caps go
    *above* the `AppLock FOR UPDATE` trio (DESIGN.md §5).

    Observable consequence: a tenant that is over its allowance *and* asking
    for an app that is already busy is told about the allowance. The app being
    busy is beside the point when nothing could be started anyway -- and
    "wait for this app" would be advice that does not help.
    """
    (only,) = _tenant_with_targets(session, 1, max_concurrent_runs=1)
    repo.start_run(session, target_id=only.id, story_id="SCRUM-1", mode="full")

    # Same app, which is busy (RunConflict's case) *and* over the cap.
    with pytest.raises(repo.ConcurrencyLimitReached):
        repo.start_run(session, target_id=only.id, story_id="SCRUM-2", mode="full")


def test_an_app_that_is_busy_still_conflicts_when_the_tenant_is_within_its_caps(session):
    """The trio is untouched: with allowance to spare, a second run on a busy
    app is still the 409 it always was."""
    (only,) = _tenant_with_targets(session, 1, max_concurrent_runs=5)
    repo.start_run(session, target_id=only.id, story_id="SCRUM-1", mode="full")

    with pytest.raises(repo.RunConflict):
        repo.start_run(session, target_id=only.id, story_id="SCRUM-2", mode="full")


# --- what the monthly quota counts ----------------------------------------

def test_a_failed_run_still_spends_monthly_quota(session):
    """It spent a sandbox. A quota that only counted successes would make
    "retry until it works" free, which is the opposite of what a quota is."""
    a, b = _tenant_with_targets(session, 2, monthly_run_quota=1)

    run = repo.start_run(session, target_id=a.id, story_id="SCRUM-1", mode="full")
    repo.fail_run(session, run.id, "the agent wedged")

    with pytest.raises(repo.MonthlyQuotaExhausted):
        repo.start_run(session, target_id=b.id, story_id="SCRUM-2", mode="full")


def test_the_monthly_quota_resets_at_the_start_of_the_next_month(session):
    """A calendar month, not a rolling 30 days: the quota is counted from the
    first of the month, so the same tenant that was refused is free again."""
    a, b = _tenant_with_targets(session, 2, monthly_run_quota=1)

    first = repo.start_run(session, target_id=a.id, story_id="SCRUM-1", mode="full")
    repo.begin_run(session, first.id)
    repo.complete_run(session, first.id)

    with pytest.raises(repo.MonthlyQuotaExhausted):
        repo.start_run(session, target_id=b.id, story_id="SCRUM-2", mode="full")

    next_month = (lease.utcnow().replace(day=1) + timedelta(days=32)).replace(day=1)
    allowed = repo.start_run(
        session, target_id=b.id, story_id="SCRUM-2", mode="full", now=next_month
    )

    assert allowed.status is RunStatus.PENDING


def test_a_tenant_over_both_caps_is_told_about_the_monthly_one(session):
    """When both are breached the customer hears the one that is true for
    longer. "You are out of quota for this month" is actionable; "three runs are
    already going" would send them to stop a run, which would not help."""
    a, b = _tenant_with_targets(session, 2, max_concurrent_runs=1, monthly_run_quota=1)
    repo.start_run(session, target_id=a.id, story_id="SCRUM-1", mode="full")

    with pytest.raises(repo.MonthlyQuotaExhausted):
        repo.start_run(session, target_id=b.id, story_id="SCRUM-2", mode="full")


# --- a crashed run must not hold quota -----------------------------------

def test_a_crashed_run_does_not_hold_concurrency_quota(session):
    """The regression the quota check could introduce, and the reason the cap
    cannot simply count `status IN LIVE`.

    A run whose lease has lapsed and that is not paused is **crashed**:
    `start_run`'s own trio reaps it in place, three lines below the quota check.
    If the cap counted it, a tenant at its cap with one dead run would be
    refused 429 by the check *above* the trio that was about to free it -- and
    the restart that worked before this slice would stop working until the
    reaper came round, which is a 30-second loop that may not be running at all.
    "Self-clearing", which is what `ConcurrencyLimitReached` promises, has to
    mean this too.

    `live_run_holding` already settled what "genuinely live" means; this is the
    same question asked of a count, so it must give the same answer.
    """
    a, b = _tenant_with_targets(session, 2, max_concurrent_runs=1)

    t0 = lease.utcnow()
    repo.start_run(session, target_id=a.id, story_id="SCRUM-1", mode="full", now=t0)

    # Past the lease TTL: that run is crashed, not running.
    later = t0 + lease.DEFAULT_LEASE_TTL + timedelta(seconds=1)

    assert repo.tenant_usage(session, now=later).live_runs == 0
    # And so the cap is not held: this start must succeed.
    started = repo.start_run(
        session, target_id=b.id, story_id="SCRUM-2", mode="full", now=later
    )
    assert started.status is RunStatus.PENDING


def test_a_paused_run_does_hold_concurrency_quota(session):
    """The other half, and the reason this is not just "ignore lapsed leases":
    a paused run has **deliberately** cleared its lease and still owns its
    target (`reap_expired` skips it). It is live, and it counts."""
    a, b = _tenant_with_targets(session, 2, max_concurrent_runs=1)

    t0 = lease.utcnow()
    run = repo.start_run(session, target_id=a.id, story_id="SCRUM-1", mode="full", now=t0)
    repo.begin_run(session, run.id)
    repo.pause_run(session, run.id)

    later = t0 + lease.DEFAULT_LEASE_TTL + timedelta(seconds=1)

    assert repo.tenant_usage(session, now=later).live_runs == 1
    with pytest.raises(repo.ConcurrencyLimitReached):
        repo.start_run(session, target_id=b.id, story_id="SCRUM-2", mode="full", now=later)


# --- setting one cap must not clear the other -----------------------------

def test_setting_one_cap_leaves_the_other_alone(session):
    """`None` is a *value* here -- it means unmetered -- so it cannot also be
    the "not specified" default, or setting one cap silently un-meters the
    other. The only caller the docstring names is a console operator, who
    would not expect raising a concurrency cap to delete a monthly quota.
    """
    repo.set_tenant_caps(session, max_concurrent_runs=4, monthly_run_quota=40)

    repo.set_tenant_caps(session, max_concurrent_runs=2)

    caps = repo.tenant_caps(session)
    assert caps.max_concurrent_runs == 2
    assert caps.monthly_run_quota == 40


def test_a_cap_can_still_be_set_to_unmetered_explicitly(session):
    """And passing `None` on purpose must still mean "no cap", or there would be
    no way back to an unmetered plan."""
    repo.set_tenant_caps(session, max_concurrent_runs=4, monthly_run_quota=40)

    repo.set_tenant_caps(session, monthly_run_quota=None)

    caps = repo.tenant_caps(session)
    assert caps.max_concurrent_runs == 4
    assert caps.monthly_run_quota is None
