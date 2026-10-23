"""Lease math for the per-app run lock.

A live run holds its app's lock and must keep extending a lease (heartbeat). If
the process crashes the lease expires and a reaper frees the app, so a dead run
can never wedge an app forever. This module is pure time arithmetic; the reaper
and the lock table live in the repository layer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# Defaults: heartbeat every 15s, lease lives 60s. A run is considered dead once
# it has missed several heartbeats, which tolerates brief pauses/GC stalls.
DEFAULT_HEARTBEAT = timedelta(seconds=15)
DEFAULT_LEASE_TTL = timedelta(seconds=60)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_expiry(now: datetime | None = None, ttl: timedelta = DEFAULT_LEASE_TTL) -> datetime:
    """Compute a fresh lease expiry (used on acquire and on every heartbeat)."""
    return (now or utcnow()) + ttl


def is_expired(expires_at: datetime, now: datetime | None = None) -> bool:
    """True once the lease has lapsed. A dead-run reaper acts on these."""
    return (now or utcnow()) >= _aware(expires_at)


def _aware(dt: datetime) -> datetime:
    """Treat a naive datetime (e.g. read back from the DB) as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
