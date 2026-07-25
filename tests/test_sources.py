import asyncio
import socket

import pytest

from record_ec_visualizer_tui.sources import (
    MulticastEndpoint,
    endpoints_from_record_config,
    multicast_lines,
    open_multicast_socket,
)

# An administratively-scoped group unlikely to collide with anything real.
TEST_GROUP = "239.255.42.99"
TEST_PORT = 45999


class TestEndpointsFromRecordConfig:
    def test_reads_analyzer_addresses(self):
        config = {
            "gasanalyzers": {
                "irga": {"ip": "239.0.0.1", "port": 40000, "var_map": {}},
                "other": {"ip": "239.0.0.2", "port": 40001},
            }
        }
        endpoints = endpoints_from_record_config(config)
        assert {(e.name, e.group, e.port) for e in endpoints} == {
            ("ga:irga", "239.0.0.1", 40000),
            ("ga:other", "239.0.0.2", 40001),
        }

    def test_can_select_a_single_analyzer(self):
        config = {
            "gasanalyzers": {
                "irga": {"ip": "239.0.0.1", "port": 40000},
                "other": {"ip": "239.0.0.2", "port": 40001},
            }
        }
        endpoints = endpoints_from_record_config(config, analyzers=["irga"])
        assert [e.name for e in endpoints] == ["ga:irga"]

    def test_missing_section_is_not_an_error(self):
        assert endpoints_from_record_config({}) == []

    def test_incomplete_section_is_skipped(self):
        config = {"gasanalyzers": {"broken": {"ip": "239.0.0.1"}}}
        assert endpoints_from_record_config(config) == []


class TestMulticastSocket:
    def test_opens_and_joins(self):
        try:
            sock = open_multicast_socket(TEST_GROUP, TEST_PORT)
        except OSError as exc:  # pragma: no cover - depends on host networking
            pytest.skip(f"multicast unavailable here: {exc}")
        try:
            assert sock.gettimeout() == 0.0  # non-blocking
        finally:
            sock.close()


def _send_datagrams(payloads: list[bytes]) -> None:
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    # TTL 0 and loopback on: exactly how rECorD publishes.
    sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 0)
    sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    try:
        for payload in payloads:
            sender.sendto(payload, (TEST_GROUP, TEST_PORT))
    finally:
        sender.close()


class TestMulticastLines:
    def test_receives_and_reassembles(self):
        """End-to-end over a real socket, the way a live site will deliver."""

        async def scenario() -> list[tuple[str, bytes]]:
            received: list[tuple[str, bytes]] = []

            async def reader() -> None:
                endpoints = [MulticastEndpoint("sonicshow", TEST_GROUP, TEST_PORT)]
                async for item in multicast_lines(endpoints):
                    received.append(item)

            task = asyncio.create_task(reader())
            await asyncio.sleep(0.3)
            # Third datagram is a message split in two, to exercise reassembly.
            _send_datagrams([b"{'a': 1}\n", b"{'b': 2}\n", b"{'c':", b" 3}\n"])
            await asyncio.sleep(0.5)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return received

        try:
            received = asyncio.run(scenario())
        except OSError as exc:  # pragma: no cover - depends on host networking
            pytest.skip(f"multicast unavailable here: {exc}")

        if not received:  # pragma: no cover - some sandboxes drop loopback multicast
            pytest.skip("no multicast loopback delivery on this host")

        assert [line for _, line in received] == [b"{'a': 1}", b"{'b': 2}", b"{'c': 3}"]
        assert {name for name, _ in received} == {"sonicshow"}

    def test_requires_at_least_one_endpoint(self):
        async def scenario():
            async for _ in multicast_lines([]):
                pass

        with pytest.raises(ValueError):
            asyncio.run(scenario())
