"""What a run is allowed to reach, and what no run may reach.

**Two decisions, each in one place.** §6 asks for default-deny egress with a
per-run allowlist; a reviewer asking "what can this run reach?" should be able
to answer it by reading one function, and an operator asking "why was this
refused?" should find one predicate. The rest of the module -- `host_of`,
`allows`, `is_public_address`, `system_resolver` -- is what those two are built
from, and is here so that neither has a second implementation anywhere.

    build_allowlist(cfg)        the target's registered host, the Anthropic API,
                                the npm registry. Nothing else.
    resolve_public(host, ...)   refuse any name that resolves to a private,
                                link-local or loopback address.

The second one is the cloud-metadata-endpoint block, the RFC1918 block and the
run-time half of the DNS-rebinding check all at once, and it belongs in the one
process that resolves -- which, in the sandbox network, is the proxy
(app/sandbox/proxy.py). It is also what the **write path** calls when a target's
base URL is saved (app/target_config.py), so an operator is told while they are
still around to fix it rather than hours later when a run fails.

**Resolution is injected.** The proxy and the write path pass `system_resolver`;
tests pass a table. A check whose result depends on what a name resolves to
today is a check that cannot be tested, and this one is load-bearing.

The agent runtime's telemetry and error reporting are **disabled by environment**
rather than allowlisted (app/sandbox/env.py), so this list stays the length of
what a run genuinely needs.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:  # the write path imports this module, so the import is typing-only
    from ..target_config import TargetConfig

# The two hosts every run needs, whatever the target is: the model it talks to
# and the registry its lockfile installs from.
ANTHROPIC_API_HOST = "api.anthropic.com"
NPM_REGISTRY_HOST = "registry.npmjs.org"

# A name -> addresses function. `socket.getaddrinfo` is one; a dict is another.
Resolver = Callable[[str], list[str]]


class EgressError(Exception):
    """A host a run may not reach, or a name that could not be checked."""


class ResolutionError(EgressError):
    """The name does not resolve. A typo, most likely; told apart from the
    refusal below because an operator can act on them differently."""


class PrivateAddress(EgressError):
    """The name resolves somewhere a run must not reach."""


def host_list(raw: str) -> tuple[str, ...]:
    """A comma-separated list of hosts, as the environment carries one.

    Both ends of the egress wiring parse one: the scheduler reads the extra
    hosts a dev stack needs (app/sandbox/docker.py) and the proxy reads the
    allowlist it was handed. The same rule either side -- strip, drop empties --
    so a trailing comma or a space after one cannot mean something different to
    the process that writes the list and the process that enforces it.
    """
    return tuple(host for host in (part.strip() for part in raw.split(",")) if host)


def host_of(base_url: str) -> str:
    """The hostname a base URL names, without the port.

    A port is not part of an identity: `shop.example.com:3000` and
    `shop.example.com:443` are the same host, and the allowlist is about which
    host a run may talk to rather than which socket.
    """
    return (urlparse(base_url).hostname or "").strip()


def build_allowlist(cfg: TargetConfig) -> tuple[str, ...]:
    """Everything a run against this target may reach.

    One function from the target's own row, which is what makes a run against
    one target structurally unable to reach another target's host. P5 inherits it
    as a change of *input* -- a tenant's allowlist -- rather than a change of
    code.
    """
    return (host_of(cfg.base_url), ANTHROPIC_API_HOST, NPM_REGISTRY_HOST)


def _canonical(host: str) -> str:
    """A host as it is compared: lower-cased, without a trailing root dot.

    `SHOP.example.com.` and `shop.example.com` are the same name to DNS, so they
    have to be the same name to the allowlist -- a comparison that disagrees with
    the resolver is a bypass.
    """
    return host.strip().rstrip(".").lower()


def allows(allowlist: Iterable[str], host: str) -> bool:
    """Whether `host` is on the allowlist.

    Compared **whole**, never as a suffix. Allowing `*.example.com` would allow
    every name anybody can register under it, which for a customer's domain is
    not a smaller blast radius than the internet.
    """
    wanted = _canonical(host)
    return any(_canonical(entry) == wanted for entry in allowlist if entry)


def is_public_address(address: str) -> bool:
    """Whether an address is one a run may connect to.

    Everything a sandbox must not reach is already described by the standard
    categories, so this is deliberately a list of them rather than a hand-made
    set of ranges: `169.254.169.254` is link-local, the internal network is
    private, and `localhost` is loopback. `is_global` covers them together and
    keeps covering them as the registries add more -- the shared address space
    (100.64/10) and the documentation ranges come free.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False  # not an address at all: nothing to allow
    return ip.is_global and not ip.is_multicast


def system_resolver(host: str) -> list[str]:
    """The real resolver: every address the name has, A and AAAA alike.

    All of them, because a name that resolves to one public and one private
    address is the DNS-rebinding shape itself, and taking the first answer would
    be the bug.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ResolutionError(f"{host!r} does not resolve ({exc})") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise ResolutionError(f"{host!r} does not resolve")
    return sorted(addresses)


def resolve_public(
    host: str, *, resolve: Resolver | None = None
) -> Sequence[str]:
    """Every address `host` resolves to, or raise. Public addresses only.

    Raises `PrivateAddress` if **any** answer is not public: a name with one
    public and one private address is exactly the attack, not a name with a
    usable answer.

    A host that is already a literal address is not resolved -- there is nothing
    to ask, and the answer is in the name.

    The default resolver is looked up when this is called rather than bound as a
    default argument, so the suite's "no real DNS" guard is something a caller
    cannot step around by omitting the argument.
    """
    resolve = resolve or system_resolver
    name = _canonical(host)
    if not name:
        raise ResolutionError("no host to resolve")

    try:
        ipaddress.ip_address(name)
    except ValueError:
        addresses = list(resolve(name))
    else:
        addresses = [name]

    if not addresses:
        raise ResolutionError(f"{host!r} does not resolve")

    refused = [a for a in addresses if not is_public_address(a)]
    if refused:
        raise PrivateAddress(
            f"{host!r} resolves to {', '.join(refused)}, which is not a public "
            f"address; a run may not reach private, link-local or loopback "
            f"addresses"
        )
    return addresses
