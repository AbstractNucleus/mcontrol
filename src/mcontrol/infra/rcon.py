"""Bespoke async client for the Source RCON protocol used by Minecraft.

Each packet:
    <length:int32 LE><id:int32 LE><type:int32 LE><body:bytes><null><null>
Length excludes itself.

Types used:
    SERVERDATA_AUTH                = 3
    SERVERDATA_AUTH_RESPONSE       = 2
    SERVERDATA_EXECCOMMAND         = 2
    SERVERDATA_RESPONSE_VALUE      = 0

Auth: send AUTH (type=3) with the password as the body. Server replies
with AUTH_RESPONSE (type=2). id=-1 means auth failed; otherwise it
echoes the request id.

Exec: send EXECCOMMAND (type=2), then an empty SERVERDATA_RESPONSE_VALUE
sentinel packet with a distinct id. Collect all RESPONSE_VALUE packets
matching the command id until the sentinel echo arrives; concatenate their
bodies. This handles Minecraft's multi-packet responses (e.g. `whitelist
list` on a populated server).

Reference: https://wiki.vg/RCON
"""

import asyncio
import itertools
import struct

_AUTH = 3
_AUTH_RESPONSE = 2
_EXECCOMMAND = 2
_RESPONSE_VALUE = 0

# A wedged RCON port must not hang requests forever (or hold the
# per-server console lock). Timeouts raise TimeoutError to the caller.
_CONNECT_TIMEOUT_S = 5.0
_COMMAND_TIMEOUT_S = 10.0


class RconError(RuntimeError):
    pass


class AuthenticationError(RconError):
    pass


class RconClosedError(RconError):
    pass


class _RconConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._ids = itertools.count(1)
        self._closed = False

    async def run(self, command: str) -> str:
        if self._closed:
            raise RconClosedError("connection has been closed")
        try:
            return await asyncio.wait_for(self._exchange(command), _COMMAND_TIMEOUT_S)
        except TimeoutError:
            # A half-read response would desync every later exchange on
            # this connection, so a timed-out command closes it.
            await self.close()
            raise

    async def _exchange(self, command: str) -> str:
        packet_id = next(self._ids)
        await self._send(packet_id, _EXECCOMMAND, command.encode("utf-8"))
        sentinel_id = next(self._ids)
        await self._send(sentinel_id, _RESPONSE_VALUE, b"")
        parts: list[bytes] = []
        while True:
            response_id, response_type, body = await self._read()
            if response_type != _RESPONSE_VALUE:
                raise RconError(f"unexpected response type {response_type}")
            if response_id == sentinel_id:
                break
            if response_id != packet_id:
                raise RconError(f"id mismatch: sent {packet_id}, got {response_id}")
            parts.append(body)
        return b"".join(parts).decode("utf-8", errors="replace")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass

    async def _send(self, packet_id: int, packet_type: int, body: bytes) -> None:
        payload = struct.pack("<ii", packet_id, packet_type) + body + b"\x00\x00"
        length = len(payload)
        self._writer.write(struct.pack("<i", length) + payload)
        await self._writer.drain()

    async def _read(self) -> tuple[int, int, bytes]:
        try:
            length_bytes = await self._reader.readexactly(4)
            length = struct.unpack("<i", length_bytes)[0]
            payload = await self._reader.readexactly(length)
        except asyncio.IncompleteReadError as exc:
            # Peer closed mid-frame — common when a second RCON client
            # connects and Minecraft drops this one.
            await self.close()
            raise RconClosedError("connection closed by peer") from exc
        packet_id, packet_type = struct.unpack("<ii", payload[:8])
        body = payload[8:-2]
        return packet_id, packet_type, body


async def connect(host: str, port: int, password: str) -> _RconConnection:
    """Open and authenticate an RCON connection. Raises AuthenticationError
    if the server rejects the password, TimeoutError if the port hangs."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), _CONNECT_TIMEOUT_S
    )
    conn = _RconConnection(reader, writer)
    auth_id = next(conn._ids)
    await conn._send(auth_id, _AUTH, password.encode("utf-8"))
    try:
        response_id, response_type, _ = await asyncio.wait_for(
            conn._read(), _CONNECT_TIMEOUT_S
        )
    except TimeoutError:
        await conn.close()
        raise
    if response_type != _AUTH_RESPONSE:
        await conn.close()
        raise RconError(f"expected AUTH_RESPONSE, got {response_type}")
    if response_id == -1:
        await conn.close()
        raise AuthenticationError("RCON authentication failed")
    return conn
