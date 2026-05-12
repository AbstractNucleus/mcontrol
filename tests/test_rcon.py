"""End-to-end tests for the bespoke async RCON client against a fake
Source-protocol server built on asyncio.start_server.

The fake mirrors Minecraft's RCON: AUTH (type=3) → AUTH_RESPONSE (type=2,
id=match for ok, id=-1 for fail), EXEC (type=2) → RESPONSE_VALUE (type=0).
"""

import asyncio
import struct

import pytest

from mcontrol import rcon


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
        self.fail_auth = False
        self.exec_response = b"There are 3 of a max of 20 players online: alice, bob, carol"
        self.exec_response_parts: list[bytes] | None = None  # overrides exec_response when set
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

    async def _handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            # Auth packet first
            pid, ptype, body = await _read_packet(reader)
            assert ptype == 3, "first packet must be AUTH"
            ok = body.rstrip(b"\x00").decode() == self.password and not self.fail_auth
            response_id = pid if ok else -1
            writer.write(_pack(response_id, 2, b""))  # AUTH_RESPONSE
            await writer.drain()
            if not ok:
                writer.close()
                return

            # One or more EXEC packets, each followed by a sentinel packet
            while not reader.at_eof():
                try:
                    pid, ptype, body = await _read_packet(reader)
                except asyncio.IncompleteReadError:
                    break
                if ptype == 2:  # EXECCOMMAND
                    self.received_commands.append(body.rstrip(b"\x00"))
                    parts = (
                        self.exec_response_parts
                        if self.exec_response_parts is not None
                        else [self.exec_response]
                    )
                    for part in parts:
                        writer.write(_pack(pid, 0, part))
                    await writer.drain()
                elif ptype == 0:  # sentinel SERVERDATA_RESPONSE_VALUE — echo it back
                    writer.write(_pack(pid, 0, b""))
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
    async with _FakeRconServer() as server:
        server.exec_response_parts = [b"chunk-one ", b"chunk-two"]
        client = await rcon.connect(server.host, server.port, "hunter2")
        try:
            response = await client.run("whitelist list")
            assert response == "chunk-one chunk-two"
        finally:
            await client.close()
