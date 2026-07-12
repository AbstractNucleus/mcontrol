"""Dev entrypoint: run mcontrol against in-memory fakes — no Supabase, no Docker.

    uv run uvicorn dev_mock:app --reload --port 8000

or start the ``mcontrol-mock`` config from .claude/launch.json.

This installs an in-memory DB store and a FakeDocker onto the real infra
modules, seeds a small fleet (both in the DB and on disk under
SERVER_BASE_PATH), then builds the app via the unmodified ``create_app``.
Production code is untouched; the fakes are wired in only when this module
is the process entrypoint.
"""

import asyncio
import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# --- Settings: satisfy pydantic-settings and point the base path at our seed
# dir. Env vars take precedence over .env, so this wins even if .env exists.
# Must run before anything imports mcontrol.settings.
_BASE = (Path(__file__).parent / ".localdev" / "minecraft").resolve()
os.environ["SUPABASE_URL"] = "http://mock.invalid"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "dev-mock"
os.environ["SERVER_BASE_PATH"] = str(_BASE)

import aiodocker  # noqa: E402

from mcontrol.infra import db  # noqa: E402

# ---------------------------------------------------------------------------
# Seed fleet. One source of truth for the DB rows, the on-disk dirs, and the
# FakeDocker container states, so discovery's startup reconcile is a no-op.
# ---------------------------------------------------------------------------

_PLAYERS: list[dict[str, str]] = [
    {"uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5", "name": "Notch"},
    {"uuid": "61699b2e-d327-4a01-9f1e-0ea8c3f06bc6", "name": "Dinnerbone"},
    {"uuid": "853c80ef-3c37-49fd-aa49-938b674adae6", "name": "jeb_"},
    {"uuid": "b876ec32-e396-476b-a115-8438d83c67d4", "name": "Grumm"},
    {"uuid": "d8d5a923-7b20-43d8-883b-1150148d6955", "name": "Steve"},
]

_SEED: list[dict[str, Any]] = [
    {"name": "atm10", "state": "running", "port": 25565, "loader": "forge", "memory": "10G"},
    {"name": "create-astral", "state": "running", "port": 25566, "loader": "fabric", "memory": "8G"},  # noqa: E501
    {"name": "vault-hunters", "state": "exited", "port": 25567, "loader": "forge", "memory": "8G"},
    {"name": "cobblemon", "state": "exited", "port": 25568, "loader": "fabric", "memory": "6G"},
    {"name": "vanilla-smp", "state": "running", "port": 25569, "loader": "vanilla", "memory": "4G"},
]


def _row(seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": seed["name"],
        "dir": str(_BASE / seed["name"]),
        "state": seed["state"],
        "container_name": None,
        "loader": seed["loader"],
        "variables": {"port": seed["port"], "memory": seed["memory"]},
        # Legacy (discovery-style) rows: scaffolded_at=None keeps the
        # detail-page health banner clean (no scaffold-file checks).
        "scaffolded_at": None,
    }


def _scaffold_disk() -> None:
    """Create per-server dirs so the Files panel and roster cards populate."""
    for seed in _SEED:
        name, port = seed["name"], seed["port"]
        sdir = _BASE / name / "server"
        (sdir / "logs").mkdir(parents=True, exist_ok=True)

        (_BASE / name / "docker-compose.yml").write_text(
            f"services:\n  {name}:\n    image: itzg/minecraft-server\n"
            f"    ports:\n      - \"{port}:25565\"\n",
            encoding="utf-8",
        )
        (sdir / "server.properties").write_text(
            "enable-rcon=true\nrcon.password=devmock\nrcon.port=25575\n"
            f"server-port=25565\nmotd=Dev Mock — {name}\nlevel-name=world\n",
            encoding="utf-8",
        )
        (sdir / "whitelist.json").write_text(
            json.dumps(_PLAYERS[:3], indent=2) + "\n", encoding="utf-8"
        )
        (sdir / "ops.json").write_text(
            json.dumps(
                [{**_PLAYERS[0], "level": 4, "bypassesPlayerLimit": False}],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (sdir / "logs" / "latest.log").write_text(
            "[12:00:00] [Server thread/INFO]: Starting minecraft server\n"
            "[12:00:04] [Server thread/INFO]: Done! For help, type \"help\"\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# In-memory DB store — mirrors the public surface of mcontrol.infra.db.
# db_async resolves db.<fn> at call time, so replacing the attributes here
# routes every async caller through these.
# ---------------------------------------------------------------------------

_servers: dict[str, dict[str, Any]] = {s["name"]: _row(s) for s in _SEED}
_players: dict[str, dict[str, Any]] = {p["uuid"]: dict(p) for p in _PLAYERS}


def _install_fake_db() -> None:
    def list_servers() -> list[dict[str, Any]]:
        return [_servers[n] for n in sorted(_servers)]

    def ping() -> None:
        return None

    def get_server(name: str) -> dict[str, Any] | None:
        return _servers.get(name)

    def insert_server(*, name: str, dir: str, state: str) -> None:
        _servers[name] = {
            "name": name, "dir": dir, "state": state,
            "container_name": None, "variables": {}, "scaffolded_at": None,
        }

    def update_server_state(*, name: str, state: str) -> None:
        if name in _servers:
            _servers[name]["state"] = state

    def update_variables(*, name: str, variables: dict[str, Any]) -> None:
        if name in _servers:
            _servers[name]["variables"] = variables

    def update_bindings(*, name: str, container_name: str | None, dir: str) -> None:
        if name in _servers:
            _servers[name].update(container_name=container_name, dir=dir)

    def insert_scaffolding_server(
        *, name: str, dir: str, variables: dict[str, Any], loader: str
    ) -> None:
        _servers[name] = {
            "name": name, "dir": dir, "state": "scaffolding", "container_name": None,
            "variables": variables, "loader": loader, "scaffolded_at": None,
        }

    def mark_scaffolded(*, name: str) -> None:
        if name in _servers:
            _servers[name].update(
                state="created", scaffolded_at=datetime.now(UTC).isoformat()
            )

    def delete_server(name: str) -> None:
        _servers.pop(name, None)

    def list_players() -> list[dict[str, Any]]:
        return [_players[u] for u in sorted(_players, key=lambda u: _players[u]["name"])]

    def get_player(uuid: str) -> dict[str, Any] | None:
        return _players.get(uuid)

    def insert_player(*, uuid: str, name: str) -> None:
        _players[uuid] = {"uuid": uuid, "name": name}

    def insert_players_bulk(rows: list[dict[str, Any]]) -> None:
        for r in rows:
            _players[r["uuid"]] = {"uuid": r["uuid"], "name": r["name"]}

    def delete_player(uuid: str) -> None:
        _players.pop(uuid, None)

    def upsert_player_from_mojang(*, uuid: str, name: str) -> dict[str, Any]:
        existing = _players.get(uuid)
        if existing is None:
            _players[uuid] = {"uuid": uuid, "name": name}
            return {"created": True, "previous_name": None}
        previous = existing["name"]
        existing["name"] = name
        return {"created": False, "previous_name": previous}

    for fn in (
        list_servers, ping, get_server, insert_server, update_server_state,
        update_variables, update_bindings, insert_scaffolding_server,
        mark_scaffolded, delete_server, list_players, get_player, insert_player,
        insert_players_bulk, delete_player, upsert_player_from_mojang,
    ):
        setattr(db, fn.__name__, fn)


# ---------------------------------------------------------------------------
# FakeDocker — covers the aiodocker surface mcontrol actually calls. Container
# state is the source of truth the resources-poll reconciler reads, so start/
# stop mutate it here to stay consistent with the DB writes lifecycle makes.
# ---------------------------------------------------------------------------

_META: dict[str, dict[str, Any]] = {
    s["name"]: {"state": s["state"], "port": s["port"]} for s in _SEED
}

_LOG_LINES = [
    "[12:00:00] [Server thread/INFO]: Starting minecraft server version 1.21",
    "[12:00:01] [Server thread/INFO]: Loading properties",
    "[12:00:02] [Server thread/INFO]: Preparing level \"world\"",
    "[12:00:04] [Server thread/INFO]: Done (3.812s)! For help, type \"help\"",
    "[12:01:10] [Server thread/INFO]: Notch joined the game",
    "[12:02:33] [Server thread/WARN]: Can't keep up! Running 2100ms behind",
]


class _FakeNetwork:
    async def connect(self, **_: Any) -> None: ...
    async def disconnect(self, **_: Any) -> None: ...


class _FakeNetworks:
    async def get(self, name: str) -> _FakeNetwork:
        return _FakeNetwork()


class _FakeContainer:
    def __init__(self, name: str, docker: "FakeDocker") -> None:
        self._name = name
        self._docker = docker

    @property
    def _container(self) -> dict[str, Any]:
        return {"Names": [f"/{self._name}"], "State": _META[self._name]["state"]}

    async def start(self) -> None:
        _META[self._name]["state"] = "running"
        self._docker._bind(self._name)

    async def stop(self) -> None:
        _META[self._name]["state"] = "exited"
        self._docker._unbind(self._name)

    async def restart(self) -> None:
        _META[self._name]["state"] = "running"
        self._docker._bind(self._name)

    async def show(self) -> dict[str, Any]:
        state = _META[self._name]["state"]
        return {
            "State": {
                "Running": state == "running",
                "Status": state,
                "StartedAt": datetime.now(UTC).isoformat(),
            },
            # No network → the RCON console degrades to a friendly
            # "no docker network" message instead of a real TCP dial.
            "NetworkSettings": {"Networks": {}},
        }

    async def stats(self, stream: bool = False) -> dict[str, Any]:
        # Numbers chosen to yield a plausible ~8% CPU / ~1.3 GiB working set.
        return {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 1_020_000},
                "system_cpu_usage": 100_000_000,
                "online_cpus": 4,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 1_000_000},
                "system_cpu_usage": 99_000_000,
            },
            "memory_stats": {
                "usage": 1_500_000_000,
                "limit": 8_589_934_592,
                "stats": {"inactive_file": 200_000_000},
            },
        }

    def log(self, **_: Any):
        return self._log_gen()

    async def _log_gen(self):
        for line in _LOG_LINES:
            yield line
            await asyncio.sleep(0)


class _FakeContainers:
    def __init__(self, docker: "FakeDocker") -> None:
        self._docker = docker

    async def list(self, all: bool = False) -> list[_FakeContainer]:  # noqa: A002
        return [_FakeContainer(n, self._docker) for n in _META]

    async def get(self, name: str) -> _FakeContainer:
        if name not in _META:
            raise aiodocker.DockerError(404, {"message": f"no such container: {name}"})
        return _FakeContainer(name, self._docker)


class FakeDocker:
    """Drop-in for aiodocker.Docker covering only what mcontrol calls."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.containers = _FakeContainers(self)
        self.networks = _FakeNetworks()
        self._listeners: dict[str, socket.socket] = {}

    async def version(self) -> dict[str, str]:
        return {"Version": "dev-mock", "ApiVersion": "1.45"}

    def _bind(self, name: str) -> None:
        """Hold a real listener on the server's port so lifecycle_service's
        post-start TCP probe succeeds and Start lands on 'running' promptly."""
        port = _META[name]["port"]
        if name in self._listeners:
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            s.listen(16)
            self._listeners[name] = s
        except OSError:
            pass

    def _unbind(self, name: str) -> None:
        s = self._listeners.pop(name, None)
        if s is not None:
            s.close()

    async def close(self) -> None:
        for s in self._listeners.values():
            s.close()
        self._listeners.clear()


_scaffold_disk()
_install_fake_db()
aiodocker.Docker = FakeDocker  # lifespan constructs this → gets the fake

from mcontrol.main import create_app  # noqa: E402

app = create_app()
