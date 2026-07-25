"""Where stream lines come from: a simulator, or real UDP multicast sockets.

Both sources yield the same thing — ``(stream_name, payload_bytes)`` — so the
application above them is identical either way. That is the whole point of the
split: pointing the TUI at a live site is a change of source, not of parsing or
display code.

Stream names are ``"sonicshow"`` and ``"ga:<analyzer>"``.

On the multicast side, note that ``udpmulticast``'s own client recipe does not
work here: it sets ``SO_REUSEPORT`` (which does not exist on Windows) and binds
to the multicast group address (which Windows rejects). :func:`open_multicast_socket`
does the portable equivalent.
"""
from __future__ import annotations

import asyncio
import socket
import struct
import sys
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass

from record_ec_visualizer_tui.codec import LineAssembler
from record_ec_visualizer_tui.simulator import RecordSimulator


@dataclass(frozen=True)
class MulticastEndpoint:
    """One multicast stream to subscribe to.

    Groups and ports are deliberately not defaulted anywhere in this package.
    rECorD's defaults live in its own source (``sonicshow_ip`` / ``sonicshow_port``,
    ``analyzershow_ip`` / ``analyzershow_port``) and a site's analyzer addresses
    live in its ``record.toml``; both must be supplied by the caller.
    """

    name: str
    group: str
    port: int
    interface: str = "0.0.0.0"


def open_multicast_socket(
    group: str,
    port: int,
    interface: str = "0.0.0.0",
) -> socket.socket:
    """Create a socket subscribed to ``group``, portably.

    Linux allows binding to the group address, which filters other traffic on
    the same port; Windows requires binding to the wildcard address instead.
    ``SO_REUSEPORT`` is used where it exists so this can run alongside rECorD's
    own consumers, and ``SO_REUSEADDR`` everywhere.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    reuse_port = getattr(socket, "SO_REUSEPORT", None)
    if reuse_port is not None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, reuse_port, 1)
        except OSError:
            # Declared but unsupported by the running kernel; SO_REUSEADDR alone
            # is enough for a single consumer.
            pass

    bind_host = "" if sys.platform == "win32" else group
    try:
        sock.bind((bind_host, port))
    except OSError:
        sock.close()
        raise

    membership = struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton(interface))
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
    except OSError:
        sock.close()
        raise

    sock.setblocking(False)
    return sock


class _DatagramCollector(asyncio.DatagramProtocol):
    """Push received datagrams onto a queue, tagged with their stream name."""

    def __init__(self, name: str, queue: asyncio.Queue[tuple[str, bytes]]) -> None:
        self._name = name
        self._queue = queue

    def datagram_received(self, data: bytes, addr: object) -> None:
        try:
            self._queue.put_nowait((self._name, data))
        except asyncio.QueueFull:
            # Dropping the oldest datagram is the right trade for a live view:
            # falling behind must not turn into unbounded memory use.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait((self._name, data))
            except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover
                pass

    def error_received(self, exc: Exception) -> None:  # pragma: no cover - transport level
        pass


async def simulated_lines(
    simulator: RecordSimulator | None = None,
    speedup: float = 1.0,
) -> AsyncIterator[tuple[str, bytes]]:
    """Yield rECorD-shaped lines from the simulator, paced in real time."""
    simulator = simulator or RecordSimulator()
    async for item in simulator.run(speedup=speedup):
        yield item


async def multicast_lines(
    endpoints: Sequence[MulticastEndpoint],
    queue_size: int = 2048,
) -> AsyncIterator[tuple[str, bytes]]:
    """Yield lines from live multicast sockets, reassembled across datagrams."""
    if not endpoints:
        raise ValueError("at least one endpoint is required")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue(maxsize=queue_size)
    assemblers = {endpoint.name: LineAssembler() for endpoint in endpoints}
    transports: list[asyncio.BaseTransport] = []

    try:
        for endpoint in endpoints:
            sock = open_multicast_socket(endpoint.group, endpoint.port, endpoint.interface)
            transport, _ = await loop.create_datagram_endpoint(
                lambda name=endpoint.name: _DatagramCollector(name, queue),
                sock=sock,
            )
            transports.append(transport)

        while True:
            name, data = await queue.get()
            for line in assemblers[name].push(data):
                yield name, line
    finally:
        for transport in transports:
            transport.close()


def endpoints_from_record_config(
    config: dict,
    analyzers: Iterable[str] | None = None,
) -> list[MulticastEndpoint]:
    """Build analyzer endpoints from a parsed rECorD ``record.toml``.

    Only the gas analyzer sections carry addresses; the sonicshow address is a
    rECorD code default and is not present in the site config, so it has to be
    passed separately.
    """
    sections = config.get("gasanalyzers") or {}
    wanted = set(analyzers) if analyzers is not None else None
    endpoints: list[MulticastEndpoint] = []
    for name, section in sections.items():
        if wanted is not None and name not in wanted:
            continue
        if not isinstance(section, dict) or "ip" not in section or "port" not in section:
            continue
        endpoints.append(
            MulticastEndpoint(name=f"ga:{name}", group=str(section["ip"]), port=int(section["port"]))
        )
    return endpoints
