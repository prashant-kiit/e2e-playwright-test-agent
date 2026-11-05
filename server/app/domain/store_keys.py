"""The layout of the object store: what lives under which key. P5-10 / #42.

One module so that "this tenant's storage" is a sentence with one answer, and
so the answer is not spread between the ingest that writes blobs, the sweep
that writes artifacts and the service that authorizes both.

    tenant/<tenant_id>/                     everything one tenant owns
    tenant/<tenant_id>/blobs/<sha256>       a revision's content-addressed file
    tenant/<tenant_id>/runs/<run_key>/...   one run's artifacts

**Why this module exists.** Blobs were already under the tenant prefix (story
31, DESIGN.md §9) and artifacts were not: they were keyed `<run_key>/<path>`,
and a run key is a timestamp, a slug and a random suffix with no tenant in it.
That was never a leak -- artifact rows carry `tenant_id` and are filtered by the
read guard, and the content route resolves the row before it touches the store
-- but it meant story 32's "purge that tenant's entire storage prefix" had no
single prefix to purge, and an operator could not answer "what does this tenant
have in the bucket?" from the bucket.

**The discriminator is the segment after the tenant prefix.** One bucket holds
both kinds and a run reaches for both through the same `Storage` protocol, so
every authorization has to decide which rule applies. It used to decide by
asking "does this start with the run key?", which worked because the two shapes
had nothing in common; now they share a prefix, so the question is `blobs/`
versus `runs/`. That is a better question anyway: it is a property of the
layout rather than of the caller's identity.

**The legacy shape is still readable, deliberately.** Expand then contract: a
deployment's existing objects keep resolving while the shape changes, because
an artifact is downloaded by the `s3_key` on its own row rather than by a key
rebuilt from parts. `python -m app.artifacts rekey` is what moves them, and
`LEGACY_ARTIFACT_KEY` is how the authorization recognises one until it has run.
Nothing writes the old shape any more.
"""

from __future__ import annotations

import re

# `tenant/<id>/runs/<run_key>/<relpath>` -- the shape this module introduced.
# Anchored, because it is used to authorize and a partial match would be a
# prefix check with extra steps.
_ARTIFACT_KEY = re.compile(r"^tenant/(?P<tenant>\d+)/runs/(?P<run_key>[^/]+)(?:/(?P<rel>.+))?$")

# `<run_key>/<relpath>` -- what P5-10 replaced. A run key has no slashes in it,
# so the first segment is the whole of it.
LEGACY_ARTIFACT_KEY = re.compile(r"^(?P<run_key>[^/]+)(?:/(?P<rel>.+))?$")


def tenant_prefix(tenant_id: int) -> str:
    """Everything one tenant owns, and the whole of it.

    The string story 32's purge enumerates and deletes. It ends in a slash on
    purpose: `tenant/1` is a prefix of `tenant/11`, and a purge that dropped
    the separator would take another customer's storage with it. That is not a
    hypothetical -- S3 `Prefix` is a byte comparison, not a path walk.
    """
    return f"tenant/{tenant_id}/"


def blobs_prefix(tenant_id: int) -> str:
    return f"{tenant_prefix(tenant_id)}blobs/"


def blob_key(tenant_id: int, sha256: str) -> str:
    """`tenant/<tenant_id>/blobs/<sha256>` (DESIGN.md §9).

    Content addressing is scoped per tenant deliberately: cross-tenant dedup is
    worth nothing (different customers' tests do not collide) and would make
    blob existence a side channel.
    """
    return f"{blobs_prefix(tenant_id)}{sha256}"


def run_artifacts_prefix(tenant_id: int, run_key: str) -> str:
    """One run's evidence, which is the unit a run may read and write."""
    return f"{tenant_prefix(tenant_id)}runs/{run_key}/"


def artifact_key(tenant_id: int, run_key: str, rel: str) -> str:
    """Where one of a run's artifacts lives."""
    return f"{run_artifacts_prefix(tenant_id, run_key)}{rel}"


def legacy_run_prefix(run_key: str) -> str:
    """`<run_key>/` -- where a run's artifacts lived before P5-10.

    Needed by the tenant purge rather than by anything that writes: an object
    left under the old shape sits *outside* the tenant prefix, so a purge that
    swept only `tenant/<id>/` would leave it behind for ever. The purge derives
    these from its own `runs` rows while they still exist.
    """
    return f"{run_key}/"


def legacy_artifact_key(run_key: str, rel: str) -> str:
    """The pre-P5-10 shape. **Only for tests and the rekey command.**

    Kept as a named function rather than an f-string at those two call sites so
    that "who still writes the old shape?" is answerable by looking at who
    calls this -- and the answer is: the thing that migrates away from it, and
    the tests that prove it still reads.
    """
    return f"{run_key}/{rel}" if rel else run_key


def is_blob_key(key: str) -> bool:
    """Whether `key` is in some tenant's blob space.

    Deliberately not "is it *this* tenant's": that is an authorization
    question, and this is the classification that decides which authorization
    rule applies (app/control/service.py). Conflating the two is how a check
    ends up answering a question nobody asked.
    """
    return re.fullmatch(r"tenant/\d+/blobs/[^/]+", key) is not None


def artifact_run_key(key: str) -> str | None:
    """The run `key` belongs to, under either shape, or None if it is a blob.

    One function for both shapes because every caller wants the same answer --
    "whose artifact is this?" -- and a caller that had to ask twice is a caller
    that will one day ask once.
    """
    if is_blob_key(key):
        return None
    current = _ARTIFACT_KEY.match(key)
    if current is not None:
        return current.group("run_key")
    # Anything else that is not a blob key: the legacy shape, whose first
    # segment is the run key. A key with no slash at all is a run's own prefix.
    legacy = LEGACY_ARTIFACT_KEY.match(key)
    return None if legacy is None else legacy.group("run_key")
