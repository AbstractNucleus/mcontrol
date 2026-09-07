"""End-to-end tests for the bespoke async RCON client against a fake
Source-protocol server built on asyncio.start_server.

The fake mirrors Minecraft's RCON thread: AUTH (type=3) → AUTH_RESPONSE
(type=2, id=match for ok, id=-1 for fail), EXEC (type=2) → RESPONSE_VALUE
(type=0) in 4096-byte chunks, any other type → "Unknown request <hex>".
Like Minecraft it reads one buffer per loop and drops the connection when
that buffer holds anything but exactly one packet.
"""

import asyncio
import struct

import pytest

from mcontrol.infra import rcon

_MC_READ_SIZE = 1460
_MC_CHUNK = 4096


def _pack(packet_id: int, packet_type: int, body: bytes) -> bytes:
    payload = struct.pack("<ii", packet_id, packet_type) + body + b"\x00\x00"
    length = len(payload)
    return struct.pack("<i", length) + payload


async def _read_packet(reader: asyncio.StreamReader) -> tuple[int, int, bytes]:
    length_bytes = await reader.readexactly(4)
    length = struct.unpack("<i", length_bytes)[0]
    payload = await reader.readexactly(length)
    packet_id, packet_type = struct.unpack("<ii", payload[:8])
    body = payload[8:-2]  # strip the two trailing null bytes
    return packet_id, packet_type, body


class _FakeRconServer:
    def __init__(self, password: str = "hunter2"):
        self.password = password
        self.received_commands: list[bytes] = []
        self.coalesced_reads = 0  # reads that held more than one packet
        self.fail_auth = False
        self.hang_auth = False  # accept TCP, never answer the AUTH packet
        self.hang_exec = False  # answer auth, never answer EXECCOMMAND
        self.exec_response = b"There are 3 of a max of 20 players online: alice, bob, carol"
        self._server: asyncio.base_events.Server | None = None
        self.host = "127.0.0.1"
        self.port = 0  # populated after start

    async def __aenter__(self):
        self._server = await asyncio.start_server(self._handler, host=self.host, port=0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_):
        self._server.close()
        await self._server.wait_closed()

    async def _read_one(self, reader: asyncio.StreamReader) -> tuple[int, int, bytes] | None:
        """Minecraft-shaped read: whatever is buffered, which must be one packet."""
        data = await reader.read(_MC_READ_SIZE)
        if len(data) < 10:
            return None
        length = struct.unpack("<i", data[:4])[0]
        if length != len(data) - 4:
            self.coalesced_reads += 1
            return None
        packet_id, packet_type = struct.unpack("<ii", data[4:12])
        return packet_id, packet_type, data[12:-2]

    @staticmethod
    def _chunked(packet_id: int, body: bytes) -> bytes:
        chunks = [body[i : i + _MC_CHUNK] for i in range(0, len(body), _MC_CHUNK)] or [b""]
        return b"".join(_pack(packet_id, 0, chunk) for chunk in chunks)

    async def _handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            frame = await self._read_one(reader)
            if frame is None:
                return
            pid, ptype, body = frame
            assert ptype == 3, "first packet must be AUTH"
            if self.hang_auth:
                await reader.read()  # wait for the client to give up and close
                return
            ok = body.decode() == self.password and not self.fail_auth
            response_id = pid if ok else -1
            writer.write(_pack(response_id, 2, b""))  # AUTH_RESPONSE
            await writer.drain()
            if not ok:
                return

            while True:
                frame = await self._read_one(reader)
                if frame is None:
                    return
                pid, ptype, body = frame
                if ptype == 2:  # EXECCOMMAND
                    self.received_commands.append(body)
                    if self.hang_exec:
                        await reader.read()  # wait for the client to give up and close
                        return
                    writer.write(self._chunked(pid, self.exec_response))
                else:
                    writer.write(self._chunked(pid, f"Unknown request {ptype:x}".encode()))
                await writer.drain()
        finally:
            writer.close()


async def test_connect_and_run_returns_response():
    async with _FakeRconServer() as server:
        client = await rcon.connect(server.host, server.port, "hunter2")
        try:
            response = await client.run("list")
            assert response == "There are 3 of a max of 20 players online: alice, bob, carol"
            assert server.received_commands == [b"list"]
        finally:
            await client.close()


async def test_run_never_shares_a_read_with_the_command():
    """Minecraft drops the socket when a read holds more than one packet, so
    the end-of-response sentinel must wait for the first response packet."""
    async with _FakeRconServer() as server:
        client = await rcon.connect(server.host, server.port, "hunter2")
        try:
            for _ in range(5):
                assert await client.run("list") == server.exec_response.decode()
        finally:
            await client.close()
        assert server.coalesced_reads == 0
        assert server.received_commands == [b"list"] * 5


async def test_connect_raises_on_bad_password():
    async with _FakeRconServer() as server:
        with pytest.raises(rcon.AuthenticationError):
            await rcon.connect(server.host, server.port, "wrong-password")


async def test_close_idempotent_when_run_twice():
    async with _FakeRconServer() as server:
        client = await rcon.connect(server.host, server.port, "hunter2")
        await client.close()
        # Second close must not raise.
        await client.close()


async def test_run_after_close_raises():
    async with _FakeRconServer() as server:
        client = await rcon.connect(server.host, server.port, "hunter2")
        await client.close()
        assert client.closed
        with pytest.raises(rcon.RconClosedError):
            await client.run("list")


async def test_run_handles_empty_response():
    async with _FakeRconServer() as server:
        server.exec_response = b""
        client = await rcon.connect(server.host, server.port, "hunter2")
        try:
            response = await client.run("op alice")
            assert response == ""
        finally:
            await client.close()


async def test_run_reassembles_multi_packet_response():
    long_response = b"".join(f"/command{i:04d} <args>\n".encode() for i in range(500))
    assert len(long_response) > 2 * _MC_CHUNK
    async with _FakeRconServer() as server:
        server.exec_response = long_response
        client = await rcon.connect(server.host, server.port, "hunter2")
        try:
            response = await client.run("help")
            assert response == long_response.decode()
            # Connection is still in sync afterwards.
            server.exec_response = b"Seed: [42]"
            assert await client.run("seed") == "Seed: [42]"
        finally:
            await client.close()
        assert server.coalesced_reads == 0


async def test_connect_times_out_when_auth_hangs(monkeypatch):
    monkeypatch.setattr(rcon, "_CONNECT_TIMEOUT_S", 0.05)
    async with _FakeRconServer() as server:
        server.hang_auth = True
        with pytest.raises(TimeoutError):
            await rcon.connect(server.host, server.port, "hunter2")


async def test_run_times_out_and_closes_when_exec_hangs(monkeypatch):
    monkeypatch.setattr(rcon, "_COMMAND_TIMEOUT_S", 0.05)
    async with _FakeRconServer() as server:
        server.hang_exec = True
        client = await rcon.connect(server.host, server.port, "hunter2")
        with pytest.raises(TimeoutError):
            await client.run("list")
        # A timed-out exchange desyncs the stream; the connection must
        # be closed rather than reused.
        assert client.closed
        with pytest.raises(rcon.RconClosedError):
            await client.run("list")


async def test_run_maps_transport_loss_to_rcon_closed():
    """A socket that died underneath us (interface gone, reset) surfaces as
    RconClosedError, not a bare OSError the routes don't expect."""
    async with _FakeRconServer() as server:
        client = await rcon.connect(server.host, server.port, "hunter2")
        client._writer.transport.abort()
        await asyncio.sleep(0)  # let connection_lost run
        with pytest.raises(rcon.RconClosedError, match="connection lost"):
            await client.run("list")
        assert client.closed


async def test_run_maps_peer_disconnect_to_rcon_closed():
    """If the peer closes mid-frame, IncompleteReadError becomes RconClosedError
    instead of leaking as an uncaught asyncio error (500 on whitelist add)."""

    async def _close_after_auth(reader, writer):
        length_bytes = await reader.readexactly(4)
        length = struct.unpack("<i", length_bytes)[0]
        payload = await reader.readexactly(length)
        packet_id, _packet_type = struct.unpack("<ii", payload[:8])
        writer.write(_pack(packet_id, 2, b""))  # AUTH_RESPONSE ok
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_close_after_auth, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        client = await rcon.connect("127.0.0.1", port, "hunter2")
        with pytest.raises(rcon.RconClosedError, match="closed by peer"):
            await client.run("whitelist add Notch")
    finally:
        server.close()
        await server.wait_closed()
