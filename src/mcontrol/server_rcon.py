"""One-shot RCON command runner for slice-7 whitelist/ops mutations.

The slice-4 console (``routes/console.py``) keeps a long-lived RCON
connection open per active SSE stream. Slice 7's add/remove flips are
infrequent and don't need a persistent connection — each call opens a
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
"""

from pathlib import Path

import aiodocker

from mcontrol import docker_client, rcon, server_props

_RCON_PORT = 25575


class RconUnavailable(Exception):
    """RCON couldn't be reached for a reason the operator can act on
    (rcon disabled in server.properties, no docker network, auth
    failure, etc.). Distinct from a successful command that returns an
    error string — those flow back to the caller verbatim."""


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
        try:
            return await conn.run(command)
        finally:
            await conn.close()
    finally:
        await docker_client.detach_self_from_network(docker, network_name)
