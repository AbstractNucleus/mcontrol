import pytest


@pytest.fixture
def fake_logs(monkeypatch):
    """Stub docker_client.logs_stream to yield predefined lines."""
    lines: list[str] = []

    async def fake(name, *, tail=200):
        for line in lines:
            yield line

    from mcontrol import docker_client

    monkeypatch.setattr(docker_client, "logs_stream", fake)
    return lines


@pytest.fixture
def fake_get_server(monkeypatch):
    rows: dict[str, dict] = {}
    from mcontrol import db
    monkeypatch.setattr(db, "get_server", lambda n: rows.get(n))
    return rows


async def test_logs_endpoint_returns_404_for_unknown_server(client, fake_get_server, fake_logs):
    response = await client.get("/servers/unknown/logs")
    assert response.status_code == 404


async def test_logs_endpoint_streams_sse_with_each_line(client, fake_get_server, fake_logs):
    fake_get_server["atm10"] = {"name": "atm10", "container_name": None, "dir": "/srv/atm10"}
    fake_logs.extend(["[INFO] starting", "[INFO] done"])

    async with client.stream("GET", "/servers/atm10/logs") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        body = b""
        async for chunk in response.aiter_bytes():
            body += chunk
        text = body.decode("utf-8")

    assert "data: [INFO] starting" in text
    assert "data: [INFO] done" in text


async def test_logs_endpoint_uses_container_name_override(client, fake_get_server, monkeypatch):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": "atm10-prod", "dir": "/srv/atm10",
    }
    seen: list[str] = []

    async def fake(name, *, tail=200):
        seen.append(name)
        return
        yield  # pragma: no cover  (make this an async generator)

    from mcontrol import docker_client
    monkeypatch.setattr(docker_client, "logs_stream", fake)

    async with client.stream("GET", "/servers/atm10/logs") as response:
        async for _ in response.aiter_bytes():
            pass

    assert seen == ["atm10-prod"]
