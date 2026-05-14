import pytest


@pytest.fixture
def fake_servers(monkeypatch):
    rows: list[dict] = []

    def fake_list_servers():
        return rows

    from mcontrol import db

    monkeypatch.setattr(db, "list_servers", fake_list_servers)
    return rows


@pytest.fixture
def fake_stats(monkeypatch):
    """Per-container responder for resources.read_container_stats.

    Defaults each container to {"status": "unreachable"} so unconfigured
    tests don't accidentally hit a real Docker socket. Set an entry to
    a dict to return it; set to an Exception instance to have the call
    raise.
    """
    by_name: dict[str, object] = {}

    async def fake_read(_docker, container_name: str):
        result = by_name.get(container_name, {"status": "unreachable"})
        if isinstance(result, Exception):
            raise result
        return result

    from mcontrol import resources

    monkeypatch.setattr(resources, "read_container_stats", fake_read)
    return by_name


async def test_home_renders_wordmark(client, fake_servers, fake_stats):
    response = await client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "mcontrol" in body
    assert "/static/tokens.css" in body
    assert "/static/app.css" in body


async def test_home_shows_empty_state_when_no_servers(client, fake_servers, fake_stats):
    response = await client.get("/")

    assert response.status_code == 200
    assert "No servers yet" in response.text


async def test_home_lists_servers_when_present(client, fake_servers, fake_stats):
    fake_servers.append({"name": "atm10", "state": "running"})
    fake_servers.append({"name": "monifactory", "state": "exited"})

    response = await client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "atm10" in body
    assert "monifactory" in body
    assert "running" in body
    assert "exited" in body
    assert "No servers yet" not in body


async def test_home_links_each_server_to_detail_page(client, fake_servers, fake_stats):
    fake_servers.append({"name": "atm10", "state": "running"})

    response = await client.get("/")

    assert response.status_code == 200
    assert 'href="/servers/atm10"' in response.text


async def test_home_links_to_central_players_page(client, fake_servers, fake_stats):
    response = await client.get("/")

    assert response.status_code == 200
    assert 'href="/players"' in response.text


# ---------------------------------------------------------------------------
# Memory column (slice 10)
# ---------------------------------------------------------------------------


def _row_block(html: str, name: str) -> str:
    """Return the slice of `html` covering one server-card <li>.

    Cards are rendered in db-row order; we slice from the row's name
    anchor to the next card start (or list end) so per-row assertions
    can target the right block.
    """
    anchor = f'href="/servers/{name}"'
    start = html.index(anchor)
    list_start = html.rfind("<li", 0, start)
    next_li = html.find("<li", start)
    end = next_li if next_li != -1 else html.find("</ul>", start)
    return html[list_start:end]


async def test_home_renders_memory_for_running_row(client, fake_servers, fake_stats):
    fake_servers.append({"name": "atm10", "state": "running"})
    fake_stats["atm10"] = {
        "status": "ok",
        "cpu_percent": 12.4,
        "mem_used": 8 * 1024**3,
        "mem_limit": 12 * 1024**3,
    }

    response = await client.get("/")

    assert response.status_code == 200
    block = _row_block(response.text, "atm10")
    assert "8.0 GiB / 12.0 GiB" in block
    assert "(67 %)" in block


async def test_home_renders_dash_when_container_not_running(
    client, fake_servers, fake_stats
):
    fake_servers.append({"name": "atm10", "state": "exited"})
    fake_stats["atm10"] = {"status": "not-running"}

    response = await client.get("/")

    assert response.status_code == 200
    block = _row_block(response.text, "atm10")
    assert "—" in block
    assert "GiB" not in block


async def test_home_tolerates_stats_failure_on_one_row(
    client, fake_servers, fake_stats
):
    """A stats call that raises must not 500 the page — that row shows
    a dash, the other rows render their live numbers."""
    fake_servers.append({"name": "atm10", "state": "running"})
    fake_servers.append({"name": "monifactory", "state": "running"})

    fake_stats["atm10"] = RuntimeError("daemon hiccup mid-render")
    fake_stats["monifactory"] = {
        "status": "ok",
        "cpu_percent": 5.0,
        "mem_used": 4 * 1024**3,
        "mem_limit": 8 * 1024**3,
    }

    response = await client.get("/")

    assert response.status_code == 200
    atm10_block = _row_block(response.text, "atm10")
    moni_block = _row_block(response.text, "monifactory")
    assert "—" in atm10_block
    assert "GiB" not in atm10_block
    assert "4.0 GiB / 8.0 GiB" in moni_block
    assert "(50 %)" in moni_block


async def test_home_resolves_container_name_override(
    client, fake_servers, fake_stats
):
    """Decision 021: the stats lookup goes through container_name_for."""
    fake_servers.append(
        {"name": "atm10", "state": "running", "container_name": "mc-atm10-prod"}
    )
    fake_stats["mc-atm10-prod"] = {
        "status": "ok",
        "cpu_percent": 0.0,
        "mem_used": 1 * 1024**3,
        "mem_limit": 2 * 1024**3,
    }

    response = await client.get("/")

    assert response.status_code == 200
    block = _row_block(response.text, "atm10")
    assert "1.0 GiB / 2.0 GiB" in block
