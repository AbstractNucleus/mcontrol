"""One-shot RCON command runner for slice-7 whitelist/ops mutations.

The slice-4 console (``routes/console.py``) keeps a long-lived RCON
connection open per active SSE stream. When that connection exists —
or is still being acquired — ``run_command`` reuses it and never opens
a second TCP client. Minecraft RCON typically allows only one client;
a competing connect races the console and can EOF mid-command.

When no console is open, this module opens a short-lived connection,
runs one command, and closes. The docker-network attach/detach dance
mirrors what the SSE handler does: the mcontrol container has to be on
the MC container's network to reach ``<container>:25575``.

Failure surface, surfaced as :class:`RconUnavailable` so the route
layer can map to a flash message:

  - ``enable-rcon=false`` or empty ``rcon.password`` in
    ``server/server.properties``.
  - The container has no docker network attached.
  - Auth failure (wrong password).
  - TCP/network error reaching the container.
  - Peer closed the connection mid-command.
  - Console still connecting / dead socket needing a page refresh.

Stale-password detection (issue 119): every successful RCON auth records
the password that worked into ``_last_authed_password`` (keyed by server
name). The server-detail route compares on-disk ``rcon.password`` to
this cached value; if they differ, the running JVM still has the old
value and the operator must restart. The cache lives for the lifetime
of the mcontrol process, which is the same lifetime as the running JVMs
we care about.
"""

import asyncio
from pathlib import Path

import aiodocker

from mcontrol.domain import lifecycle_state, server_props
from mcontrol.infra import docker_client, rcon

_RCON_PORT = 25575
_CONSOLE_CONNECT_WAIT_S = 5.0

# Server name → password that most recently authenticated successfully.
# Populated by run_command (here) and routes/console._stream after a
# successful rcon.connect; consumed by stale_password_detected.
_last_authed_password: dict[str, str] = {}


def record_authed_password(server_name: str, password: str) -> None:
    """Record the password that just succeeded against the running JVM."""
    _last_authed_password[server_name] = password


def forget_authed_password(server_name: str) -> None:
    """Drop the cached password. the JVM that knew it is gone.

    Called from the stop and restart lifecycle handlers so the next
    successful auth re-establishes the baseline against the fresh JVM.
    """
    _last_authed_password.pop(server_name, None)


def stale_password_detected(server: dict) -> bool:
    """True iff we know the running JVM's password and it differs from disk.

    Returns False when we've never observed a successful auth for this
    server (no baseline to compare against), when the server isn't
    currently running (no stale JVM to warn about), or when on-disk and
    cached values match. Reads ``server.properties`` via ``server_props``,
    which is mtime-cached so render-time overhead is one ``stat`` call
    once warm.
    """
    if not lifecycle_state.is_running(server):
        return False
    server_name = server["name"]
    if server_name not in _last_authed_password:
        return False
    server_dir = Path(server["dir"])
    props = server_props.read_properties(server_dir / "server" / "server.properties")
    disk_password = props.get("rcon.password", "")
    if not disk_password:
        return False
    return disk_password != _last_authed_password[server_name]


class RconUnavailable(Exception):
    """RCON couldn't be reached for a reason the operator can act on
    (rcon disabled in server.properties, no docker network, auth
    failure, etc.). Distinct from a successful command that returns an
    error string. those flow back to the caller verbatim."""


def _map_console_errors(exc: BaseException) -> RconUnavailable:
    if isinstance(exc, TimeoutError):
        return RconUnavailable("RCON command timed out.")
    if isinstance(exc, rcon.RconClosedError):
        return RconUnavailable(
            "RCON connection closed; refresh the page to reconnect."
        )
    return RconUnavailable(str(exc))


async def _run_via_console(server_name: str, command: str) -> str | None:
    """Use the detail-page RCON socket when the console owns the slot.

    Returns the command response, or ``None`` when the console is not
    involved and the caller may open a one-shot client. Never opens a
    second Minecraft RCON TCP connection while the console lock is held.
    """
    # Lazy import: console imports server_rcon for record_authed_password.
    from mcontrol.routes import console

    owns = console.console_owns_rcon(server_name)
    if not owns:
        try:
            return await console.run_on_active(server_name, command)
        except (TimeoutError, rcon.RconClosedError) as exc:
            raise _map_console_errors(exc) from exc

    loop = asyncio.get_running_loop()
    deadline = loop.time() + _CONSOLE_CONNECT_WAIT_S
    while True:
        try:
            reused = await console.run_on_active(server_name, command)
        except (TimeoutError, rcon.RconClosedError) as exc:
            raise _map_console_errors(exc) from exc
        if reused is not None:
            return reused
        if not console.console_owns_rcon(server_name):
            return None
        if loop.time() >= deadline:
            raise RconUnavailable(
                "RCON console is still connecting; try again in a moment."
            )
        await asyncio.sleep(0.05)


async def run_command(docker: aiodocker.Docker, server: dict, command: str) -> str:
    """Run ``command`` over RCON, return the server's literal response.

    Prefers the live console connection when the detail page holds one.
    Otherwise opens a short-lived connection. ``server`` is the DB row
    (we pull ``dir`` for server.properties and ``container_name`` /
    ``name`` for the network resolve)."""
    server_dir = Path(server["dir"])
    props = server_props.read_properties(server_dir / "server" / "server.properties")
    if props.get("enable-rcon", "").lower() != "true":
        raise RconUnavailable("RCON is not enabled in server.properties.")
    password = props.get("rcon.password", "")
    if not password:
        raise RconUnavailable("rcon.password is empty in server.properties.")

    reused = await _run_via_console(server["name"], command)
    if reused is not None:
        return reused

    container_name = server.get("container_name") or server["name"]

    network_name = await docker_client.find_network_name(docker, container_name)
    if network_name is None:
        raise RconUnavailable(f"No docker network found for {container_name!r}.")

    await docker_client.attach_self_to_network(docker, network_name)
    try:
        try:
            conn = await rcon.connect(container_name, _RCON_PORT, password)
        except rcon.AuthenticationError as exc:
            raise RconUnavailable("RCON authentication failed.") from exc
        except TimeoutError as exc:
            # TimeoutError subclasses OSError, so this must come first to
            # keep the operator-facing message specific.
            raise RconUnavailable(f"RCON connect to {container_name} timed out.") from exc
        except OSError as exc:
            raise RconUnavailable(f"Could not reach {container_name}: {exc}") from exc
        except rcon.RconClosedError as exc:
            raise RconUnavailable(
                f"RCON connection to {container_name} closed during auth."
            ) from exc
        record_authed_password(server["name"], password)
        try:
            return await conn.run(command)
        except TimeoutError as exc:
            raise RconUnavailable("RCON command timed out.") from exc
        except rcon.RconClosedError as exc:
            raise RconUnavailable(
                "RCON connection closed while running the command."
            ) from exc
        finally:
            await conn.close()
    finally:
        await docker_client.detach_self_from_network(docker, network_name)
