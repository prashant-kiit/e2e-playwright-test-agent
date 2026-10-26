"""A real container per run: the dispatch seam's one shipped implementation.

The API takes the app lock and writes the run row as it always has, and then
this starts a container that hydrates from the head revision, drives the
pipeline, commits revisions at step boundaries, collects artifacts and tears
down. The agent writing and executing code no longer shares a process tree, a
filesystem or an environment with the thing holding the control plane's
credentials.

**The Docker Engine API over its socket, by hand, rather than an SDK.** `httpx`
is already a dependency (delivery talks to GitHub with it) and the surface used
here is five calls, so a second HTTP client plus its transitive dependencies
would be a larger change to the API image than the feature. The socket mount
itself is a dev-stack-only compromise and says so at the point of the mount in
docker-compose.yml: anything that can talk to it is root on that host. It is
exactly what this seam exists to replace -- in production `Scheduler` is a K8s
Job or a Fargate task call, authenticated as the API's own identity, holding no
socket.

**Two containers per run, created together and destroyed together.** The run's
sandbox sits on an internal network with no default route; its only way out is
an allowlisting proxy built from *this* target's row, which is why the proxy is
per-run rather than shared -- a shared tunnel cannot answer "which run is
asking?" honestly. The handle is the sandbox's container name, and the proxy's
name is derived from it by the same rule, so one opaque string reaps both and an
SRE can still type it into `docker logs`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from .. import repo
from ..db import SessionLocal
from ..orchestrator.driver import SessionFactory
from ..target_config import config_of
from . import egress
from .env import sandbox_environment

log = logging.getLogger(__name__)

DEFAULT_SOCKET = "/var/run/docker.sock"
DEFAULT_IMAGE = "qa-sandbox:latest"
DEFAULT_PROXY_IMAGE = "qa-egress-proxy:latest"
DEFAULT_NETWORK = "qa-sandbox"
DEFAULT_EGRESS_NETWORK = "qa-egress"
PROXY_PORT = 3128

# A name a human can use: `docker logs qa-run-<run_key>` while it is alive.
RUN_PREFIX = "qa-run-"
PROXY_PREFIX = "qa-proxy-"


class DockerError(RuntimeError):
    """The daemon refused, or is not there. Reported as a dispatch failure, so
    the run ends `failed` naming it and the target is freed."""


def proxy_name_for(handle: str) -> str:
    """The proxy container beside the sandbox `handle` names.

    Derived rather than stored: two ids in one column, or a second column, would
    be two things that can disagree about which proxy belongs to which run.
    """
    return PROXY_PREFIX + handle.removeprefix(RUN_PREFIX)


@dataclass(frozen=True)
class DockerSettings:
    """Where the daemon is, what to run, and on which networks.

    Read from the environment once per scheduler so a test can build one
    explicitly without setting process-wide variables.
    """

    socket: str = DEFAULT_SOCKET
    image: str = DEFAULT_IMAGE
    network: str = DEFAULT_NETWORK
    proxy_image: str = DEFAULT_PROXY_IMAGE
    egress_network: str = DEFAULT_EGRESS_NETWORK
    # `host.docker.internal:host-gateway` and friends. Needed by the
    # Docker-backed tests, which reach a database published on the host rather
    # than one on the compose network.
    extra_hosts: tuple[str, ...] = ()
    # Off only where there is deliberately no egress control to test, which is
    # the container-path integration test. The compose stack always has it.
    with_proxy: bool = True

    @classmethod
    def from_env(cls) -> DockerSettings:
        hosts = os.environ.get("QA_SANDBOX_EXTRA_HOSTS", "")
        return cls(
            socket=os.environ.get("QA_DOCKER_SOCKET", DEFAULT_SOCKET),
            image=os.environ.get("QA_SANDBOX_IMAGE", DEFAULT_IMAGE),
            network=os.environ.get("QA_SANDBOX_NETWORK", DEFAULT_NETWORK),
            proxy_image=os.environ.get("QA_PROXY_IMAGE", DEFAULT_PROXY_IMAGE),
            egress_network=os.environ.get("QA_EGRESS_NETWORK", DEFAULT_EGRESS_NETWORK),
            extra_hosts=egress.host_list(hosts),
            with_proxy=os.environ.get("QA_SANDBOX_PROXY", "1") != "0",
        )


class DockerScheduler:
    """Starts and reaps a sandbox (and its proxy) through the Docker API."""

    def __init__(
        self,
        settings: DockerSettings | None = None,
        *,
        session_factory: SessionFactory = SessionLocal,
        resolve: egress.Resolver | None = None,
    ) -> None:
        self.settings = settings or DockerSettings.from_env()
        self._session_factory = session_factory
        # Injected for the same reason the write path injects it: the
        # public-address check is load-bearing, and a check whose outcome
        # depends on what a name resolves to today is a check nothing can test.
        self._resolve = resolve
        self._client: httpx.Client | None = None

    # --- the seam --------------------------------------------------------

    def dispatch(self, run_id: int) -> str:
        """Start a sandbox for this run and return its handle.

        Raises on anything that leaves no sandbox working: a missing image, a
        daemon that is not there, a refused quota, or a base URL that resolves
        somewhere a run may not reach. The launcher turns that into a `failed`
        run with the reason and frees the app lock, because a pending run with
        no sandbox is the state an operator cannot act on.
        """
        with self._session_factory() as session:
            run = repo.get_run(session, run_id)
            run_key = run.run_key
            cfg = config_of(run.target)

        allowlist = egress.build_allowlist(cfg)
        # The run-time half of the public-address rule. The name was checked
        # when the target was saved; this is the check for a name repointed
        # since, which is the DNS-rebinding case §6 names. The proxy checks it
        # again at connect time -- this one exists so the run fails *before* it
        # costs tokens, with a reason an operator can read.
        egress.resolve_public(egress.host_of(cfg.base_url), resolve=self._resolve)
        # A precondition of the sandbox, not of the proxy: it has to hold on the
        # `with_proxy=False` path too, which is why it is here and not beside
        # the egress network it is the counterpart to.
        self._require_sandbox_network()

        name = RUN_PREFIX + run_key
        self._remove(name)  # a resumed run reuses its key; no stale namesake
        proxy_url = None
        if self.settings.with_proxy:
            proxy_url = self._start_proxy(run_key, allowlist)

        env = sandbox_environment(run_id, cfg, proxy_url=proxy_url)
        try:
            self._create_and_start(
                name,
                image=self.settings.image,
                cmd=[str(run_id)],
                env=env,
                network=self.settings.network,
                labels={"qa.run_id": str(run_id), "qa.run_key": run_key},
            )
        except Exception:
            # Never leave a proxy behind for a sandbox that did not start: it
            # would hold a port and an allowlist for a run that will never use
            # either.
            if proxy_url:
                self._remove(proxy_name_for(name))
            raise
        log.info("dispatched sandbox %s for run %s", name, run_id)
        return name

    def destroy(self, handle: str) -> None:
        """Remove the sandbox and its proxy. Idempotent.

        Pause, stop and the reaper may all reach for the same handle, and a
        container that has already exited is the outcome each of them wanted.
        """
        self._remove(handle)
        self._remove(proxy_name_for(handle))

    # --- the proxy -------------------------------------------------------

    def _start_proxy(self, run_key: str, allowlist: tuple[str, ...]) -> str:
        """One allowlisting proxy for one run, on both networks.

        Created on the egress network and then connected to the sandbox
        network: the Engine API attaches one network at creation, and the order
        matters only in that the proxy must be able to resolve names on the way
        out, which is the network with a default route.
        """
        name = PROXY_PREFIX + run_key
        self._remove(name)
        self._ensure_egress_network()
        self._create_and_start(
            name,
            image=self.settings.proxy_image,
            cmd=[],
            env={
                "QA_EGRESS_ALLOWLIST": ",".join(allowlist),
                "QA_PROXY_PORT": str(PROXY_PORT),
            },
            network=self.settings.egress_network,
            labels={"qa.run_key": run_key, "qa.role": "egress-proxy"},
        )
        self._connect(self.settings.network, name)
        return f"http://{name}:{PROXY_PORT}"

    # --- the networks ----------------------------------------------------

    def _require_sandbox_network(self) -> None:
        """Fail unless the sandbox network already exists -- never create it.

        The counterpart to `_ensure_egress_network`, and the asymmetry between
        the two is deliberate. A network Docker creates by default is **not**
        `internal`, so inventing `qa-sandbox` here would give every sandbox a
        default route and remove the whole egress control -- silently, because
        nothing would fail. It would also carry none of the stores, so hydrate
        would fail anyway. A missing sandbox network is a broken stack, and the
        honest thing to do with it is say so, with the reason.

        Checked in `dispatch` rather than beside the proxy, because it is a
        precondition of the *sandbox* and must hold on the path that runs
        without a proxy too.
        """
        response = self._request("GET", f"/networks/{self.settings.network}")
        if response.status_code == 404:
            raise DockerError(
                f"the sandbox network {self.settings.network!r} does not exist. "
                "It is not created for you on purpose: a default network is not "
                "`internal`, so creating one would give every sandbox a default "
                "route and remove the egress control. Bring the stack up "
                "(`make up`), which declares it with `internal: true`."
            )

    def _ensure_egress_network(self) -> None:
        """Create the egress network if it is not there, idempotently.

        Compose *declares* `qa-egress` but never creates it: the only service
        attached to it is the `never-started` egress-proxy, and Compose skips
        the networks of a service a profile excludes. So on a laptop where the
        stack was brought up with `make up`, the first run dispatched would fail
        with "network qa-egress not found" -- which is #23's "no extra steps",
        broken.

        Safe to create, unlike the sandbox network: `qa-egress` is an ordinary
        bridge whose only job is to be a way out, and being a plain bridge is
        the whole of what it has to be. See `_require_sandbox_network`.
        """
        response = self._request("GET", f"/networks/{self.settings.egress_network}")
        if response.status_code != 404:
            return
        log.info("creating the egress network %s", self.settings.egress_network)
        created = self._request(
            "POST",
            "/networks/create",
            json={"Name": self.settings.egress_network, "Driver": "bridge"},
        )
        # 409 is another dispatch winning the race, which is success here.
        if created.status_code >= 400 and created.status_code != 409:
            raise DockerError(
                f"could not create the egress network "
                f"{self.settings.egress_network}: {_message(created)}"
            )

    # --- the Docker Engine API ------------------------------------------

    @property
    def client(self) -> httpx.Client:
        """A client over the daemon's unix socket, built on first use.

        Lazily, because `get_launcher` builds a scheduler per request and a
        request that never dispatches should not have opened a socket.
        """
        if self._client is None:
            self._client = httpx.Client(
                transport=httpx.HTTPTransport(uds=self.settings.socket),
                base_url="http://docker",
                timeout=30.0,
            )
        return self._client

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise DockerError(
                f"cannot reach the Docker daemon at {self.settings.socket}: {exc}"
            ) from exc
        return response

    def _create_and_start(
        self,
        name: str,
        *,
        image: str,
        cmd: list[str],
        env: dict[str, str],
        network: str,
        labels: dict[str, str],
    ) -> str:
        payload = {
            "Image": image,
            "Cmd": cmd,
            "Env": [f"{key}={value}" for key, value in sorted(env.items())],
            "Labels": labels,
            "HostConfig": {
                # Removed as soon as it exits, so a paused or finished run
                # leaves nothing behind to pay for. The log lives in Postgres
                # now (DESIGN.md §10), so a post-mortem does not need the
                # container -- which is what makes this affordable.
                "AutoRemove": True,
                "NetworkMode": network,
                # PID 1 that reaps: a browser leaves zombies otherwise.
                "Init": True,
                "ExtraHosts": list(self.settings.extra_hosts),
            },
            "NetworkingConfig": {"EndpointsConfig": {network: {}}},
        }
        created = self._request(
            "POST", "/containers/create", params={"name": name}, json=payload
        )
        if created.status_code == 404:
            raise DockerError(f"no such image: {image}")
        if created.status_code >= 400:
            raise DockerError(f"could not create {name}: {_message(created)}")
        container_id = created.json()["Id"]

        started = self._request("POST", f"/containers/{container_id}/start")
        if started.status_code >= 400:
            self._remove(container_id)
            raise DockerError(f"could not start {name}: {_message(started)}")
        return container_id

    def _connect(self, network: str, container: str) -> None:
        response = self._request(
            "POST", f"/networks/{network}/connect", json={"Container": container}
        )
        if response.status_code >= 400:
            raise DockerError(
                f"could not attach {container} to {network}: {_message(response)}"
            )

    def _remove(self, name_or_id: str) -> None:
        """Force-remove a container if it is there. A 404 is success."""
        response = self._request(
            "DELETE", f"/containers/{name_or_id}", params={"force": "true", "v": "true"}
        )
        if response.status_code not in (204, 404, 409):
            log.warning("removing %s: %s", name_or_id, _message(response))


def _message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message", response.text))
    except ValueError:
        return response.text
