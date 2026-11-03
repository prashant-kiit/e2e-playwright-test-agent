"""The dev stack's own reachability invariants.

`make up` is the only way most people meet this system, and a store that is
*running* but unreachable is the worst shape a dependency can take: compose
reports healthy, nothing logs an error, and every run fails in hydrate instead.

P4 made that shape reachable by putting the stores on two networks -- the
control plane (the API) and the sandbox network (a run's container) -- because
hydrate and ingest happen inside a sandbox now. A server that binds one
interface therefore had a side to be absent from.

**P5-05 removed that second network**, which removes the trap rather than
fixing it: a sandbox reaches the API's internal control-plane routes and the
stores are not on its network at all. The flag stays, and so does its test,
because the host still publishes 8333 and "binds one interface" is never what
is wanted for a store -- but the thing it was protecting against is now
structurally absent, and the test below says which is doing the work.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parent


@pytest.fixture()
def compose() -> dict:
    return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())


def test_the_stores_are_on_the_control_plane_network_only(compose):
    """P5-05's deployment half: the stores are unreachable from a sandbox.

    Not because a connection would be refused, but because there is no route
    and no name. A sandbox is given neither a connection string nor an endpoint
    (server/tests/test_sandbox_credentials.py), and the stores are not on its
    network -- so even a run that guessed a hostname would resolve nothing.
    """
    for service in ("seaweedfs", "postgres"):
        networks = compose["services"][service]["networks"]
        assert networks == ["default"], (service, networks)


def test_the_api_is_on_the_sandbox_network_because_a_run_must_reach_it(compose):
    """What replaced the stores there. A run does its reads and writes through
    the internal control-plane routes, so the API is the one host it can
    resolve -- and the network still has no default route, so it is the only
    one it can reach without the proxy."""
    assert "sandbox" in compose["services"]["api"]["networks"]
    assert compose["networks"]["sandbox"]["internal"] is True


def test_the_sandbox_network_carries_nothing_but_the_api(compose):
    """The blast radius of a compromised run, as a list of hostnames.

    A long-lived service quietly added to this network would be reachable from
    every tenant's agent, which is the kind of change that looks like
    convenience in a diff. Its own test, so the list has to be edited
    deliberately.
    """
    on_sandbox_network = sorted(
        name
        for name, service in compose["services"].items()
        if "sandbox" in (service.get("networks") or [])
    )

    assert on_sandbox_network == ["api"], on_sandbox_network


def test_the_object_store_binds_every_interface(compose):
    """SeaweedFS binds **one** address, and this container has two. Without
    `-ip.bind=0.0.0.0` the S3 port comes up on whichever network it picked and
    is a closed socket on the other -- observed as the API and the host's
    published port both losing the store while `docker compose ps` said
    healthy, because the healthcheck curls localhost and localhost is always
    bound.

    Postgres needs no such flag: its image binds 0.0.0.0 already. This is the
    one service whose default is per-interface, which is exactly why the flag
    looks removable to someone tidying the command line.

    P5-05 put the store back on a single network, so the two-interface trap is
    no longer reachable -- but the host still publishes 8333, so binding one
    interface is still wrong, and the flag is still what makes it right.
    """
    command = compose["services"]["seaweedfs"]["command"]
    assert "-ip.bind=0.0.0.0" in command, command
