"""The gateway that reaches the service over the internal API.

What a sandbox uses. It is handed a base URL and a run-scoped token by the
environment its container was built with (app/sandbox/env.py) and it is the only
way out of that container to the control plane: there is no `DATABASE_URL` and
no `S3_*` any more, and the stores are not on the sandbox's network at all.

**`httpx`, and no retries.** `httpx` is already a dependency (delivery talks to
GitHub with it, and app/sandbox/docker.py talks to the Docker socket with it), so
this adds nothing to the image. Retries are deliberately absent: every operation
here is either idempotent-by-construction (a status transition the service
refuses twice, a content-addressed blob) or part of the ingest that must fail the
run if it cannot complete, and a retry loop in here would turn "the control plane
is down" into a run that hangs for the length of the wall clock instead of
failing with the reason. The one thing that *is* tolerant is the log emitter,
because losing a log line must never fail a run -- and that tolerance lives in
the bus, where the rest of the best-effort rules are.

**It does not verify its own token, and cannot.** See the note in `__init__`:
the key stays in the control plane, so the server is the only verifier. A
malformed token still fails here, at construction, rather than on the first
operation -- but a *forged* one fails at the API, which is where it should.

**Errors arrive as exceptions the run-side code already handles.** A 403 or a
401 becomes `NotAuthorized`, a run that ended under the sandbox becomes
`RunNotLive`, and anything else becomes `ControlPlaneError`. That is what lets
the launcher and the driver be written against one set of failures rather than
against two transports' worth.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import httpx

from ..domain.steps import Step
from ..run_token import RunScope, read_unverified
from .model import HeadRevision, RunFacts, RunState, StoredArtifact, TrackedBlob
from .service import ControlPlaneError, NotAuthorized, RunNotLive

# Long enough for a blob upload on a slow link, short enough that a control
# plane that has gone away fails the run rather than holding it to the wall
# clock. Reads are the same number: the longest single read is one blob.
DEFAULT_TIMEOUT_S = 120.0

# The status code the service's `RunNotLive` arrives as, distinguished from the
# other 403s by the body. The split matters because a run stopped by an operator
# is the ordinary end of a run and must not be reported as a broken deployment.
_NOT_LIVE_MARKER = "no longer authorizes anything"


class HttpGateway:
    """A `RunGateway` that calls the internal API."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        # **Read, not verified.** A sandbox holds no signing key -- it must not,
        # since a key would let it mint a token for any run of any tenant -- so
        # it cannot check its own token and this would raise on every real run if
        # it tried. What it needs from the claims is addressing: the run id goes
        # in every URL below, and the tenant id is how ingest builds its blob
        # keys. The control plane verifies the signature on every request and
        # refuses a scope that does not match the row, so claims a sandbox
        # tampered with would only address requests it is then refused.
        self._scope = read_unverified(token)
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=DEFAULT_TIMEOUT_S)
        self._headers = {"Authorization": f"Bearer {token}"}

    @property
    def scope(self) -> RunScope:
        return self._scope

    # --- the transport ---------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._base}/internal/runs/{self._scope.run_id}{path}"

    def _check(self, response: httpx.Response) -> httpx.Response:
        """Turn a refusal into the exception the run-side code expects."""
        if response.is_success:
            return response
        body = response.text[:500]
        if response.status_code in (401, 403):
            if _NOT_LIVE_MARKER in body:
                raise RunNotLive(body)
            raise NotAuthorized(f"{response.status_code}: {body}")
        raise ControlPlaneError(f"{response.status_code}: {body}")

    def _get(self, path: str) -> dict:
        return self._check(
            self._client.get(self._url(path), headers=self._headers)
        ).json()

    def _post(self, path: str, body: dict | None = None) -> dict:
        response = self._check(
            self._client.post(self._url(path), headers=self._headers, json=body or {})
        )
        return response.json() if response.content else {}

    # --- reads -----------------------------------------------------------

    def run_facts(self) -> RunFacts:
        return RunFacts.from_dict(self._get("/facts"))

    def run_state(self) -> RunState:
        return RunState.from_dict(self._get("/state"))

    def run_status(self) -> str:
        return self._get("/status")["status"]

    def head_revision(self) -> HeadRevision | None:
        raw = self._get("/head-revision")["revision"]
        return None if raw is None else HeadRevision.from_dict(raw)

    def artifacts(self) -> tuple[StoredArtifact, ...]:
        return tuple(
            StoredArtifact.from_dict(raw) for raw in self._get("/artifacts")["artifacts"]
        )

    # --- blobs -----------------------------------------------------------

    def blob_exists(self, key: str) -> bool:
        response = self._client.head(self._url(f"/blobs/{key}"), headers=self._headers)
        if response.status_code == 404:
            return False
        self._check(response)
        return True

    def read_blob(self, key: str) -> tuple[Iterator[bytes], str]:
        """Stream a blob back.

        Buffered rather than streamed, and that is a deliberate limitation worth
        naming: `httpx`'s streaming response must be closed inside a `with`, and
        the `Storage` protocol hands its caller a bare iterator with no such
        lifetime. Tracked files are source files and the largest artifact a run
        fetches is its own session tarball, so the memory is bounded by one file
        rather than by a revision. Streaming end to end would mean changing the
        `Storage` protocol to return a context manager, which is a change to
        every caller for a benefit no current caller needs.
        """
        response = self._check(
            self._client.get(self._url(f"/blobs/{key}"), headers=self._headers)
        )
        content_type = response.headers.get(
            "content-type", "application/octet-stream"
        )
        return iter([response.content]), content_type

    def write_blob(
        self, key: str, path: Path, content_type: str | None = None
    ) -> None:
        headers = dict(self._headers)
        if content_type:
            headers["Content-Type"] = content_type
        with path.open("rb") as fh:
            self._check(
                self._client.put(self._url(f"/blobs/{key}"), headers=headers, content=fh)
            )

    # --- writes ----------------------------------------------------------

    def begin_run(self) -> None:
        self._post("/begin")

    def complete_run(self) -> None:
        self._post("/complete")

    def fail_run(self, reason: str) -> None:
        self._post("/fail", {"reason": reason})

    def pause_run(self) -> None:
        self._post("/pause")

    def stop_run(self) -> None:
        self._post("/stop")

    def start_step(self, step: Step) -> None:
        self._post(f"/steps/{step.value}/start")

    def complete_step(self, step: Step) -> None:
        self._post(f"/steps/{step.value}/complete")

    def fail_step(self, step: Step) -> None:
        self._post(f"/steps/{step.value}/fail")

    def set_session_id(self, session_id: str) -> None:
        self._check(
            self._client.put(
                self._url("/session-id"),
                headers=self._headers,
                json={"session_id": session_id},
            )
        )

    def clear_session_id(self) -> None:
        self._check(
            self._client.put(
                self._url("/session-id"),
                headers=self._headers,
                json={"session_id": None},
            )
        )

    def heartbeat(self) -> None:
        self._post("/heartbeat")

    def record_cost(self, *, spend_usd: float, sandbox_seconds: int) -> None:
        self._post(
            "/cost",
            {"spend_usd": spend_usd, "sandbox_seconds": sandbox_seconds},
        )

    def commit_revision(
        self, files: Sequence[TrackedBlob], *, author: str
    ) -> int | None:
        return self._post(
            "/revisions",
            {"files": [f.as_dict() for f in files], "author": author},
        )["rev"]

    def index_artifact(
        self, *, key: str, sha256: str, kind: str, step: Step | None
    ) -> int:
        return self._post(
            "/artifacts",
            {
                "key": key,
                "sha256": sha256,
                "kind": kind,
                "step": step.value if step else None,
            },
        )["version"]

    def publish_log(self, lines: Sequence[str]) -> None:
        self._post("/logs", {"lines": list(lines)})

