"""Tests for routes/migrate.py — the slice 8 PR 1 card + run endpoint.

Decision 028: per-server, one-way, opt-in migration. Card is gated on
`scaffolded_at IS NULL`; POST runs migration.migrate(...), then
db.update_variables + db.mark_scaffolded, then HX-Redirect.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def base_dir(tmp_path, monkeypatch, env):
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
async def app_client(base_dir) -> AsyncIterator[AsyncClient]:
    from mcontrol.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def fake_db(monkeypatch):
    state = {
        "rows": [],
        "variables_writes": [],
        "scaffolded_marks": [],
    }
    from mcontrol.infra import db

    def fake_get_server(name):
        for row in state["rows"]:
            if row["name"] == name:
                return row
        return None

    def fake_list_servers():
        return list(state["rows"])

    def fake_update_variables(*, name, variables):
        state["variables_writes"].append((name, dict(variables)))
        for row in state["rows"]:
            if row["name"] == name:
                row["variables"] = dict(variables)

    def fake_mark_scaffolded(*, name):
        state["scaffolded_marks"].append(name)
        for row in state["rows"]:
            if row["name"] == name:
                row["state"] = "created"
                row["scaffolded_at"] = "2026-05-09T22:00:00+00:00"

    monkeypatch.setattr(db, "get_server", fake_get_server)
    monkeypatch.setattr(db, "list_servers", fake_list_servers)
    monkeypatch.setattr(db, "update_variables", fake_update_variables)
    monkeypatch.setattr(db, "mark_scaffolded", fake_mark_scaffolded)
    return state


def _legacy_layout(base_dir: Path, name: str = "atm10", *, host_port: int = 25571) -> Path:
    """Synthesise an `atm10`-shaped legacy directory under base_dir."""
    server_dir = base_dir / name
    inner = server_dir / "server"
    inner.mkdir(parents=True)
    (server_dir / "Dockerfile").write_text(
        "FROM eclipse-temurin:17-jre\n"
        "COPY entrypoint.sh /entrypoint.sh\n"
        'ENTRYPOINT ["/entrypoint.sh"]\n',
        encoding="utf-8",
    )
    (server_dir / "entrypoint.sh").write_text(
        "#!/usr/bin/env bash\nexec ./start_server.sh\n", encoding="utf-8"
    )
    (server_dir / ".dockerignore").write_text("server/world\n", encoding="utf-8")
    (server_dir / ".env").write_text("RCON_PASSWORD=rconer\n", encoding="utf-8")
    (server_dir / "docker-compose.yml").write_text(
        "services:\n"
        f"  {name}:\n"
        "    build: .\n"
        f'    container_name: {name}\n'
        "    ports:\n"
        f'      - "{host_port}:25565"\n'
        "    volumes:\n"
        "      - ./server:/data\n",
        encoding="utf-8",
    )
    (inner / "start_server.sh").write_text(
        "#!/usr/bin/env bash\n"
        "exec java -Xmx12G -XX:+UseG1GC -jar neoforge-21.1.86-server.jar nogui\n",
        encoding="utf-8",
    )
    return server_dir


def _legacy_row(base_dir: Path, *, name: str = "atm10", state: str = "exited") -> dict:
    return {
        "name": name,
        "container_name": None,
        "dir": str(base_dir / name),
        "state": state,
        "scaffolded_at": None,
        "variables": None,
    }


# ---- GET ----------------------------------------------------------


async def test_get_returns_form_prefilled_from_legacy_files(
    app_client, fake_db, base_dir
):
    _legacy_layout(base_dir)
    fake_db["rows"].append(_legacy_row(base_dir))

    response = await app_client.get("/servers/atm10/migrate")

    assert response.status_code == 200
    body = response.text
    # Heap preserved via parsed_xmx + 2 (decision 009).
    assert 'value="14"' in body
    assert 'value="25571"' in body
    assert 'value="neoforge-21.1.86-server.jar"' in body
    assert 'value="-XX:+UseG1GC"' in body
    # Card explains what gets clobbered.
    assert "Dockerfile" in body
    assert "entrypoint.sh" in body
    assert ".dockerignore" in body
    assert ".env" in body


async def test_get_button_disabled_when_state_running(
    app_client, fake_db, base_dir
):
    _legacy_layout(base_dir)
    fake_db["rows"].append(_legacy_row(base_dir, state="running"))

    response = await app_client.get("/servers/atm10/migrate")

    assert response.status_code == 200
    body = response.text
    assert "disabled" in body
    assert "Stop the server" in body


async def test_get_returns_404_when_already_scaffolded(
    app_client, fake_db, base_dir
):
    _legacy_layout(base_dir)
    row = _legacy_row(base_dir)
    row["scaffolded_at"] = "2026-05-08T12:00:00+00:00"
    fake_db["rows"].append(row)

    response = await app_client.get("/servers/atm10/migrate")

    assert response.status_code == 404


async def test_get_returns_404_for_unknown_server(app_client, fake_db):
    response = await app_client.get("/servers/unknown/migrate")
    assert response.status_code == 404


async def test_get_falls_back_to_blank_fields_when_parse_fails(
    app_client, fake_db, base_dir
):
    """No legacy files on disk → form fields stay blank, card still renders."""
    server_dir = base_dir / "atm10"
    server_dir.mkdir()
    (server_dir / "server").mkdir()
    fake_db["rows"].append(_legacy_row(base_dir))

    response = await app_client.get("/servers/atm10/migrate")

    assert response.status_code == 200
    body = response.text
    # Required inputs render; values are empty strings.
    assert 'name="memory_budget_gb"' in body
    assert 'name="server_jar"' in body
    # No "Will delete" line when nothing legacy exists.
    assert "Will delete" not in body


# ---- POST ---------------------------------------------------------


async def test_post_writes_scaffold_files_and_stamps_row(
    app_client, fake_db, base_dir
):
    _legacy_layout(base_dir)
    fake_db["rows"].append(_legacy_row(base_dir))

    response = await app_client.post(
        "/servers/atm10/migrate",
        data={
            "memory_budget_gb": "14",
            "port": "25571",
            "server_jar": "neoforge-21.1.86-server.jar",
            "jvm_extra_args": "-XX:+UseG1GC",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/servers/atm10"

    server_dir = base_dir / "atm10"
    compose = (server_dir / "docker-compose.yml").read_text(encoding="utf-8")
    start = (server_dir / "server" / "start_server.sh").read_text(encoding="utf-8")
    assert "image: eclipse-temurin:21-jre" in compose
    assert '- "25571:25565"' in compose
    assert "-Xmx12g" in start

    # Legacy files removed.
    assert not (server_dir / "Dockerfile").exists()
    assert not (server_dir / "entrypoint.sh").exists()
    assert not (server_dir / ".dockerignore").exists()
    assert not (server_dir / ".env").exists()

    # DB writes happened in order: variables first, then mark_scaffolded.
    assert fake_db["variables_writes"] == [
        (
            "atm10",
            {
                "memory_budget_gb": 14,
                "port": 25571,
                "server_jar": "neoforge-21.1.86-server.jar",
                "jvm_extra_args": "-XX:+UseG1GC",
            },
        )
    ]
    assert fake_db["scaffolded_marks"] == ["atm10"]


async def test_post_drops_jvm_extra_args_when_blank(
    app_client, fake_db, base_dir
):
    _legacy_layout(base_dir)
    fake_db["rows"].append(_legacy_row(base_dir))

    response = await app_client.post(
        "/servers/atm10/migrate",
        data={
            "memory_budget_gb": "14",
            "port": "25571",
            "server_jar": "neoforge.jar",
            "jvm_extra_args": "",
        },
    )

    assert response.status_code == 200
    written_vars = fake_db["variables_writes"][0][1]
    assert "jvm_extra_args" not in written_vars


async def test_post_refuses_when_state_running(app_client, fake_db, base_dir):
    _legacy_layout(base_dir)
    fake_db["rows"].append(_legacy_row(base_dir, state="running"))

    response = await app_client.post(
        "/servers/atm10/migrate",
        data={
            "memory_budget_gb": "14",
            "port": "25571",
            "server_jar": "neoforge.jar",
            "jvm_extra_args": "",
        },
    )

    assert response.status_code == 409
    # Files untouched — no migration ran.
    assert (base_dir / "atm10" / "Dockerfile").exists()
    assert fake_db["scaffolded_marks"] == []


async def test_post_refuses_when_already_scaffolded(
    app_client, fake_db, base_dir
):
    _legacy_layout(base_dir)
    row = _legacy_row(base_dir)
    row["scaffolded_at"] = "2026-05-08T12:00:00+00:00"
    fake_db["rows"].append(row)

    response = await app_client.post(
        "/servers/atm10/migrate",
        data={
            "memory_budget_gb": "14",
            "port": "25571",
            "server_jar": "neoforge.jar",
            "jvm_extra_args": "",
        },
    )

    assert response.status_code == 409
    assert fake_db["scaffolded_marks"] == []
    # Original Dockerfile still in place.
    assert (base_dir / "atm10" / "Dockerfile").exists()


async def test_post_validation_returns_form_with_errors(
    app_client, fake_db, base_dir
):
    _legacy_layout(base_dir)
    fake_db["rows"].append(_legacy_row(base_dir))

    response = await app_client.post(
        "/servers/atm10/migrate",
        data={
            "memory_budget_gb": "1",  # below minimum
            "port": "70",  # below minimum
            "server_jar": "  ",
            "jvm_extra_args": "",
        },
    )

    assert response.status_code == 422
    body = response.text
    assert "Minimum 2 GB" in body
    assert "Port must be between" in body
    assert "Required" in body
    # No DB writes on validation failure.
    assert fake_db["variables_writes"] == []
    assert fake_db["scaffolded_marks"] == []
    # Files still legacy.
    assert (base_dir / "atm10" / "Dockerfile").exists()


async def test_post_rejects_port_collision_with_other_server(
    app_client, fake_db, base_dir
):
    _legacy_layout(base_dir)
    fake_db["rows"].append(_legacy_row(base_dir))
    fake_db["rows"].append(
        {
            "name": "kobra",
            "container_name": None,
            "dir": str(base_dir / "kobra"),
            "state": "exited",
            "scaffolded_at": "2026-05-06T12:00:00+00:00",
            "variables": {"port": 25570, "memory_budget_gb": 12, "server_jar": "x.jar"},
        }
    )

    response = await app_client.post(
        "/servers/atm10/migrate",
        data={
            "memory_budget_gb": "14",
            "port": "25570",  # collides with kobra's port
            "server_jar": "neoforge.jar",
            "jvm_extra_args": "",
        },
    )

    assert response.status_code == 422
    # Apostrophes are HTML-escaped (&#39;) in the rendered template.
    assert "already used by &#39;kobra&#39;" in response.text
    assert fake_db["scaffolded_marks"] == []


async def test_post_returns_404_for_unknown_server(app_client, fake_db):
    response = await app_client.post(
        "/servers/unknown/migrate",
        data={
            "memory_budget_gb": "14",
            "port": "25571",
            "server_jar": "x.jar",
            "jvm_extra_args": "",
        },
    )
    assert response.status_code == 404


async def test_post_accepts_legacy_name_with_underscore(
    app_client, fake_db, base_dir
):
    """Legacy servers discovered with names that don't match the new-server
    slug shape (e.g. underscores) must still be migratable. The slug regex
    in routes/new_server.py gates *creation*, not operations on existing
    rows; migrate already trusts get_server_or_404 + path-traversal
    containment."""
    _legacy_layout(base_dir, name="kobra_kollektivet", host_port=25572)
    fake_db["rows"].append(_legacy_row(base_dir, name="kobra_kollektivet"))

    response = await app_client.post(
        "/servers/kobra_kollektivet/migrate",
        data={
            "memory_budget_gb": "14",
            "port": "25572",
            "server_jar": "fabric-server-launch.jar",
            "jvm_extra_args": "",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/servers/kobra_kollektivet"
    assert fake_db["scaffolded_marks"] == ["kobra_kollektivet"]


# ---- detail page wires the card shell -----------------------------


async def test_detail_page_lazy_loads_card_for_legacy_row(
    app_client, fake_db, base_dir
):
    _legacy_layout(base_dir)
    fake_db["rows"].append(_legacy_row(base_dir))

    response = await app_client.get("/servers/atm10")

    assert response.status_code == 200
    body = response.text
    assert 'id="migrate-card"' in body
    assert 'hx-get="/servers/atm10/migrate"' in body


async def test_detail_page_omits_card_when_already_scaffolded(
    app_client, fake_db, base_dir
):
    _legacy_layout(base_dir)
    row = _legacy_row(base_dir)
    row["scaffolded_at"] = "2026-05-06T12:00:00+00:00"
    row["variables"] = {"memory_budget_gb": 8, "port": 25565, "server_jar": "x.jar"}
    fake_db["rows"].append(row)

    response = await app_client.get("/servers/atm10")

    assert response.status_code == 200
    assert 'id="migrate-card"' not in response.text
