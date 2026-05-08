"""Tests for server_rcon.run_command's pre-flight checks.

The RCON wire path itself is exercised by the slice-4 test_console
integration tests + manual smoke-testing on the real fleet; these
tests cover the slice-7-specific pre-flight contract: clear errors
when ``enable-rcon=false``, ``rcon.password`` empty, or no docker
network is attached."""

from pathlib import Path

import pytest

from mcontrol import server_rcon


def _server_with_props(tmp_path: Path, props_body: str) -> dict:
    server_dir = tmp_path / "atm10"
    (server_dir / "server").mkdir(parents=True)
    (server_dir / "server" / "server.properties").write_text(props_body)
    return {"name": "atm10", "container_name": None, "dir": str(server_dir)}


async def test_run_command_raises_when_rcon_disabled(tmp_path):
    server = _server_with_props(
        tmp_path, "enable-rcon=false\nrcon.password=secret\n"
    )

    with pytest.raises(server_rcon.RconUnavailable, match="not enabled"):
        await server_rcon.run_command(server, "whitelist add Notch")


async def test_run_command_raises_when_password_empty(tmp_path):
    server = _server_with_props(
        tmp_path, "enable-rcon=true\nrcon.password=\n"
    )

    with pytest.raises(server_rcon.RconUnavailable, match="empty"):
        await server_rcon.run_command(server, "whitelist add Notch")


async def test_run_command_raises_when_properties_file_missing(tmp_path):
    server_dir = tmp_path / "atm10"
    (server_dir / "server").mkdir(parents=True)
    server = {"name": "atm10", "container_name": None, "dir": str(server_dir)}

    with pytest.raises(server_rcon.RconUnavailable, match="not enabled"):
        await server_rcon.run_command(server, "whitelist add Notch")


async def test_run_command_raises_when_no_docker_network(tmp_path, monkeypatch):
    server = _server_with_props(
        tmp_path, "enable-rcon=true\nrcon.password=secret\n"
    )

    async def fake_find(name):
        return None

    from mcontrol import docker_client

    monkeypatch.setattr(docker_client, "find_network_name", fake_find)

    with pytest.raises(server_rcon.RconUnavailable, match="No docker network"):
        await server_rcon.run_command(server, "whitelist add Notch")
