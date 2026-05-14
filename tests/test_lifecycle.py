import pytest


@pytest.fixture
def fake_server_row(monkeypatch):
    rows: dict[str, dict] = {}

    def fake_get(name):
        return rows.get(name)

    from mcontrol import db

    monkeypatch.setattr(db, "get_server", fake_get)
    return rows


@pytest.fixture
def stub_db_writes(monkeypatch):
    seen: list[tuple[str, dict]] = []
    from mcontrol import db

    def cap(label):
        def fn(**kwargs):
            seen.append((label, kwargs))
        return fn

    monkeypatch.setattr(db, "update_server_state", cap("update_server_state"))
    return seen


@pytest.fixture
def stub_docker(monkeypatch):
    from mcontrol import docker_client

    started: list[str] = []
    stopped: list[str] = []
    restarted: list[str] = []

    async def fake_start(_docker, name): started.append(name)
    async def fake_stop(_docker, name): stopped.append(name)
    async def fake_restart(_docker, name): restarted.append(name)

    monkeypatch.setattr(docker_client, "start", fake_start)
    monkeypatch.setattr(docker_client, "stop", fake_stop)
    monkeypatch.setattr(docker_client, "restart", fake_restart)

    return {"started": started, "stopped": stopped, "restarted": restarted}


async def test_stop_calls_docker_stop_and_returns_state_pill(
    client, fake_server_row, stub_db_writes, stub_docker
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "running",
    }

    response = await client.post("/servers/atm10/lifecycle/stop")

    assert response.status_code == 200
    assert "exited" in response.text  # state-pill text
    assert stub_docker["stopped"] == ["atm10"]
    assert ("update_server_state", {"name": "atm10", "state": "exited"}) in stub_db_writes


async def test_start_calls_docker_start_and_returns_state_pill(
    client, fake_server_row, stub_db_writes, stub_docker
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "exited",
    }

    response = await client.post("/servers/atm10/lifecycle/start")

    assert response.status_code == 200
    assert "running" in response.text
    assert stub_docker["started"] == ["atm10"]
    assert ("update_server_state", {"name": "atm10", "state": "running"}) in stub_db_writes


async def test_restart_calls_docker_restart_and_returns_state_pill(
    client, fake_server_row, stub_db_writes, stub_docker
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "running",
    }

    response = await client.post("/servers/atm10/lifecycle/restart")

    assert response.status_code == 200
    assert "running" in response.text
    assert stub_docker["restarted"] == ["atm10"]
    assert ("update_server_state", {"name": "atm10", "state": "running"}) in stub_db_writes


async def test_lifecycle_returns_404_for_unknown_server(
    client, fake_server_row, stub_docker
):
    response = await client.post("/servers/unknown/lifecycle/start")
    assert response.status_code == 404


async def test_start_timeout_returns_flash_and_does_not_update_state(
    client, fake_server_row, stub_db_writes, monkeypatch
):

    from mcontrol import docker_client

    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "exited",
    }

    async def _timeout(_docker, name): raise TimeoutError()
    monkeypatch.setattr(docker_client, "start", _timeout)

    response = await client.post("/servers/atm10/lifecycle/start")

    assert response.status_code == 200
    assert "lifecycle-flash--error" in response.text
    assert stub_db_writes == []


async def test_stop_timeout_returns_flash_and_does_not_update_state(
    client, fake_server_row, stub_db_writes, monkeypatch
):

    from mcontrol import docker_client

    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "running",
    }

    async def _timeout(_docker, name): raise TimeoutError()
    monkeypatch.setattr(docker_client, "stop", _timeout)

    response = await client.post("/servers/atm10/lifecycle/stop")

    assert response.status_code == 200
    assert "lifecycle-flash--error" in response.text
    assert stub_db_writes == []


async def test_restart_timeout_returns_flash_and_does_not_update_state(
    client, fake_server_row, stub_db_writes, monkeypatch
):

    from mcontrol import docker_client

    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "running",
    }

    async def _timeout(_docker, name): raise TimeoutError()
    monkeypatch.setattr(docker_client, "restart", _timeout)

    response = await client.post("/servers/atm10/lifecycle/restart")

    assert response.status_code == 200
    assert "lifecycle-flash--error" in response.text
    assert stub_db_writes == []


async def test_lifecycle_uses_container_name_override(
    client, fake_server_row, stub_db_writes, stub_docker
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": "atm10-prod", "dir": "/srv/atm10",
        "state": "running",
    }

    await client.post("/servers/atm10/lifecycle/stop")

    assert stub_docker["stopped"] == ["atm10-prod"]


def _button_chunk(body: str, verb: str) -> str:
    """Return the substring from `<button ...` through `</button>` for the
    lifecycle button whose `hx-post` targets `/lifecycle/{verb}`. The
    class attribute (where `btn--primary` lives) sits before `hx-post`,
    so we have to walk back to the opening `<button` tag, not just split
    on the URL.
    """
    needle = f"lifecycle/{verb}"
    idx = body.index(needle)
    open_tag = body.rfind("<button", 0, idx)
    close_tag = body.index("</button>", idx)
    return body[open_tag:close_tag]


def _is_disabled(chunk: str) -> bool:
    """Match the standalone `disabled` attribute, not `hx-disabled-elt`.
    Decision 039 added `hx-disabled-elt="this"` to every lifecycle button
    for in-flight htmx-driven disable, so a naive `'disabled' in chunk`
    matches both."""
    return " disabled>" in chunk or " disabled " in chunk


async def test_stop_response_carries_oob_buttons_for_stopped_state(
    client, fake_server_row, stub_db_writes, stub_docker
):
    """After Stop, the response carries both the state pill AND an OOB
    swap of the lifecycle-buttons wrapper rebuilt for state=exited:
    Start enabled + accent, Stop + Restart disabled."""
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "running",
    }

    response = await client.post("/servers/atm10/lifecycle/stop")
    body = response.text

    assert 'id="state-pill"' in body
    assert 'state-pill--exited' in body

    # OOB swap wrapper for the buttons block.
    assert 'id="lifecycle-buttons"' in body
    assert 'hx-swap-oob="true"' in body

    start = _button_chunk(body, "start")
    assert 'btn--primary' in start
    assert not _is_disabled(start)

    stop = _button_chunk(body, "stop")
    assert _is_disabled(stop)
    assert 'btn--primary' not in stop

    restart = _button_chunk(body, "restart")
    assert _is_disabled(restart)
    assert 'btn--primary' not in restart


async def test_stop_response_carries_data_state_for_announcement(
    client, fake_server_row, stub_db_writes, stub_docker
):
    """Decision 039: the OOB-swapped lifecycle-buttons wrapper carries
    `data-state` reflecting the new state, so `static/lifecycle.js` can
    announce it into the aria-live region without re-deriving from CSS
    classes."""
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "running",
    }

    response = await client.post("/servers/atm10/lifecycle/stop")
    body = response.text
    wrapper_open = body.split('id="lifecycle-buttons"', 1)[1].split('>', 1)[0]
    assert 'data-state="exited"' in wrapper_open


async def test_start_response_carries_oob_buttons_for_running_state(
    client, fake_server_row, stub_db_writes, stub_docker
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "exited",
    }

    response = await client.post("/servers/atm10/lifecycle/start")
    body = response.text

    assert 'state-pill--running' in body
    assert 'id="lifecycle-buttons"' in body
    assert 'hx-swap-oob="true"' in body

    start = _button_chunk(body, "start")
    assert _is_disabled(start)
    assert 'btn--primary' not in start

    stop = _button_chunk(body, "stop")
    assert 'btn--primary' in stop
    assert not _is_disabled(stop)

    restart = _button_chunk(body, "restart")
    assert not _is_disabled(restart)
