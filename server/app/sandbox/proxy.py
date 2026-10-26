"""The allowlisting proxy: the sandbox's only way out.

Egress is denied at the **network layer**. The sandbox sits on an internal
Docker network with no default route, so there is nothing for an agent to opt out
of: unsetting `HTTP_PROXY` does not open the internet, it closes the only door.
An allowlist the agent can unset is a convention, not a control, which is why
this is not an environment variable.

    sandbox network   internal, no default route
                        the sandbox container
                        postgres, the object store     (resolved by name, reachable)
    egress network    this proxy only
                        allowlisting CONNECT proxy  ->  the internet

**The proxy resolves, not the sandbox.** An internal network cannot reach an
upstream resolver, and `CONNECT` carries a hostname, so Chromium and npm hand
names here and never resolve anything themselves. That is not a workaround: it
puts name resolution in the one process that also enforces policy, which is what
makes the private-address refusal happen at connect time, every time.

Three rules, in order, for every connection:

1. the host must be on **this run's** allowlist, built from this target's row by
   the one builder (`egress.build_allowlist`), passed in as `QA_EGRESS_ALLOWLIST`;
2. it must resolve, and **every** address it resolves to must be public
   (`egress.resolve_public`) -- the metadata endpoint, RFC1918 and loopback all
   refused by that one predicate;
3. the tunnel is opened to the **address that was verified**, not to the name
   again. Resolving twice is how a name that passed the check becomes a
   connection to somewhere it did not: the gap between check and connect is
   exactly what DNS rebinding aims at.

Plain HTTP is proxied as a tunnel too, after the same three rules: the first
request line's absolute-form URI names the host, and HTTP/1.1 servers accept
that form, so the bytes are relayed verbatim. A later request for another host
on the same connection reaches the socket of the first host, which is not a
bypass -- it is a request that host will not answer for.

Every decision is logged, so `docker logs qa-proxy-<run_key>` answers "what did
this run try to reach?" without a packet capture.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass

from . import egress

log = logging.getLogger("qa.proxy")

DEFAULT_PORT = 3128
# Enough for a request line plus headers; a client that sends more than this
# before a blank line is not speaking HTTP.
MAX_HEADER_BYTES = 64 * 1024
RELAY_CHUNK = 64 * 1024


def allowlist_from_env() -> tuple[str, ...]:
    """This run's allowlist, as the scheduler passed it.

    One source, and it is the builder's output (app/sandbox/egress.py). The
    proxy does not add to it, does not read a target row, and has no notion of
    a default: an empty allowlist is a proxy that refuses everything, which is
    the right failure for a misconfigured dispatch.
    """
    return egress.host_list(os.environ.get("QA_EGRESS_ALLOWLIST", ""))


def port_from_env() -> int:
    try:
        return int(os.environ.get("QA_PROXY_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


@dataclass(frozen=True)
class Decision:
    """Whether a connection may be opened, and where to."""

    allowed: bool
    reason: str
    address: str | None = None


def decide(
    host: str,
    allowlist: tuple[str, ...],
    *,
    resolve: egress.Resolver | None = None,
) -> Decision:
    """Apply the three rules to one host. A plain function, so the policy is
    testable without a socket -- which is the only way to test the rule that
    matters most, the one about addresses nobody can register."""
    if not egress.allows(allowlist, host):
        return Decision(False, f"{host} is not on this run's allowlist")
    try:
        addresses = egress.resolve_public(host, resolve=resolve)
    except egress.EgressError as exc:
        return Decision(False, str(exc))
    return Decision(True, f"{host} -> {addresses[0]}", address=addresses[0])


def target_of(request_line: str) -> tuple[str, str, int] | None:
    """(method, host, port) from a proxy request line, or None if it is not one.

        CONNECT shop.example.com:443 HTTP/1.1
        GET http://shop.example.com/x HTTP/1.1
    """
    parts = request_line.split()
    if len(parts) < 2:
        return None
    method, target = parts[0].upper(), parts[1]
    if method == "CONNECT":
        host, _, port = target.partition(":")
        return method, host, int(port) if port.isdigit() else 443
    if "://" in target:
        scheme, _, rest = target.partition("://")
        authority = rest.split("/", 1)[0]
        # Strip userinfo if a client sent any; the host is what policy is about,
        # and `http://shop.example.com@evil.example.com/` names evil.
        authority = authority.rpartition("@")[2]
        host, _, port = authority.partition(":")
        default = 443 if scheme.lower() == "https" else 80
        return method, host, int(port) if port.isdigit() else default
    return None


async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(RELAY_CHUNK):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError, OSError):
        pass
    finally:
        writer.close()


class Proxy:
    """One run's proxy. Its allowlist is fixed for its lifetime, as the run is."""

    def __init__(
        self, allowlist: tuple[str, ...], *, resolve: egress.Resolver | None = None
    ) -> None:
        self.allowlist = allowlist
        self._resolve = resolve

    async def handle(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        try:
            await self._handle(client_reader, client_writer)
        except Exception:  # pragma: no cover - one bad client is not an outage
            log.warning("proxy connection failed", exc_info=True)
            client_writer.close()

    async def _handle(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        head = await client_reader.readuntil(b"\r\n")
        request_line = head.decode("latin-1").strip()
        parsed = target_of(request_line)
        if parsed is None:
            await self._refuse(client_writer, 400, f"not a proxy request: {request_line}")
            return
        method, host, port = parsed

        decision = decide(host, self.allowlist, resolve=self._resolve)
        if not decision.allowed:
            log.warning("DENY %s %s:%s -- %s", method, host, port, decision.reason)
            await self._refuse(client_writer, 403, decision.reason)
            return
        log.info("ALLOW %s %s:%s -- %s", method, host, port, decision.reason)

        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                decision.address, port
            )
        except OSError as exc:
            await self._refuse(client_writer, 502, f"cannot reach {host}:{port}: {exc}")
            return

        if method == "CONNECT":
            # Everything up to the blank line is the client's, and it is not
            # ours to forward: a CONNECT's headers end at the tunnel.
            await self._drain_headers(client_reader)
            client_writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await client_writer.drain()
        else:
            # Absolute-form, relayed verbatim: an HTTP/1.1 server must accept
            # it, so there is no request to rewrite and nothing to get wrong.
            upstream_writer.write(head)
            await upstream_writer.drain()

        await asyncio.gather(
            _relay(client_reader, upstream_writer),
            _relay(upstream_reader, client_writer),
        )

    async def _drain_headers(self, reader: asyncio.StreamReader) -> None:
        read = 0
        while read < MAX_HEADER_BYTES:
            line = await reader.readuntil(b"\r\n")
            read += len(line)
            if line in (b"\r\n", b""):
                return

    async def _refuse(
        self, writer: asyncio.StreamWriter, status: int, reason: str
    ) -> None:
        """Say why, in the response. An agent that is refused should be able to
        report the refusal rather than an inexplicable timeout."""
        body = reason.encode("utf-8", "replace")
        writer.write(
            f"HTTP/1.1 {status} Forbidden\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Content-Type: text/plain\r\n"
            f"Connection: close\r\n\r\n".encode("latin-1")
            + body
        )
        try:
            await writer.drain()
        finally:
            writer.close()


async def serve(
    allowlist: tuple[str, ...],
    *,
    port: int = DEFAULT_PORT,
    host: str = "0.0.0.0",  # noqa: S104 - the only network it is on is internal
    resolve: egress.Resolver | None = None,
) -> asyncio.AbstractServer:
    """Start the proxy. Returns the server, for a caller that has to stop it."""
    proxy = Proxy(allowlist, resolve=resolve)
    server = await asyncio.start_server(proxy.handle, host, port)
    log.info("proxy listening on %s:%s; allowlist: %s", host, port, ", ".join(allowlist))
    return server


async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    allowlist = allowlist_from_env()
    if not allowlist:
        log.warning(
            "QA_EGRESS_ALLOWLIST is empty: this proxy will refuse every host. "
            "The scheduler builds it from the target's row."
        )
    server = await serve(allowlist, port=port_from_env())
    async with server:
        await server.serve_forever()


if __name__ == "__main__":  # pragma: no cover - exercised as a container
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        sys.exit(0)
