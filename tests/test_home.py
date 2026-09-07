import re

import pytest


@pytest.fixture
def fake_servers(monkeypatch):
    rows: list[dict] = []

    def fake_list_servers():
        return rows

    from mcontrol.infra import db

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

    from mcontrol.infra import resources

    monkeypatch.setattr(resources, "read_container_stats", fake_read)
    return by_name


async def test_home_renders_wordmark(client, fake_servers, fake_stats):
    response = await client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "mcontrol" in body
    assert "/static/tokens.css" in body
    assert "/static/app.shell.css" in body
    assert "/static/app.misc.css" in body


async def test_home_shows_empty_state_when_no_servers(client, fake_servers, fake_stats):
    response = await client.get("/")

    assert response.status_code == 200
    assert "No servers yet" in response.text


async def test_home_lists_servers_when_present(client, fake_servers, fake_stats):
    fake_servers.append({"name": "atm10", "state": "running"})
    fake_servers.append({"name": "monifactory", "state": "exited"})

    response = await client.get("/", headers={"Accept": "text/html"})

    assert response.status_code == 200
    body = response.text
    assert "atm10" in body
    assert "monifactory" in body
    assert "running" in body
    assert "Unavailable" in body
    assert "No servers yet" not in body


async def test_sidebar_lists_servers(client, fake_servers, fake_stats):
    """The left rail is populated from request.state (prefetched off the
    render path by the _prime_sidebar middleware), not a blocking DB call
    inside the Jinja global. Assert the server appears specifically inside
    the <aside class="sidebar"> block, not just anywhere on the page."""
    fake_servers.append({"name": "atm10", "state": "running"})

    response = await client.get("/", headers={"Accept": "text/html"})

    assert response.status_code == 200
    body = response.text
    aside = body[body.index('<aside id="primary-sidebar"') : body.index("</aside>")]
    assert 'sidebar__server-name">atm10' in aside


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
    can target the right block. Anchors on ``class="server-card__name"``
    rather than the bare ``href`` because the sidebar (rendered into
    every page) also links each server by ``href="/servers/{name}"``.
    """
    anchor = f'class="server-card__name" href="/servers/{name}"'
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
    assert "Not running" in block
    assert "GiB" not in block


async def test_home_tolerates_stats_failure_on_one_row(
    client, fake_servers, fake_stats
):
    """A stats call that raises must not 500 the page. That row shows
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
    assert "Unavailable" in atm10_block
    assert "GiB" not in atm10_block
    assert "4.0 GiB / 8.0 GiB" in moni_block
    assert "(50 %)" in moni_block


async def test_home_resolves_container_name_override(
    client, fake_servers, fake_stats
):
    """The stats lookup goes through container_name_for."""
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


async def test_home_fleet_row_targets_closest_li(
    client, fake_servers, fake_stats
):
    """Names with dots would break `#fleet-row-foo.bar` as a CSS selector."""
    fake_servers.append({"name": "foo.bar", "state": "running"})
    fake_stats["foo.bar"] = {"status": "not-running", "container_state": "exited"}

    response = await client.get("/")

    assert response.status_code == 200
    block = _row_block(response.text, "foo.bar")
    assert 'hx-target="closest li"' in block
    assert 'hx-target="#fleet-row-foo.bar"' not in block


async def test_home_summary_running_uses_live_stats_not_db(
    client, fake_servers, fake_stats
):
    """DB says ghost is running but Docker has no container; atm10 is
    live even though the row still says exited."""
    fake_servers.append({"name": "ghost", "state": "running"})
    fake_servers.append({"name": "atm10", "state": "exited"})
    fake_stats["atm10"] = {
        "status": "ok",
        "cpu_percent": 1.0,
        "mem_used": 1024,
        "mem_limit": 2048,
    }

    body = (await client.get("/")).text

    metrics = dict(re.findall(
        r'<span class="fleet-insight__label">(Total servers|Running).*?</span>'
        r'<strong>(\d+)</strong>', body, re.DOTALL,
    ))
    assert metrics == {"Total servers": "2", "Running": "1"}


async def test_prime_sidebar_skips_when_accept_lacks_html(
    client, fake_servers, fake_stats, monkeypatch
):
    from mcontrol.infra import db

    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return list(fake_servers)

    monkeypatch.setattr(db, "list_servers", counting)

    # /servers/new does not itself call list_servers, so the counter
    # isolates the middleware.
    await client.get("/servers/new", headers={"Accept": "application/json"})
    assert calls["n"] == 0

    await client.get("/servers/new", headers={"Accept": "text/html"})
    assert calls["n"] == 1


async def test_prime_sidebar_skips_logs_and_download_paths(
    client, fake_servers, fake_stats, monkeypatch
):
    from mcontrol.infra import db

    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return list(fake_servers)

    monkeypatch.setattr(db, "list_servers", counting)
    monkeypatch.setattr(db, "get_server", lambda _n: None)

    await client.get("/servers/atm10/logs", headers={"Accept": "text/html"})
    await client.get(
        "/servers/atm10/files/download",
        headers={"Accept": "text/html"},
        params={"path": "x"},
    )
    await client.get("/servers/atm10/rcon", headers={"Accept": "text/html"})
    assert calls["n"] == 0
