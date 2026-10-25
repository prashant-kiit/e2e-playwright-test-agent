"""The proxy's decision, and the refusal a sandbox actually meets.

The policy is three rules applied to a host name (`proxy.decide`), so it is
tested as a function: the rule that matters most is about addresses nobody can
register, and a test that needed a real `169.254.169.254` to prove the metadata
block would be a test nobody could run.

What is deliberately **not** here is the happy path end to end. Allowing a host
means opening a tunnel to a public address, and a test that could do that in
process would have to subvert the one predicate under test -- so "the allowed
hosts are reachable and nothing else is" is proven by the Docker-backed test
(tests/test_docker_sandbox.py), because the control being tested there is the
network and not the function.
"""

from __future__ import annotations

import asyncio

import pytest

from app.sandbox import proxy

ALLOWLIST = ("shop.example.com", "api.anthropic.com", "registry.npmjs.org")


def _resolver(mapping: dict[str, list[str]]):
    def resolve(host: str) -> list[str]:
        try:
            return mapping[host]
        except KeyError as exc:
            raise proxy.egress.ResolutionError(f"{host} does not resolve") from exc

    return resolve


PUBLIC = _resolver(
    {
        "shop.example.com": ["93.184.216.34"],
        "api.anthropic.com": ["93.184.216.35"],
        "registry.npmjs.org": ["93.184.216.36"],
        "evil.example.com": ["93.184.216.37"],
        "rebound.example.com": ["10.0.0.7"],
    }
)


# --- the three rules -----------------------------------------------------

def test_an_allowlisted_host_that_resolves_publicly_is_allowed():
    decision = proxy.decide("shop.example.com", ALLOWLIST, resolve=PUBLIC)
    assert decision.allowed
    assert decision.address == "93.184.216.34"


def test_a_host_that_is_not_on_this_runs_allowlist_is_refused():
    decision = proxy.decide("evil.example.com", ALLOWLIST, resolve=PUBLIC)
    assert not decision.allowed
    assert "allowlist" in decision.reason


def test_another_targets_host_is_refused_even_though_it_is_a_real_site():
    """The allowlist is built from one target's row, so one run's proxy cannot
    be used to reach another customer's app."""
    decision = proxy.decide("bank.example.com", ALLOWLIST, resolve=PUBLIC)
    assert not decision.allowed


def test_an_allowlisted_host_that_now_resolves_privately_is_refused():
    """The run-time half of the DNS-rebinding check: a name repointed after it
    was saved does not become an internal request."""
    allowlist = ("rebound.example.com",)
    decision = proxy.decide("rebound.example.com", allowlist, resolve=PUBLIC)
    assert not decision.allowed
    assert "10.0.0.7" in decision.reason


def test_the_metadata_endpoint_is_refused_even_if_somebody_allowlists_it():
    """Two rules, not one: being on the allowlist is not permission to reach a
    link-local address."""
    decision = proxy.decide("169.254.169.254", ("169.254.169.254",), resolve=PUBLIC)
    assert not decision.allowed


def test_an_empty_allowlist_refuses_everything():
    """The right failure for a misconfigured dispatch: a proxy with no
    allowlist is a closed door, not an open one."""
    assert not proxy.decide("shop.example.com", (), resolve=PUBLIC).allowed


def test_the_tunnel_is_opened_to_the_address_that_was_verified():
    """Resolving twice is how a name that passed the check becomes a connection
    to somewhere it did not."""
    decision = proxy.decide("shop.example.com", ALLOWLIST, resolve=PUBLIC)
    assert decision.address == "93.184.216.34"


def test_the_allowlist_comes_from_the_environment_the_scheduler_set(monkeypatch):
    monkeypatch.setenv("QA_EGRESS_ALLOWLIST", "a.example.com, b.example.com ,")
    assert proxy.allowlist_from_env() == ("a.example.com", "b.example.com")


def test_an_unset_allowlist_is_empty_rather_than_permissive(monkeypatch):
    monkeypatch.delenv("QA_EGRESS_ALLOWLIST", raising=False)
    assert proxy.allowlist_from_env() == ()


# --- reading a proxy request --------------------------------------------

@pytest.mark.parametrize(
    "line,expected",
    [
        ("CONNECT shop.example.com:443 HTTP/1.1", ("CONNECT", "shop.example.com", 443)),
        ("CONNECT shop.example.com HTTP/1.1", ("CONNECT", "shop.example.com", 443)),
        ("GET http://shop.example.com/x HTTP/1.1", ("GET", "shop.example.com", 80)),
        ("GET http://shop.example.com:8080/x HTTP/1.1", ("GET", "shop.example.com", 8080)),
        ("POST https://api.anthropic.com/v1 HTTP/1.1", ("POST", "api.anthropic.com", 443)),
    ],
)
def test_the_host_is_read_from_the_request_line(line, expected):
    assert proxy.target_of(line) == expected


@pytest.mark.parametrize("line", ["GET /relative HTTP/1.1", "garbage", ""])
def test_a_request_that_is_not_a_proxy_request_is_not_one(line):
    assert proxy.target_of(line) is None


def test_userinfo_in_the_uri_does_not_hide_the_host():
    """`http://shop.example.com@evil.example.com/` names evil, and the policy is
    about the host a connection is opened to."""
    assert proxy.target_of("GET http://user@evil.example.com/ HTTP/1.1") == (
        "GET",
        "evil.example.com",
        80,
    )


# --- the refusal, over a real socket ------------------------------------

def _ask(port: int, request_line: str) -> str:
    async def go() -> str:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"{request_line}\r\nHost: x\r\n\r\n".encode())
        await writer.drain()
        data = await reader.read(4096)
        writer.close()
        return data.decode("latin-1")

    return asyncio.run(go())


@pytest.fixture()
def running_proxy():
    """The server itself, on a loopback port, with a fixed resolver."""
    loop = asyncio.new_event_loop()
    # `rebound.example.com` is on this allowlist deliberately: the refusal
    # worth proving over a socket is the second rule, not the first.
    server = loop.run_until_complete(
        proxy.serve(
            ALLOWLIST + ("rebound.example.com",),
            port=0,
            host="127.0.0.1",
            resolve=PUBLIC,
        )
    )
    port = server.sockets[0].getsockname()[1]

    import threading

    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield port
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    server.close()
    loop.close()


def test_a_disallowed_host_is_refused_with_a_reason_an_agent_can_report(running_proxy):
    """Not a timeout: an agent that was refused should be able to say so."""
    response = _ask(running_proxy, "CONNECT evil.example.com:443 HTTP/1.1")

    assert response.startswith("HTTP/1.1 403")
    assert "allowlist" in response


def test_a_private_resolving_host_is_refused_over_the_socket_too(running_proxy):
    response = _ask(running_proxy, "CONNECT rebound.example.com:443 HTTP/1.1")

    assert response.startswith("HTTP/1.1 403")
    assert "10.0.0.7" in response


def test_something_that_is_not_a_proxy_request_is_a_400(running_proxy):
    response = _ask(running_proxy, "GET /health HTTP/1.1")

    assert response.startswith("HTTP/1.1 400")
