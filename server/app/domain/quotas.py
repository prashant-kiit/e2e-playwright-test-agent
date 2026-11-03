"""A tenant's plan limits, and whether one more run fits inside them.

The decision only, with no database in it: `repo.start_run` counts, this says
what the counts mean. Pure because the interesting cases are arithmetic at a
boundary -- at the cap, one under, one over, and unmetered -- and those are
worth testing without a schema.

**`None` means no cap.** Not "nothing allowed", which is the reading that would
turn an unconfigured tenant into one that cannot run anything. A tenant whose
plan is unmetered says so by holding no number, and `breach()` answers `None`
for it without counting anything against it.

Two separate limits because they are two separate conversations with the
customer. Being at the concurrency cap is **temporary and self-clearing**: a
live run will finish and the next start succeeds, so the remedy is to wait or
to stop a run. Being out of monthly quota is **not**: nothing the customer does
to their running work frees any, and the remedy is a bigger plan or next month.
Telling someone to wait when waiting cannot help is the failure this
distinction exists to prevent -- which is why the breach carries which one it
was, rather than one "over quota" for both.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class QuotaKind(str, Enum):
    """Which limit was reached. The portal renders a different sentence per
    member, so this is the thing a rejection has to carry."""

    CONCURRENCY = "concurrency"
    MONTHLY = "monthly"


@dataclass(frozen=True)
class Caps:
    """What a tenant's plan allows. `None` for either is no cap on that one."""

    max_concurrent_runs: int | None = None
    monthly_run_quota: int | None = None

    @property
    def unmetered(self) -> bool:
        return self.max_concurrent_runs is None and self.monthly_run_quota is None


@dataclass(frozen=True)
class Usage:
    """What the tenant has spent: live runs now, and runs started this month.

    Both counted across every one of the tenant's apps, because both caps are
    the tenant's rather than any app's.
    """

    live_runs: int = 0
    runs_this_month: int = 0


def at_concurrency_cap(caps: Caps, usage: Usage) -> bool:
    """Whether another run would exceed the concurrent-run cap.

    `>=` rather than `>`, because `usage` is what has been spent *before* the
    run being asked about: a tenant with 2 live runs and a cap of 2 is already
    full, and the next run would be the third. `None` is no cap, so never full.
    """
    return caps.max_concurrent_runs is not None and usage.live_runs >= caps.max_concurrent_runs


def at_monthly_quota(caps: Caps, usage: Usage) -> bool:
    """Whether another run would exceed this calendar month's quota."""
    return (
        caps.monthly_run_quota is not None
        and usage.runs_this_month >= caps.monthly_run_quota
    )


@dataclass(frozen=True)
class Breach:
    """A cap that one more run would exceed, and the numbers to say so with.

    Carries `limit` and `used` alongside the kind because every caller needs
    all three together and only this function knows which pair goes with which
    kind. Returning the kind alone meant the caller immediately switched on it
    again to pick the matching numbers out of `caps` and `usage` -- the same
    decision made twice, in two places that could disagree.
    """

    kind: QuotaKind
    limit: int
    used: int


def breach(caps: Caps, usage: Usage) -> Breach | None:
    """Which cap to *refuse* an enqueue with, or `None` if one more run fits.

    One breach, not a set, because this answers "what do we tell the person who
    just pressed Start?" and that is one sentence. The portal's usage panel
    asks the two predicates above instead -- both caps can be full at once, and
    a meter that read empty because the *other* meter was also full would be
    simply wrong. That is the distinction between the two surfaces: a rejection
    has one reason, a dashboard has two gauges.

    **Monthly is checked first, and the order is the point rather than an
    accident.** A tenant that is both at its concurrency cap *and* out of
    monthly quota gets told the thing that is true for longer: "you are out of
    quota until December" is actionable, where "three runs are already going"
    would send them to stop a run and try again, which cannot possibly work.
    Reporting the temporary problem while a permanent one is also present is
    the specific failure this ordering prevents.
    """
    if at_monthly_quota(caps, usage):
        # The casts are safe: `at_*` is false whenever the cap is None.
        return Breach(
            QuotaKind.MONTHLY,
            limit=caps.monthly_run_quota,  # type: ignore[arg-type]
            used=usage.runs_this_month,
        )
    if at_concurrency_cap(caps, usage):
        return Breach(
            QuotaKind.CONCURRENCY,
            limit=caps.max_concurrent_runs,  # type: ignore[arg-type]
            used=usage.live_runs,
        )
    return None
