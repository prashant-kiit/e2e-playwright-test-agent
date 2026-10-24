"""What a run can reach, as two functions.

"What can this run reach?" has to be answerable by reading **one** place, so the
allowlist is built by one function from the target's own row, and one predicate
decides whether an address is public. That predicate is the cloud-metadata
block, the RFC1918 block and the run-time half of the DNS-rebinding check all at
once -- which is why it is worth its own tests rather than being three checks in
three places.

Neither function needs a network or a container, which is why they are built and
tested before either exists. Resolution is **injected**: a test that depends on
what `example.com` resolves to today is a test that fails on a train.
"""

from __future__ import annotations

import pytest

from app.sandbox import egress
from app.target_config import TargetConfig


def _config(base_url: str = "https://shop.example.com") -> TargetConfig:
    return TargetConfig(
        app="demo",
        name="Demo",
        base_url=base_url,
        locators="",
        agent_notes=(),
        target_repo="o/r",
        target_branch="master",
    )


def _resolver(mapping: dict[str, list[str]]):
    """A resolver over a fixed table. An unknown name does not resolve."""

    def resolve(host: str) -> list[str]:
        try:
            return mapping[host]
        except KeyError as exc:
            raise egress.ResolutionError(f"{host} does not resolve") from exc

    return resolve


# --- the allowlist: the target's host, Anthropic, npm, and nothing else ----

def test_the_allowlist_is_the_targets_host_the_api_and_the_registry():
    assert egress.build_allowlist(_config()) == (
        "shop.example.com",
        egress.ANTHROPIC_API_HOST,
        egress.NPM_REGISTRY_HOST,
    )


def test_a_port_in_the_base_url_does_not_become_part_of_the_host():
    assert egress.build_allowlist(_config("http://shop.example.com:3000"))[0] == (
        "shop.example.com"
    )


def test_the_targets_own_host_is_allowed():
    allowlist = egress.build_allowlist(_config())
    assert egress.allows(allowlist, "shop.example.com")


def test_another_targets_host_is_not_allowed():
    """A run against one target structurally cannot reach another's."""
    allowlist = egress.build_allowlist(_config())
    assert not egress.allows(allowlist, "bank.example.com")


def test_a_subdomain_of_an_allowed_host_is_not_allowed():
    """Allowlisting a suffix would allow every name somebody can register under
    it; the entry is a host, and a host is compared whole."""
    allowlist = egress.build_allowlist(_config())
    assert not egress.allows(allowlist, "evil.shop.example.com")
    assert not egress.allows(allowlist, "shop.example.com.attacker.test")


def test_the_host_comparison_ignores_case_and_a_trailing_dot():
    allowlist = egress.build_allowlist(_config())
    assert egress.allows(allowlist, "SHOP.example.com")
    assert egress.allows(allowlist, "shop.example.com.")


def test_the_agent_runtimes_telemetry_hosts_are_not_in_the_allowlist():
    """They are disabled by environment instead, so the allowlist stays the
    length of what a run genuinely needs."""
    allowlist = egress.build_allowlist(_config())
    for host in ("statsig.anthropic.com", "sentry.io", "o1158394.ingest.sentry.io"):
        assert not egress.allows(allowlist, host), host


# --- the public-address rule ----------------------------------------------

@pytest.mark.parametrize(
    "address",
    [
        "169.254.169.254",  # the cloud metadata endpoint
        "10.0.0.5",         # RFC1918
        "172.16.4.1",
        "192.168.1.1",
        "127.0.0.1",        # loopback
        "0.0.0.0",
        "::1",
        "fd00::1",          # unique local
        "fe80::1",          # link-local
        "100.64.0.1",       # carrier-grade NAT, shared address space
        "224.0.0.1",        # multicast
    ],
)
def test_an_address_a_run_must_not_reach_is_not_public(address):
    assert not egress.is_public_address(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "1.1.1.1", "2606:4700::1111"])
def test_a_routable_address_is_public(address):
    assert egress.is_public_address(address)


def test_a_name_resolving_publicly_passes():
    resolve = _resolver({"shop.example.com": ["93.184.216.34"]})
    assert egress.resolve_public("shop.example.com", resolve=resolve) == [
        "93.184.216.34"
    ]


def test_a_name_resolving_to_a_private_address_is_refused():
    resolve = _resolver({"internal.example.com": ["10.1.2.3"]})
    with pytest.raises(egress.PrivateAddress) as exc:
        egress.resolve_public("internal.example.com", resolve=resolve)
    assert "10.1.2.3" in str(exc.value)


def test_a_name_resolving_to_the_metadata_endpoint_is_refused():
    resolve = _resolver({"metadata.example.com": ["169.254.169.254"]})
    with pytest.raises(egress.PrivateAddress):
        egress.resolve_public("metadata.example.com", resolve=resolve)


def test_a_loopback_name_is_refused():
    resolve = _resolver({"localhost": ["127.0.0.1"]})
    with pytest.raises(egress.PrivateAddress):
        egress.resolve_public("localhost", resolve=resolve)


def test_one_private_address_among_several_refuses_the_name():
    """A name that resolves to both is the DNS-rebinding shape itself; taking
    the public answer and ignoring the other would be the bug."""
    resolve = _resolver({"both.example.com": ["93.184.216.34", "10.0.0.1"]})
    with pytest.raises(egress.PrivateAddress):
        egress.resolve_public("both.example.com", resolve=resolve)


def test_a_name_that_does_not_resolve_is_refused_as_such():
    """Distinguished from a private answer: one is a typo, the other is an
    attempt to reach the inside, and an operator should be told which."""
    with pytest.raises(egress.ResolutionError):
        egress.resolve_public("nope.example.com", resolve=_resolver({}))


def test_a_literal_private_ip_as_the_host_is_refused_without_resolving():
    """Nothing to resolve, and the answer is already in the name."""
    resolve = _resolver({})
    with pytest.raises(egress.PrivateAddress):
        egress.resolve_public("169.254.169.254", resolve=resolve)


def test_a_literal_public_ip_as_the_host_passes():
    assert egress.resolve_public("93.184.216.34", resolve=_resolver({})) == [
        "93.184.216.34"
    ]
