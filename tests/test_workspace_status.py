import asyncio
from types import SimpleNamespace

import pytest

from mcontrol.domain import status
from mcontrol.infra import db, resources


@pytest.mark.parametrize(
    "raw,label",
    [
        ("running", "Running"),
        ("starting", "Starting"),
        ("exited", "Stopped"),
        ("created", "Stopped"),
        ("missing", "Missing"),
        (None, "Unavailable"),
        ("unreachable", "Unavailable"),
        ("dead", "Failed"),
    ],
)
def test_status_names(raw, label):
    assert status.label(raw) == label


async def test_entire_docker_read_is_bounded(monkeypatch):
    async def hung_get(_name):
        await asyncio.Event().wait()

    monkeypatch.setattr(resources, "_STATS_TIMEOUT_S", 0.01)
    docker = SimpleNamespace(containers=SimpleNamespace(get=hung_get))
    result = await asyncio.wait_for(resources.read_container_stats(docker, "hung"), 0.2)
    assert result == {"status": "unreachable"}


async def test_fleet_fragment_uses_observed_state_without_mutating_db(client, monkeypatch):
    row = {"name": "survival", "state": "running", "variables": {}}
    monkeypatch.setattr(db, "list_servers", lambda: [row])

    async def stopped(*_):
        return {"status": "not-running", "container_state": "exited"}

    monkeypatch.setattr(resources, "read_container_stats", stopped)
    response = await client.get("/fleet/status")
    assert response.status_code == 200
    assert "<html" not in response.text
    assert ">Stopped<" in response.text
    assert "data-observed-at=" in response.text
    assert row["state"] == "running"


async def test_resource_refresh_never_walks_disk(client, monkeypatch, tmp_path):
    row = {"name": "survival", "state": "exited", "dir": str(tmp_path)}
    monkeypatch.setattr(db, "get_server", lambda _: row)

    async def stopped(*_):
        return {"status": "not-running", "container_state": "exited"}

    def no_walk(_):
        raise AssertionError("Disk walk blocks fast telemetry")

    monkeypatch.setattr(resources, "read_container_stats", stopped)
    monkeypatch.setattr(resources, "read_disk_usage", no_walk)
    response = await client.get("/servers/survival/resources")
    assert response.status_code == 200


async def test_disk_is_independent_of_docker(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        db,
        "get_server",
        lambda _: {
            "name": "survival",
            "state": "running",
            "dir": str(tmp_path),
        },
    )
    (tmp_path / "world.dat").write_bytes(b"x" * 4096)

    async def no_docker(*_):
        raise AssertionError("Disk usage should not need Docker")

    monkeypatch.setattr(resources, "read_container_stats", no_docker)
    response = await client.get("/servers/survival/disk")
    assert response.status_code == 200
    assert "4.0 KiB" in response.text
    assert "every 60s" in response.text


async def test_fleet_failure_returns_retryable_status(client, monkeypatch):
    monkeypatch.setattr(db, "list_servers", lambda: [{"name": "survival", "state": "running"}])

    async def unavailable(*_):
        return {"status": "unreachable"}

    monkeypatch.setattr(resources, "read_container_stats", unavailable)
    response = await client.get("/fleet/status")
    assert response.status_code == 503
    assert "Last fleet values may be stale" in response.json()["detail"]
    first_visit = await client.get("/")
    assert first_visit.status_code == 200
    assert ">Unavailable<" in first_visit.text
    assert 'aria-label="Start survival"' not in first_visit.text
