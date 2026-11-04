"""Every operation a run may perform, and the one place each is authorized.

This module is what replaced `DATABASE_URL` and the `S3_*` credentials in a
sandbox. Before P5-05 a run held the control plane's own authority and was
trusted not to misuse it; now it holds a token naming one run, one target and one
tenant (app/run_token.py), and everything it can do is a function in here that
starts by checking that token against the row it names.

**`authorized_run` is the boundary, and it is one function on purpose.** Every
operation below calls it first. Five operations each doing their own three checks
is how one of them ends up doing two, and the missing check would be invisible
to every behavioural test -- the same argument app/delivery/tools.py makes for
binding and marking-invalid in one context manager.

What it checks, and why each one is load-bearing:

- **the tenant**, by reading the run *inside* the scope's tenant (`acting_as`),
  so P5-02's enforced read filter is what answers "is this my run?" rather than
  a comparison this module could forget. A scope naming another tenant's run
  finds nothing.
- **the target**, because the target is what bounds the tree a run may commit
  to. A scope pairing a run with a target it does not belong to is not a weaker
  token but an inconsistent one, and is refused rather than resolved in either
  direction.
- **liveness**, because the token is stateless and therefore cannot be revoked
  (app/run_token.py says so, and this is the other half of that trade). Expiry
  is the backstop; this is the gate. A token for a finished run is worthless the
  moment the run finishes, however long its signature has left.

A **paused** run is still live here, and `is_live` is still the whole of the
status gate: it is the definition the whole repository uses
(app/domain/status.py, and `repo.live_run_holding` turns on it), and a second
definition of "live" would be a second thing that can be wrong. That was once
the end of the paragraph, and it left a hole (#48, story 22): a token copied
before a pause kept authorizing that run's config, blobs, revisions and
uploads for as long as the pause lasted, which is unbounded, while the sandbox
it was minted for had been destroyed at the instant of the pause.

What closes it is the **sandbox attempt**, a fourth field on the scope and a
counter on the run. The gate is not asking "is this run over?" -- `is_live` answers that
-- but "is the sandbox this token was minted for still the one doing the
work?". `repo.pause_run` moves the counter on, so:

    during the pause     the old token names attempt N, the run is on N+1
    after the resume     still N+1, so the old token does not come back to
                         life along with the run -- which is the half a status
                         check cannot do, because a resumed run is RUNNING
                         again and looks exactly like the one that was paused

It is deliberately **not** done by refusing a paused run, though that was the
first thing tried: a resumed sandbox calls `run_facts` *before* `begin_run`
has moved the row out of PAUSED, so refusing a paused run refuses the resume
itself. The counter has no such ordering to get wrong.

A token table would have closed this too, and is still the cost app/auth.py
declines to pay for sessions. This is one integer on a row that is already
read on every call.

The three exempt operations below are unaffected, and that is load-bearing
rather than incidental: a sandbox being torn down at a pause still flushes its
last log lines and still records what it spent, and the exemptions are what let
it. See `scoped_run`.

**Nothing here trusts a key it is handed**, and the three blob operations are
authorized *differently* because they leak differently. A blob key is a content
hash, so it is guessable and shareable, and the tenant prefix alone is too
coarse -- it would let one target's run read or overwrite another target's tree.

    read    the key must be referenced by a revision of **this run's target**
            (`revisions.blob_is_referenced_by_target`). This is #30's "every
            blob read authorized through a Postgres row belonging to the
            requesting tenant -- no serve-by-key-alone", and the row also pins
            the *target*, which is what the token actually names.
    write   the uploaded bytes must hash to the key. Content addressing makes
            that necessary and sufficient: a run can only write bytes that
            already match the key, so writing over another target's blob is a
            no-op rather than a poisoning. A prefix rule would not have caught
            it -- and `commit_revision` confirms blobs *exist*, not what is in
            them, so this is the check standing between a shared content-address
            space and one run corrupting another target's revision.
    exists  the tenant prefix, deliberately. It is ingest's dedup check, asked
            about a key the run derived from content it is holding -- so the
            answer tells it only whether its own tenant already stores bytes it
            already has, which is not a side channel. Requiring a row would
            break dedup, which exists precisely to skip blobs no revision of
            this target references yet.

Artifact keys are `<run_key>/<path>` and are authorized by prefix on all three,
because a run owns that prefix outright and artifacts are not content-addressed.
"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Iterator, Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import prompt_store, repo, revisions
from ..domain.status import is_live
from ..domain.steps import Step
from ..models import Artifact, Run
from ..run_token import RunScope
from ..storage import Storage
from ..target_config import config_of
from ..tenancy import current_tenant_id, tenant_scope
from .model import (
    HeadRevision,
    RunFacts,
    RunState,
    StoredArtifact,
    TrackedBlob,
)


class ControlPlaneError(Exception):
    """A run asked for something it may not have, or that is not there."""


class NotAuthorized(ControlPlaneError):
    """The scope does not authorize this. The routes answer 403.

    Deliberately the same exception whether the run does not exist, belongs to
    another tenant, or belongs to another target: a sandbox probing run ids must
    not be able to tell "no such run" from "not yours", because the difference
    is exactly the information it would be probing for.
    """


class RunNotLive(NotAuthorized):
    """The run is over, so its token no longer authorizes anything.

    A subclass rather than a sibling, because every caller that handles
    `NotAuthorized` wants this handled the same way -- and because the one place
    that does care (the sandbox, deciding whether to keep trying) wants to tell
    "my run ended" from "my token is wrong", which is what the distinct type is
    for.
    """


@contextlib.contextmanager
def acting_as(scope: RunScope) -> Iterator[None]:
    """Bind `scope`'s tenant for the duration of the block.

    Every entry point wraps its call in this: the routes do it after verifying
    the bearer token, and `LocalGateway` does it per call. It serves both halves
    of tenancy at once -- the enforced read filter is what refuses another
    tenant's run, and every row the run writes (its revisions, its step rows,
    its log lines) is attributed to its own tenant rather than the resolver's
    default. It is the only such seam on the run path: the thread path's
    `launcher._run_tenant_scope` did this job until P5-05, and both paths now
    bind their tenant here, from the scope the run-scoped token carries.
    """
    with tenant_scope(scope.tenant_id):
        yield


def scoped_run(session: Session, scope: RunScope) -> Run:
    """The scope's run, checked against the row but **not** against liveness.

    The three checks that hold for ever: the caller is acting as the scope's
    tenant, the run is that tenant's, and the run belongs to the scope's target.
    What is missing is the liveness gate, which is why this is not the thing
    operations call -- `authorized_run` is.

    **Three operations use this deliberately, and they are the whole list**
    (`authorized_run` below is the fourth caller, and it is the gate itself):

    - `run_status`, because the sandbox entrypoint reads it *after* the run ends
      to choose its exit code;
    - `record_cost`, because it is recorded in a `finally` about a run that has
      just finished, and would otherwise be refused on every successful run;
    - `publish_log`, because the last lines a run emits are emitted after its
      final status transition -- `=== run <key> completed ===`, the teardown
      line, the session and cost lines -- and those are the lines an operator
      reads first. Gating them cost a container-path debugging session: every
      line appeared except the ones that said how the run ended.

    None of the three is a weakening of the gate, because none of them can
    change a run's work: one is a read of one field, one writes two accounting
    columns, and one appends to an append-only log belonging to the run the
    token names.
    What the gate exists to stop is a finished run's token being used to commit a
    revision, drive a status or upload an artifact -- and all of those still go
    through `authorized_run`.

    **The residual exposure, stated rather than implied.** A token leaked from a
    *finished* run can still append log lines to that run and rewrite its two
    cost columns, until its signature expires (`run_token.ttl_s`). Of the three,
    `record_cost` is the one that is not forced by ordering -- it could have been
    recorded control-plane-side at teardown instead of by the sandbox in its
    `finally`. It is here because moving it would split `drive_run`'s "every way
    out of a run records what it cost" across two processes, and the thing being
    traded away is two accounting columns on a run that is already over. That is
    a deliberate trade and not an oversight, which is the only reason it is
    written down here.
    """
    if current_tenant_id() != scope.tenant_id:
        # A caller that forgot `acting_as`. Raised rather than silently entering
        # the scope here, because the write path depends on the ambient tenant
        # too: a read that quietly fixed itself would leave the *writes* in this
        # request attributed to whatever tenant was bound, which is a
        # misattribution rather than a leak and therefore worse.
        raise NotAuthorized(
            f"the acting tenant is {current_tenant_id()}, not the scope's "
            f"{scope.tenant_id}; the caller did not enter acting_as()"
        )
    try:
        run = repo.get_run(session, scope.run_id)
    except repo.NotFound as exc:
        raise NotAuthorized(f"no run {scope.run_id} for this token") from exc
    if run.target_id != scope.target_id:
        raise NotAuthorized(
            f"run {scope.run_id} does not belong to target {scope.target_id}"
        )
    return run


def authorized_run(session: Session, scope: RunScope) -> Run:
    """The run `scope` authorizes, or raise. The boundary; see the module docstring.

    `scoped_run` plus the liveness gate, and deliberately nothing else: writing
    the three checks out again here would be the thing this module's docstring
    argues against two paragraphs up ("five operations each doing their own
    three checks is how one of them ends up doing two"), with the three exempt
    operations as the fifth caller.
    """
    run = scoped_run(session, scope)
    if not is_live(run.status):
        raise RunNotLive(
            f"run {scope.run_id} is {run.status.value}; its token no longer "
            f"authorizes anything"
        )
    if run.sandbox_attempt != scope.sandbox_attempt:
        # The run's *current* attempt is deliberately not in the message. This
        # class's own docstring says a sandbox probing must not be able to tell
        # one refusal from another, and the current attempt is a fact about the
        # run as it is now -- which is exactly what the holder of a superseded
        # token has stopped being entitled to. Its own attempt is something it
        # already knows.
        raise RunNotLive(
            f"run {scope.run_id} is no longer on attempt "
            f"{scope.sandbox_attempt}; its sandbox is gone and this token no "
            f"longer authorizes anything"
        )
    return run


# --- what a run reads ----------------------------------------------------

def run_facts(session: Session, scope: RunScope) -> RunFacts:
    """The run's immutable facts and its target's configuration, in one read.

    The target configuration comes through here rather than from a route of its
    own because a sandbox holds exactly one target's tree: "the target" is never
    a question a run asks, it is part of what the run *is*.
    """
    run = authorized_run(session, scope)
    return RunFacts(
        run_id=run.id,
        run_key=run.run_key,
        app=run.target.app,
        story_id=run.story_id,
        mode=run.mode,
        status=run.status,
        last_completed_step=run.last_completed_step,
        claude_session_id=run.claude_session_id,
        target=config_of(run.target),
        # Exactly the versions the run row pins, not whatever the tenant's
        # current head is: `pinned` refuses to substitute, so the bodies served
        # here are the bodies the recorded revs name. That is what makes
        # "the recorded version matches what ran" structural (P5-06).
        #
        # A read, deliberately: `prompt_store.resolve_all` would seed missing
        # rows, and a sandbox's request must not write a tenant's prompts
        # mid-run. A run from before the column simply has none to serve.
        prompts=(
            prompt_store.pinned(session, run.prompt_revs)
            if run.prompt_revs
            # A run from before the column: there is no pinned version to look
            # up, and the shipped files are exactly what it was given when it
            # started. Served at the seed rev rather than left empty, so the
            # runner never has to decide what to do without prompts.
            else prompt_store.shipped_at_seed_rev()
        ),
    )


def run_state(session: Session, scope: RunScope) -> RunState:
    """The fields the driver re-reads at each step boundary."""
    run = authorized_run(session, scope)
    return RunState(
        status=run.status,
        stop_requested=run.stop_requested,
        pause_requested=run.pause_requested,
        claude_session_id=run.claude_session_id,
    )


def run_status(session: Session, scope: RunScope) -> str:
    """The run's status, for a caller that only needs the exit code.

    Deliberately **not** gated on liveness: the sandbox entrypoint reads this
    *after* the run has ended in order to choose its exit code. It is a
    one-field read of a row the scope already names, so answering it costs
    nothing an attacker wants. See `scoped_run`.
    """
    return scoped_run(session, scope).status.value


def head_revision(session: Session, scope: RunScope) -> HeadRevision | None:
    """The target's head revision and its file index, or None if it has none.

    None rather than a raise: "this target has no revision" is hydrate's
    `NoHeadRevision`, and the sandbox is the side that turns it into a failed
    run with that reason, exactly as it did when it read the row itself.
    """
    authorized_run(session, scope)
    head = revisions.head_revision(session, scope.target_id)
    if head is None:
        return None
    return revisions.revision_view(session, head)


def list_artifacts(session: Session, scope: RunScope) -> tuple[StoredArtifact, ...]:
    """This run's artifact index: what the collector dedups against."""
    run = authorized_run(session, scope)
    rows = session.scalars(select(Artifact).where(Artifact.run_id == run.id))
    return tuple(
        StoredArtifact(key=row.s3_key, sha256=row.sha256, version=row.version)
        for row in rows
    )


# --- keys: a run may name its own tenant's blobs and its own run's artifacts --

def authorize_blob_key(scope: RunScope, key: str) -> None:
    """Refuse a blob key outside the scope's tenant prefix.

    The cheap half, and on its own **not** enough: it bounds the key to one
    tenant's content-address space, which is where `blob_exists` stops (see the
    module docstring) and where reads and writes do not. The prefix is derived
    from the same function that builds the keys so the two cannot disagree about
    the layout.
    """
    prefix = revisions.blob_key(scope.tenant_id, "")
    if not key.startswith(prefix) or "/" in key[len(prefix) :]:
        raise NotAuthorized(f"blob key {key!r} is not this tenant's to name")


def authorize_artifact_key(scope: RunScope, run_key: str, key: str) -> None:
    """Refuse an artifact key outside this run's own prefix.

    Artifact keys are `<run_key>/<path>` (app/artifacts.py), so one run's
    evidence is one prefix, and a run may read and write only its own. `..` is
    refused rather than normalized: the key is about to be handed to an object
    store that has no notion of a parent directory, so a key containing one is a
    caller doing something it has not explained.
    """
    if key != run_key and not key.startswith(f"{run_key}/"):
        raise NotAuthorized(f"artifact key {key!r} is not this run's to name")
    if ".." in key.split("/"):
        raise NotAuthorized(f"artifact key {key!r} walks out of its own prefix")


def _is_artifact_key(run_key: str, key: str) -> bool:
    """Whether `key` is in this run's artifact prefix rather than a blob key.

    One bucket holds both and a run reaches for both through the same `Storage`
    protocol, so every operation has to decide which rule applies. Decided by
    the run's own prefix rather than by the blob prefix, because `run_key` is
    exact: a key under it is this run's artifact and a key that is not is a blob
    key to be judged as one.
    """
    return key == run_key or key.startswith(f"{run_key}/")


def blob_exists(session: Session, scope: RunScope, store: Storage, key: str) -> bool:
    """Whether the store already holds `key`. Ingest's dedup check.

    Authorized by prefix alone, and the module docstring says why that is not a
    gap: a run asks about a key it derived from content it is holding.
    """
    run = authorized_run(session, scope)
    if _is_artifact_key(run.run_key, key):
        authorize_artifact_key(scope, run.run_key, key)
    else:
        authorize_blob_key(scope, key)
    return store.exists(key)


def read_blob(
    session: Session, scope: RunScope, store: Storage, key: str
) -> tuple[Iterator[bytes], str]:
    """Stream `key` back. Hydrate's blob fetch, and the session archive's.

    A blob is authorized by a **row**: it must be referenced by a revision of
    this run's target. That is the half a prefix cannot do -- see the module
    docstring -- and it is why knowing a content hash is not enough.
    """
    run = authorized_run(session, scope)
    if _is_artifact_key(run.run_key, key):
        authorize_artifact_key(scope, run.run_key, key)
    else:
        authorize_blob_key(scope, key)
        if not revisions.blob_is_referenced_by_target(session, scope.target_id, key):
            raise NotAuthorized(
                f"blob {key} is not referenced by any revision of this run's "
                f"target, so this token does not authorize reading it"
            )
    return store.get_stream(key)


def write_blob(
    session: Session,
    scope: RunScope,
    store: Storage,
    key: str,
    path: Path,
    content_type: str | None = None,
) -> None:
    """Store `path`'s bytes under `key`. Ingest's upload, and the artifact sweep's.

    A blob's bytes must hash to its key. Content addressing makes that the whole
    check: the only bytes a run may write under a blob key are the bytes that key
    already names, so an upload aimed at another target's blob writes what is
    already there. Without it, a shared per-tenant content-address space plus a
    `commit_revision` that confirms existence rather than content would let one
    run poison another target's revision -- the one way this seam could corrupt
    data it is not allowed to read.
    """
    run = authorized_run(session, scope)
    if _is_artifact_key(run.run_key, key):
        authorize_artifact_key(scope, run.run_key, key)
    else:
        authorize_blob_key(scope, key)
        digest = _sha256_of(path)
        expected = revisions.sha256_from_blob_key(key)
        if digest != expected:
            raise NotAuthorized(
                f"blob {key} names content {expected} but these bytes hash to "
                f"{digest}; a blob key is a content hash and may not be written "
                f"with anything else"
            )
    store.put_file(key, path, content_type)


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- what a run writes ---------------------------------------------------

def begin_run(session: Session, scope: RunScope) -> None:
    repo.begin_run(session, authorized_run(session, scope).id)


def complete_run(session: Session, scope: RunScope) -> None:
    repo.complete_run(session, authorized_run(session, scope).id)


def fail_run(session: Session, scope: RunScope, reason: str) -> None:
    repo.fail_run(session, authorized_run(session, scope).id, reason)


def pause_run(session: Session, scope: RunScope) -> None:
    repo.pause_run(session, authorized_run(session, scope).id)


def stop_run(session: Session, scope: RunScope) -> None:
    repo.stop_run(session, authorized_run(session, scope).id)


def start_step(session: Session, scope: RunScope, step: Step) -> None:
    repo.start_step(session, authorized_run(session, scope).id, step)


def complete_step(session: Session, scope: RunScope, step: Step) -> None:
    repo.complete_step(session, authorized_run(session, scope).id, step)


def fail_step(session: Session, scope: RunScope, step: Step) -> None:
    repo.fail_step(session, authorized_run(session, scope).id, step)


def set_session_id(session: Session, scope: RunScope, session_id: str) -> None:
    repo.set_session_id(session, authorized_run(session, scope).id, session_id)


def clear_session_id(session: Session, scope: RunScope) -> None:
    repo.clear_session_id(session, authorized_run(session, scope).id)


def heartbeat(session: Session, scope: RunScope) -> None:
    """Refresh the run's lease.

    Ungated beyond `authorized_run`, which already refuses a run that is not
    live -- which is also exactly the behaviour `heartbeat_during` wants: it
    stops quietly once the run is over rather than treating it as an error.
    """
    repo.heartbeat(session, authorized_run(session, scope).id)


def record_cost(
    session: Session,
    scope: RunScope,
    *,
    spend_usd: float,
    sandbox_seconds: int,
) -> None:
    """What the run spent. Recorded in a `finally`, so it must tolerate a run
    that has just become terminal: it uses `scoped_run`, which that function's
    docstring lists as one of its four deliberate callers."""
    repo.record_run_cost(
        session,
        scoped_run(session, scope).id,
        spend_usd=spend_usd,
        sandbox_seconds=sandbox_seconds,
    )


def commit_revision(
    session: Session,
    scope: RunScope,
    store: Storage,
    files: Sequence[TrackedBlob],
    *,
    author: str,
) -> int | None:
    """Commit revision N+1 of the run's target. Returns the new `rev`, or None.

    None when the manifest's tree hash already matches the head, which is the
    ordinary case: three of the five pipeline steps routinely change no tracked
    file (app/launcher.py's `make_ingest` says why that matters).

    **The tree hash is recomputed here, not accepted.** The sandbox sends a
    manifest of paths and content hashes; this derives the tree hash from it with
    the same function the write path uses. A sandbox therefore cannot record a
    revision whose stored hash does not describe its own file list -- which is
    the thing delivery's "we pushed the revision we recorded" proof rests on.

    **Every blob is confirmed present before the row is written.** Ingest uploads
    its blobs and then commits, and over a network those are separate requests:
    without this check a dropped upload would be recorded as a revision whose
    hydrate fails later, on a different run, with a missing-blob error pointing
    at nothing. `revisions.commit_revision` gets this for free by doing both
    halves in one process; the split path has to ask.
    """
    run = authorized_run(session, scope)
    for file in files:
        key = revisions.blob_key(scope.tenant_id, file.sha256)
        if not store.exists(key):
            raise ControlPlaneError(
                f"the blob for {file.path!r} ({key}) is not in the store, so "
                f"this revision would reference bytes nobody has"
            )
    revision = revisions.record_revision(
        session,
        run.target,
        [(f.path, f.sha256, f.size) for f in files],
        author=author,
        produced_by_run_id=run.id,
    )
    return None if revision is None else revision.rev


def index_artifact(
    session: Session,
    scope: RunScope,
    *,
    key: str,
    sha256: str,
    kind: str,
    step: Step | None,
) -> int:
    """Record one uploaded artifact, versioning a key this run already has.

    Returns the row's version. The rule is the collector's and the session
    archive's, and it is one rule in one place for the reason both of them say:
    one row per (run, key), its version bumped when the content changes, so a
    paused run resumed three times has one session artifact at version three
    rather than three artifacts.
    """
    run = authorized_run(session, scope)
    authorize_artifact_key(scope, run.run_key, key)
    row = session.scalars(
        select(Artifact).where(Artifact.run_id == run.id, Artifact.s3_key == key)
    ).one_or_none()
    if row is None:
        row = Artifact(
            tenant_id=scope.tenant_id,
            run_id=run.id,
            step=step.value if step else None,
            kind=kind,
            s3_key=key,
            sha256=sha256,
            version=1,
        )
        session.add(row)
    elif row.sha256 != sha256:
        row.version += 1
        row.sha256 = sha256
        row.step = step.value if step else row.step
    session.commit()
    session.refresh(row)
    return row.version


def publish_log(session: Session, scope: RunScope, lines: Sequence[str]) -> None:
    """Append log lines for this run.

    A sequence rather than a line, because this is the one operation a run
    performs in volume and each one was a round trip on the container path. The
    emitter batches; the ordering within a batch is the order it was given.

    **Not gated on liveness**, and that is the interesting part: the last lines
    a run emits come *after* its final status transition, so a gate here silently
    drops exactly the lines that say how the run ended. See `scoped_run`.

    **There is no `close_log`, deliberately.** `PostgresLogBus.close` is already
    a no-op and says why: a Postgres-backed stream ends when the run's status
    says it has ended, because that is the only end-of-stream marker a reader in
    another process can see, and a sentinel row would be a second way to say
    what the run row already says. A run in a container writes through here and
    is read through that same bus, so there is nothing for a close to do -- and a
    route that did nothing would be a route somebody later made do something.
    """
    from ..orchestrator.bus import PostgresLogBus

    run = scoped_run(session, scope)
    bus = PostgresLogBus(session_factory=lambda: BorrowedSession(session))
    for line in lines:
        bus.publish(run.id, line)


class BorrowedSession:
    """Lend an open session to something that wants to open its own.

    `PostgresLogBus` takes a session *factory* and uses it as a context manager,
    because on its own it owns short transactions (app/orchestrator/bus.py). Here
    the surrounding request already has a session and owns it, so this hands it
    over without letting the borrower close it.

    Public, and reused by the suite (`tests/control_helpers.py`), because the
    tests need exactly this shape for exactly this reason and a second copy is a
    second `__exit__` to get wrong. It also matters more there than here: a test
    that takes a *second* connection instead gets two fixture teardowns, and the
    second one's `TRUNCATE` waits for ever on the first one's open transaction.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def __enter__(self) -> Session:
        return self._session

    def __exit__(self, *_exc) -> bool:
        return False
