"""The gateway that reaches the service in this process.

What the thread path uses (`QA_SANDBOX=thread`: CI, development, and every
existing test that drives a run). It opens a short session per operation, the
way the driver always did, and calls the same `service.py` functions the internal
API's routes call.

**It presents a real token, and the service really checks it.** That is the
whole point of this implementation existing rather than the thread path keeping
its old direct `repo` calls: the scope check, the target check and the liveness
gate are exercised by the suite that runs on every commit, not only by the
Docker-backed test. A `LocalGateway` built for run 7 cannot act on run 8, and a
test can say so without a container.

What this path does **not** exercise is the framing -- JSON, status codes,
streaming -- which is what tests/test_internal_api.py covers directly and what
tests/test_control_gateway.py pins by running one suite through both gateways.

**A session per operation, not one for the run.** Copied deliberately from the
driver's original shape (app/orchestrator/driver.py: "each DB touch is a short
transaction, which keeps the lease fresh and avoids holding a transaction open
across a long-running step"). A gateway that held one session for the life of a
run would hold a transaction open across `npm ci` and across every agent step,
which is the thing that comment exists to prevent. It also makes the two
transports agree on a subtler point: an HTTP request cannot share a transaction
with the next one either, so anything that depended on it would work on one path
and not the other.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from ..db import SessionFactory
from ..domain.steps import Step
from ..run_token import RunScope, verify
from ..storage import Storage
from . import service
from .model import HeadRevision, RunFacts, RunState, StoredArtifact, TrackedBlob


class LocalGateway:
    """A `RunGateway` backed by the service, a session factory and a store."""

    def __init__(
        self,
        token: str,
        *,
        session_factory: SessionFactory,
        store: Storage,
    ) -> None:
        # Verified here rather than trusted: this is the one line that makes the
        # thread path's authority come from the same token the container path
        # carries. A `LocalGateway` built from a scope directly would be a
        # second, unauthenticated way in -- and the suite would then be proving
        # the behaviour of a path that does not ship.
        self._scope = verify(token)
        self._session_factory = session_factory
        self._store = store

    @property
    def scope(self) -> RunScope:
        return self._scope

    # --- reads -----------------------------------------------------------

    def run_facts(self) -> RunFacts:
        with service.acting_as(self._scope), self._session_factory() as s:
            return service.run_facts(s, self._scope)

    def run_state(self) -> RunState:
        with service.acting_as(self._scope), self._session_factory() as s:
            return service.run_state(s, self._scope)

    def run_status(self) -> str:
        with service.acting_as(self._scope), self._session_factory() as s:
            return service.run_status(s, self._scope)

    def head_revision(self) -> HeadRevision | None:
        with service.acting_as(self._scope), self._session_factory() as s:
            return service.head_revision(s, self._scope)

    def artifacts(self) -> tuple[StoredArtifact, ...]:
        with service.acting_as(self._scope), self._session_factory() as s:
            return service.list_artifacts(s, self._scope)

    # --- blobs -----------------------------------------------------------

    def blob_exists(self, key: str) -> bool:
        with service.acting_as(self._scope), self._session_factory() as s:
            return service.blob_exists(s, self._scope, self._store, key)

    def read_blob(self, key: str) -> tuple[Iterator[bytes], str]:
        with service.acting_as(self._scope), self._session_factory() as s:
            chunks, content_type = service.read_blob(
                s, self._scope, self._store, key
            )
            # Drained inside the session, because the caller is handed an
            # iterator and will consume it after this block has closed. A lazy
            # stream over a closed session works for `FakeStorage` and fails for
            # a real one, which is the kind of difference that shows up only in
            # the stack that matters.
            return iter([b"".join(chunks)]), content_type

    def write_blob(
        self, key: str, path: Path, content_type: str | None = None
    ) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.write_blob(s, self._scope, self._store, key, path, content_type)

    # --- writes ----------------------------------------------------------

    def begin_run(self) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.begin_run(s, self._scope)

    def complete_run(self) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.complete_run(s, self._scope)

    def fail_run(self, reason: str) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.fail_run(s, self._scope, reason)

    def pause_run(self) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.pause_run(s, self._scope)

    def stop_run(self) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.stop_run(s, self._scope)

    def start_step(self, step: Step) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.start_step(s, self._scope, step)

    def complete_step(self, step: Step) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.complete_step(s, self._scope, step)

    def fail_step(self, step: Step) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.fail_step(s, self._scope, step)

    def set_session_id(self, session_id: str) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.set_session_id(s, self._scope, session_id)

    def clear_session_id(self) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.clear_session_id(s, self._scope)

    def heartbeat(self) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.heartbeat(s, self._scope)

    def record_cost(self, *, spend_usd: float, sandbox_seconds: int) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.record_cost(
                s,
                self._scope,
                spend_usd=spend_usd,
                sandbox_seconds=sandbox_seconds,
            )

    def commit_revision(
        self, files: Sequence[TrackedBlob], *, author: str
    ) -> int | None:
        with service.acting_as(self._scope), self._session_factory() as s:
            return service.commit_revision(
                s, self._scope, self._store, files, author=author
            )

    def index_artifact(
        self, *, key: str, sha256: str, kind: str, step: Step | None
    ) -> int:
        with service.acting_as(self._scope), self._session_factory() as s:
            return service.index_artifact(
                s, self._scope, key=key, sha256=sha256, kind=kind, step=step
            )

    def publish_log(self, lines: Sequence[str]) -> None:
        with service.acting_as(self._scope), self._session_factory() as s:
            service.publish_log(s, self._scope, lines)
