"""The dev stack's own reachability invariants.

`make up` is the only way most people meet this system, and a store that is
*running* but unreachable is the worst shape a dependency can take: compose
reports healthy, nothing logs an error, and every run fails in hydrate instead.

P4 made that shape reachable by putting the stores on two networks -- the
control plane (the API) and the sandbox network (a run's container) -- because
hydrate and ingest happen inside a sandbox now. A server that binds one
interface therefore has a side to be absent from.
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


def test_the_object_store_is_on_both_networks(compose):
    """The premise of the test below: hydrate reads blobs from inside a sandbox
    and the API serves them to the portal, so both sides need the store."""
    networks = compose["services"]["seaweedfs"]["networks"]
    assert "default" in networks and "sandbox" in networks, networks


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
    """
    command = compose["services"]["seaweedfs"]["command"]
    assert "-ip.bind=0.0.0.0" in command, command
