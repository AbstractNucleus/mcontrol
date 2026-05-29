"""One-shot RCON command runner for slice-7 whitelist/ops mutations.

The slice-4 console (``routes/console.py``) keeps a long-lived RCON
connection open per active SSE stream. Slice 7's add/remove flips are
infrequent and don't need a persistent connection. each call opens a
connection, runs one command, and closes.

The docker-network attach/detach dance mirrors what the SSE handler
does: the mcontrol container has to be on the MC container's network
to reach ``<container>:25575``. We attach for the duration of the
command and detach afterwards.

Failure surface, surfaced as :class:`RconUnavailable` so the route
layer can map to a flash message:

  - ``enable-rcon=false`` or empty ``rcon.password`` in
    ``server/server.properties``.
  - The container has no docker network attached.
  - Auth failure (wrong password).
  - TCP/network error reaching the container.

Stale-password detection (issue 119): every successful RCON auth records
the password that worked into ``_last_authed_password`` (keyed by server
name). The server-detail route compares on-disk ``rcon.password`` to
this cached value; if they differ, the running JVM still has the old
value and the operator must restart. The cache lives for the lifetime
of the mcontrol process, which is the same lifetime as the running JVMs
we care about.
"""

from pathlib import Path

import aiodocker

from mcontrol.domain import lifecycle_state, server_props
from mcontrol.infra import docker_client, rcon

_RCON_PORT = 25575

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


async def run_command(docker: aiodocker.Docker, server: dict, command: str) -> str:
    """Open RCON, run ``command``, return the server's literal response.

    ``server`` is the DB row (we pull ``dir`` for server.properties and
    ``container_name`` / ``name`` for the network resolve)."""
    server_dir = Path(server["dir"])
    props = server_props.read_properties(server_dir / "server" / "server.properties")
    if props.get("enable-rcon", "").lower() != "true":
        raise RconUnavailable("RCON is not enabled in server.properties.")
    password = props.get("rcon.password", "")
    if not password:
        raise RconUnavailable("rcon.password is empty in server.properties.")

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
        except OSError as exc:
            raise RconUnavailable(f"Could not reach {container_name}: {exc}") from exc
        record_authed_password(server["name"], password)
        try:
            return await conn.run(command)
        finally:
            await conn.close()
    finally:
        await docker_client.detach_self_from_network(docker, network_name)
