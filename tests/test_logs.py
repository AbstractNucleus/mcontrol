import pytest


@pytest.fixture
def fake_logs(monkeypatch):
    """Stub docker_client.logs_stream to yield predefined lines."""
    lines: list[str] = []

    async def fake(_docker, name, *, tail=200):
        for line in lines:
            yield line

    from mcontrol.infra import docker_client

    monkeypatch.setattr(docker_client, "logs_stream", fake)
    return lines


@pytest.fixture
def fake_get_server(monkeypatch):
    rows: dict[str, dict] = {}
    from mcontrol.infra import db
    monkeypatch.setattr(db, "get_server", lambda n: rows.get(n))
    return rows


async def test_logs_endpoint_returns_404_for_unknown_server(client, fake_get_server, fake_logs):
    response = await client.get("/servers/unknown/logs")
    assert response.status_code == 404


async def _stream_text(client, url, headers=None):
    async with client.stream("GET", url, headers=headers or {}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = b""
        async for chunk in response.aiter_bytes():
            body += chunk
    return body.decode("utf-8")


async def test_logs_endpoint_streams_sse_with_each_line(client, fake_get_server, fake_logs):
    fake_get_server["atm10"] = {"name": "atm10", "container_name": None, "dir": "/srv/atm10"}
    fake_logs.extend(["[INFO] starting", "[INFO] done"])

    text = await _stream_text(client, "/servers/atm10/logs")

    assert "[INFO] starting" in text
    assert "[INFO] done" in text
    # Each event must carry a trailing-newline data payload (via the
    # two-"data:"-line trick) so lines don't run together in the <pre>
    # under hx-swap="beforeend". Per the SSE spec, two data lines in one
    # event are joined with \n on the client. Payloads are wrapped in a
    # classified span since the client swaps them as HTML.
    assert 'data: <span class="log-line">[INFO] starting</span>\ndata: \n\n' in text
    assert 'data: <span class="log-line">[INFO] done</span>\ndata: \n\n' in text


async def test_logs_lines_are_html_escaped(client, fake_get_server, fake_logs):
    """Player chat legitimately contains <>&; unescaped it would be parsed
    as markup by the client's HTML swap (vanishing lines / XSS)."""
    fake_get_server["atm10"] = {"name": "atm10", "container_name": None, "dir": "/srv/atm10"}
    fake_logs.append("[INFO] <Notch> hello & welcome")

    text = await _stream_text(client, "/servers/atm10/logs")

    assert "&lt;Notch&gt; hello &amp; welcome" in text
    assert "<Notch>" not in text


async def test_logs_classify_levels(client, fake_get_server, fake_logs):
    fake_get_server["atm10"] = {"name": "atm10", "container_name": None, "dir": "/srv/atm10"}
    fake_logs.extend(
        [
            "[12:00:01] [Server thread/WARN]: Can't keep up!",
            "[12:00:02] [Server thread/ERROR]: something broke",
        ]
    )

    text = await _stream_text(client, "/servers/atm10/logs")

    assert 'class="log-line log-line--warn"' in text
    assert 'class="log-line log-line--error"' in text


async def test_logs_emit_closed_event_when_stream_ends(client, fake_get_server, fake_logs):
    """A finished stream (container stopped) must tell the client to close
    instead of letting EventSource reconnect and replay forever."""
    fake_get_server["atm10"] = {"name": "atm10", "container_name": None, "dir": "/srv/atm10"}
    fake_logs.append("[INFO] bye")

    text = await _stream_text(client, "/servers/atm10/logs")

    assert "log stream ended" in text
    assert "event: closed" in text


async def test_logs_reconnect_skips_backlog_tail(client, fake_get_server, monkeypatch):
    """A reconnecting EventSource presents Last-Event-ID; the route must not
    replay the 200-line backlog on top of what the pane already shows."""
    fake_get_server["atm10"] = {"name": "atm10", "container_name": None, "dir": "/srv/atm10"}
    tails: list[int] = []

    async def fake(_docker, name, *, tail=200):
        tails.append(tail)
        return
        yield  # pragma: no cover  (make this an async generator)

    from mcontrol.infra import docker_client
    monkeypatch.setattr(docker_client, "logs_stream", fake)

    await _stream_text(client, "/servers/atm10/logs")
    await _stream_text(client, "/servers/atm10/logs", headers={"Last-Event-ID": "42"})

    assert tails == [200, 0]


async def test_logs_docker_error_closes_stream(client, fake_get_server, monkeypatch):
    """A missing container yields one info line + closed, not a 500 and not
    an infinite reconnect loop."""
    import aiodocker

    fake_get_server["atm10"] = {"name": "atm10", "container_name": None, "dir": "/srv/atm10"}

    async def fake(_docker, name, *, tail=200):
        raise aiodocker.DockerError(404, {"message": "no such container"})
        yield  # pragma: no cover

    from mcontrol.infra import docker_client
    monkeypatch.setattr(docker_client, "logs_stream", fake)

    text = await _stream_text(client, "/servers/atm10/logs")

    assert "container not found" in text
    assert "event: closed" in text


async def test_logs_endpoint_uses_container_name_override(client, fake_get_server, monkeypatch):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": "atm10-prod", "dir": "/srv/atm10",
    }
    seen: list[str] = []

    async def fake(_docker, name, *, tail=200):
        seen.append(name)
        return
        yield  # pragma: no cover  (make this an async generator)

    from mcontrol.infra import docker_client
    monkeypatch.setattr(docker_client, "logs_stream", fake)

    async with client.stream("GET", "/servers/atm10/logs") as response:
        async for _ in response.aiter_bytes():
            pass

    assert seen == ["atm10-prod"]
