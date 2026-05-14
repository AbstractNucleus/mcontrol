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
        await server_rcon.run_command(object(), server, "whitelist add Notch")


async def test_run_command_raises_when_password_empty(tmp_path):
    server = _server_with_props(
        tmp_path, "enable-rcon=true\nrcon.password=\n"
    )

    with pytest.raises(server_rcon.RconUnavailable, match="empty"):
        await server_rcon.run_command(object(), server, "whitelist add Notch")


async def test_run_command_raises_when_properties_file_missing(tmp_path):
    server_dir = tmp_path / "atm10"
    (server_dir / "server").mkdir(parents=True)
    server = {"name": "atm10", "container_name": None, "dir": str(server_dir)}

    with pytest.raises(server_rcon.RconUnavailable, match="not enabled"):
        await server_rcon.run_command(object(), server, "whitelist add Notch")


async def test_run_command_raises_when_no_docker_network(tmp_path, monkeypatch):
    server = _server_with_props(
        tmp_path, "enable-rcon=true\nrcon.password=secret\n"
    )

    async def fake_find(_docker, name):
        return None

    from mcontrol import docker_client

    monkeypatch.setattr(docker_client, "find_network_name", fake_find)

    with pytest.raises(server_rcon.RconUnavailable, match="No docker network"):
        await server_rcon.run_command(object(), server, "whitelist add Notch")


# ---------------------------------------------------------------------------
# Stale-password detection (issue 119)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_password_cache():
    """Each test starts with an empty cache so module-level state doesn't leak."""
    server_rcon._last_authed_password.clear()
    yield
    server_rcon._last_authed_password.clear()


def _running_server(tmp_path: Path, props_body: str) -> dict:
    server = _server_with_props(tmp_path, props_body)
    server["state"] = "running"
    return server


def test_stale_password_false_when_no_baseline(tmp_path):
    server = _running_server(tmp_path, "enable-rcon=true\nrcon.password=secret\n")
    assert server_rcon.stale_password_detected(server) is False


def test_stale_password_false_when_disk_matches_cache(tmp_path):
    server = _running_server(tmp_path, "enable-rcon=true\nrcon.password=secret\n")
    server_rcon.record_authed_password(server["name"], "secret")
    assert server_rcon.stale_password_detected(server) is False


def test_stale_password_true_when_disk_differs_from_cache(tmp_path):
    server = _running_server(tmp_path, "enable-rcon=true\nrcon.password=new-secret\n")
    server_rcon.record_authed_password(server["name"], "old-secret")
    assert server_rcon.stale_password_detected(server) is True


def test_stale_password_false_when_not_running(tmp_path):
    """An exited server has no JVM to be stale — operator restart will pick up disk anyway."""
    server = _server_with_props(tmp_path, "enable-rcon=true\nrcon.password=new-secret\n")
    server["state"] = "exited"
    server_rcon.record_authed_password(server["name"], "old-secret")
    assert server_rcon.stale_password_detected(server) is False


def test_stale_password_false_when_disk_password_empty(tmp_path):
    """Empty disk password isn't 'stale' — it's the operator-managed-disable path."""
    server = _running_server(tmp_path, "enable-rcon=true\nrcon.password=\n")
    server_rcon.record_authed_password(server["name"], "old-secret")
    assert server_rcon.stale_password_detected(server) is False


def test_forget_authed_password_clears_baseline(tmp_path):
    server = _running_server(tmp_path, "enable-rcon=true\nrcon.password=new-secret\n")
    server_rcon.record_authed_password(server["name"], "old-secret")
    server_rcon.forget_authed_password(server["name"])
    assert server_rcon.stale_password_detected(server) is False


def test_forget_authed_password_is_idempotent_when_missing():
    server_rcon.forget_authed_password("never-recorded")  # no KeyError
