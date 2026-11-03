"""The protocol the run-side code calls, and the `Storage` adapter over it.

This is what replaced the pair `(session_factory, store)` everywhere a run used
them. The driver, the launcher, hydrate, ingest, the artifact collector and the
session archive all talk to one of these instead of to Postgres and S3, which is
what let `DATABASE_URL` and the `S3_*` credentials leave the sandbox.

**Why a protocol and not a base class.** Two implementations ship -- `LocalGateway`
(the service in this process) and `HttpGateway` (the service over the internal
API) -- and they are two transports for one set of operations rather than two
behaviours. A protocol says that: there is nothing to inherit, because there is
no shared behaviour, only a shared shape. `tests/test_control_gateway.py` runs
one suite against both, which is the thing that keeps the shape honest.

**The operations are named after what a run does, not after the rows.** `repo`
has ninety functions; a run performs about twenty operations. Naming the
protocol after the operations is what makes "what can a sandbox do?" a question
with a readable answer -- it is this file -- and it is the list the token's blast
radius is measured against.

**`GatewayStorage` is the one adapter.** Hydrate's `materialize`, ingest's blob
upload, the artifact sweep and the session archive all already speak the
`Storage` protocol (app/storage.py), and they are good code that should not have
to know a network appeared underneath it. So each gateway implements three blob
primitives and this turns them into a `Storage`. The important consequence is
that the *thread* path goes through the same key authorization as the container
path: a `LocalGateway` handing back the raw `S3Storage` would have left
`authorize_blob_key` untested on the path the whole suite runs on, which is how
that rule would have quietly stopped holding.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..domain.steps import Step
from ..run_token import RunScope
from ..storage import content_type_for
from .model import HeadRevision, RunFacts, RunState, StoredArtifact, TrackedBlob


@runtime_checkable
class RunGateway(Protocol):
    """Everything a run may ask of the control plane, and nothing else."""

    @property
    def scope(self) -> RunScope:
        """The run, target and tenant this gateway is bound to.

        A property rather than an argument on every call: a gateway is built for
        one run, and a run id threaded through twenty methods is twenty chances
        for it to disagree with the token.
        """

    # --- reads -----------------------------------------------------------

    def run_facts(self) -> RunFacts: ...
    def run_state(self) -> RunState: ...

    def run_status(self) -> str:
        """The run's status after it has ended, for the entrypoint's exit code.

        The one read a token outlives its run to perform; see
        `service.run_status`.
        """

    def head_revision(self) -> HeadRevision | None: ...
    def artifacts(self) -> tuple[StoredArtifact, ...]: ...

    # --- blobs: the three primitives `GatewayStorage` is built from ------

    def blob_exists(self, key: str) -> bool: ...
    def read_blob(self, key: str) -> tuple[Iterator[bytes], str]: ...
    def write_blob(
        self, key: str, path: Path, content_type: str | None = None
    ) -> None: ...

    # --- writes ----------------------------------------------------------

    def begin_run(self) -> None: ...
    def complete_run(self) -> None: ...
    def fail_run(self, reason: str) -> None: ...
    def pause_run(self) -> None: ...
    def stop_run(self) -> None: ...

    def start_step(self, step: Step) -> None: ...
    def complete_step(self, step: Step) -> None: ...
    def fail_step(self, step: Step) -> None: ...

    def set_session_id(self, session_id: str) -> None: ...
    def clear_session_id(self) -> None: ...

    def heartbeat(self) -> None: ...
    def record_cost(self, *, spend_usd: float, sandbox_seconds: int) -> None: ...

    def commit_revision(
        self, files: Sequence[TrackedBlob], *, author: str
    ) -> int | None: ...

    def index_artifact(
        self, *, key: str, sha256: str, kind: str, step: Step | None
    ) -> int: ...

    def publish_log(self, lines: Sequence[str]) -> None:
        """Append a batch of log lines.

        There is no `close_log`: see `service.publish_log`. The bus's own
        `close` stays a no-op, so `drive_run`'s `finally` is unchanged.
        """


class GatewayStorage:
    """The `Storage` protocol, served by a gateway's three blob primitives.

    So that `hydrate.materialize`, `revisions.upload_blobs`, the artifact sweep
    and the session archive keep the interface they already had -- and keep
    going through the control plane's key authorization while they do.
    """

    def __init__(self, gateway: RunGateway) -> None:
        self._gateway = gateway

    def ensure_bucket(self) -> None:
        """A no-op: a run has no business creating buckets.

        The control plane's own `S3Storage.ensure_bucket` still runs on the
        write paths that create targets, so the bucket exists long before any
        run reaches for it. A sandbox asking for one would be asking for an
        operation its token does not name.
        """

    def put_file(
        self, key: str, path: Path, content_type: str | None = None
    ) -> None:
        self._gateway.write_blob(key, path, content_type or content_type_for(key))

    def get_stream(self, key: str) -> tuple[Iterator[bytes], str]:
        return self._gateway.read_blob(key)

    def exists(self, key: str) -> bool:
        return self._gateway.blob_exists(key)
