import pytest


@pytest.fixture
def fake_get_server(monkeypatch):
    rows: dict[str, dict | None] = {}

    from mcontrol import db
    monkeypatch.setattr(db, "get_server", rows.get)
    return rows


def _row(
    name: str,
    *,
    state: str = "running",
) -> dict:
    return {
        "name": name,
        "container_name": None,
        "dir": f"/srv/{name}",
        "state": state,
        "variables": {},
        "created_at": "2026-04-29T10:00:00Z",
        "updated_at": "2026-04-29T10:00:00Z",
    }


async def test_server_detail_returns_404_when_unknown(client, fake_get_server):
    response = await client.get("/servers/does-not-exist")

    assert response.status_code == 404


async def test_server_detail_renders_known_server(client, fake_get_server):
    fake_get_server["atm10"] = {
        "name": "atm10",
        "container_name": None,
        "dir": "/home/abstract/servers/minecraft/atm10",
        "state": "running",
        "variables": {"memory_budget_gb": 12, "port": 25565},
        "created_at": "2026-04-29T10:00:00Z",
        "updated_at": "2026-04-29T10:00:00Z",
    }

    response = await client.get("/servers/atm10")

    assert response.status_code == 200
    body = response.text
    assert "atm10" in body
    assert "/home/abstract/servers/minecraft/atm10" in body
    assert "running" in body
    assert "memory_budget_gb" in body
    assert "25565" in body


async def test_server_detail_renders_lifecycle_buttons(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    body = response.text
    assert 'hx-post="/servers/atm10/lifecycle/start"' in body
    assert 'hx-post="/servers/atm10/lifecycle/stop"' in body
    assert 'hx-post="/servers/atm10/lifecycle/restart"' in body


def _button_chunk(body: str, verb: str) -> str:
    """Return the `<button ...>...</button>` substring for the lifecycle
    button targeting `/lifecycle/{verb}`. Class lives before `hx-post`,
    so walk back to the opening tag."""
    needle = f"lifecycle/{verb}"
    idx = body.index(needle)
    open_tag = body.rfind("<button", 0, idx)
    close_tag = body.index("</button>", idx)
    return body[open_tag:close_tag]


def _is_disabled(chunk: str) -> bool:
    """Standalone `disabled` attribute (not `hx-disabled-elt`, which
    decision 039 added to every lifecycle button)."""
    return " disabled>" in chunk or " disabled " in chunk


async def test_server_detail_running_state_accents_stop_disables_start(
    client, fake_get_server
):
    fake_get_server["atm10"] = _row("atm10", state="running")
    response = await client.get("/servers/atm10")
    body = response.text

    # The initial render wraps the buttons in the partial, no OOB attribute.
    assert 'id="lifecycle-buttons"' in body
    wrapper_open = body.split('id="lifecycle-buttons"', 1)[1].split('>', 1)[0]
    assert 'hx-swap-oob' not in wrapper_open

    start = _button_chunk(body, "start")
    assert _is_disabled(start)
    assert 'btn--primary' not in start

    stop = _button_chunk(body, "stop")
    assert 'btn--primary' in stop
    assert not _is_disabled(stop)

    restart = _button_chunk(body, "restart")
    assert not _is_disabled(restart)


async def test_server_detail_exited_state_accents_start_disables_others(
    client, fake_get_server
):
    fake_get_server["atm10"] = _row("atm10", state="exited")
    response = await client.get("/servers/atm10")
    body = response.text

    start = _button_chunk(body, "start")
    assert 'btn--primary' in start
    assert not _is_disabled(start)

    stop = _button_chunk(body, "stop")
    assert _is_disabled(stop)

    restart = _button_chunk(body, "restart")
    assert _is_disabled(restart)


async def test_server_detail_restarting_state_disables_all_no_accent(
    client, fake_get_server
):
    fake_get_server["atm10"] = _row("atm10", state="restarting")
    response = await client.get("/servers/atm10")
    body = response.text

    for verb in ("start", "stop", "restart"):
        chunk = _button_chunk(body, verb)
        assert _is_disabled(chunk), f"{verb} should be disabled in restarting state"
        assert 'btn--primary' not in chunk, f"{verb} should not carry accent in restarting state"


def _element_chunk(body: str, element_id: str) -> str:
    """Return the opening-tag substring for the element with `id="<element_id>"`."""
    needle = f'id="{element_id}"'
    idx = body.index(needle)
    open_tag = body.rfind('<', 0, idx)
    close_tag = body.index('>', idx)
    return body[open_tag:close_tag + 1]


async def test_server_detail_lifecycle_buttons_carry_a11y_attrs(
    client, fake_get_server
):
    """Decision 039: each lifecycle button opts into static/lifecycle.js
    via `data-lifecycle-button`, carries a server-scoped `aria-label`,
    uses `hx-disabled-elt="this"` so htmx disables on click, and is a
    native `<button>` (keyboard-activatable for free)."""
    fake_get_server["atm10"] = _row("atm10", state="running")
    response = await client.get("/servers/atm10")
    body = response.text

    for verb in ("start", "stop", "restart"):
        chunk = _button_chunk(body, verb)
        assert "data-lifecycle-button" in chunk, f"{verb} missing opt-in attr"
        assert f'aria-label="{verb.title()} atm10"' in chunk, f"{verb} aria-label"
        assert 'hx-disabled-elt="this"' in chunk, f"{verb} missing hx-disabled-elt"
        assert 'type="button"' in chunk, f"{verb} should be type=button"


async def test_server_detail_lifecycle_buttons_wrapper_carries_state(
    client, fake_get_server
):
    """The wrapper carries `data-state` so static/lifecycle.js can read
    the current state back when announcing post-action transitions."""
    fake_get_server["atm10"] = _row("atm10", state="running")
    response = await client.get("/servers/atm10")
    body = response.text
    wrapper_open = body.split('id="lifecycle-buttons"', 1)[1].split('>', 1)[0]
    assert 'data-state="running"' in wrapper_open


async def test_server_detail_renders_aria_live_lifecycle_status(
    client, fake_get_server
):
    """A visually-hidden aria-live region sits next to the lifecycle row
    so screen readers get post-action state announcements (decision 039)."""
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    body = response.text
    assert 'id="lifecycle-status"' in body
    region = body.split('id="lifecycle-status"', 1)[1].split('>', 1)[0]
    assert 'aria-live="polite"' in region
    assert 'aria-atomic="true"' in region
    assert 'visually-hidden' in region


async def test_server_detail_renders_log_pane(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    body = response.text
    assert 'sse-connect="/servers/atm10/logs"' in body

    # Live, chronological log feed: screen readers need role="log" + a name.
    log_stream = _element_chunk(body, "log-stream")
    assert 'role="log"' in log_stream
    assert 'aria-live="polite"' in log_stream
    assert 'aria-atomic="false"' in log_stream
    assert 'aria-label="Server log output"' in log_stream


async def test_server_detail_renders_console_pane(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    body = response.text
    assert 'sse-connect="/servers/atm10/rcon"' in body
    assert 'hx-post="/servers/atm10/rcon"' in body

    # The RCON stream is a live log; the input is a labeled command field.
    console_stream = _element_chunk(body, "console-stream")
    assert 'role="log"' in console_stream
    assert 'aria-live="polite"' in console_stream
    assert 'aria-atomic="false"' in console_stream
    assert 'aria-label="RCON console output"' in console_stream
    assert 'aria-label="RCON command"' in body


async def test_server_detail_renders_bindings_card(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    body = response.text
    assert "Bindings" in body
    assert 'hx-get="/servers/atm10/bindings?edit=1"' in body


async def test_server_detail_links_back_to_home(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    assert 'href="/"' in response.text


async def test_server_detail_legacy_row_has_no_variables_card_or_banner(
    client, fake_get_server
):
    """scaffolded_at=None → legacy: no Variables card and no health banner."""
    row = _row("atm10")
    row["scaffolded_at"] = None
    fake_get_server["atm10"] = row

    response = await client.get("/servers/atm10")
    body = response.text
    assert 'id="variables"' not in body
    assert "health-banner" not in body
    # Legacy still shows the inline kv-list of variables.
    assert "no variables set" in body or "kv-list" in body


async def test_server_detail_scaffolded_row_renders_variables_card(
    client, fake_get_server, tmp_path
):
    from mcontrol import scaffolding

    server_dir = tmp_path / "newshire"
    variables = {"memory_budget_gb": 8, "port": 25575, "server_jar": "paper.jar"}
    scaffolding.scaffold("newshire", variables, tmp_path)

    row = {
        "name": "newshire", "container_name": None, "dir": str(server_dir),
        "state": "created",
        "variables": variables,
        "scaffolded_at": "2026-05-06T12:00:00+00:00",
        "created_at": "2026-05-06T11:00:00Z",
        "updated_at": "2026-05-06T12:00:00Z",
    }
    fake_get_server["newshire"] = row

    response = await client.get("/servers/newshire")
    body = response.text
    assert response.status_code == 200
    assert 'id="variables"' in body
    assert 'hx-get="/servers/newshire/variables?edit=1"' in body
    # No health banner when files are intact and variables are complete.
    assert "health-banner" not in body
    # Legacy inline `variables` row is suppressed for scaffolded rows.
    # (Card carries the canonical view; the kv-list would be redundant.)
    body_dl = body.split('class="server-detail"', 1)[1].split('</dl>', 1)[0]
    assert "kv-list" not in body_dl


async def test_server_detail_renders_health_banner_for_stuck_scaffolding(
    client, fake_get_server, tmp_path
):
    row = {
        "name": "newshire", "container_name": None, "dir": str(tmp_path / "newshire"),
        "state": "scaffolding",
        "variables": {"memory_budget_gb": 8, "port": 25575, "server_jar": "paper.jar"},
        "scaffolded_at": "2026-05-06T12:00:00+00:00",
        "created_at": "2026-05-06T11:00:00Z",
        "updated_at": "2026-05-06T12:00:00Z",
    }
    fake_get_server["newshire"] = row

    response = await client.get("/servers/newshire")
    body = response.text
    assert "health-banner" in body
    assert "stuck-scaffolding" in body
