"""Focused tests for the read-only new-server scaffold preview."""

from mcontrol.domain import scaffolding


def _files(payload: dict) -> dict[str, str]:
    return {item["path"]: item["content"] for item in payload["files"]}


async def test_preview_blank_form_uses_examples_and_real_renderers(client):
    response = await client.post(
        "/servers/new/preview",
        data={
            "name": "",
            "memory_budget_gb": "",
            "port": "",
            "server_jar": "",
            "loader": "",
            "java_version": "",
            "jvm_extra_args": "",
            "custom_start_script": "",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["errors"] == {}
    files = _files(payload)
    assert list(files) == [
        "docker-compose.yml",
        "server/start_server.sh",
        "server/server.properties",
    ]

    variables = {
        "memory_budget_gb": 8,
        "port": 25565,
        "server_jar": "paper.jar",
        "java_version": scaffolding.DEFAULT_JAVA_VERSION,
    }
    assert files["docker-compose.yml"] == scaffolding.render_compose(
        "my-minecraft-server", variables
    )
    assert files["server/start_server.sh"] == scaffolding.render_start_script(variables)
    assert files["server/server.properties"] == scaffolding.render_server_properties(
        "GENERATED_ON_CREATE"
    )
    assert all(item["path"] != "server/eula.txt" for item in payload["files"])


async def test_preview_renders_submitted_values_without_eula_acceptance(client):
    response = await client.post(
        "/servers/new/preview",
        data={
            "name": "modded-server",
            "memory_budget_gb": "12",
            "port": "25580",
            "server_jar": "ignored.jar",
            "loader": "forge",
            "java_version": "17",
            "jvm_extra_args": "-XX:+UseG1GC",
            "custom_start_script": "scripts/run.sh",
            "accept_eula": "",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["errors"] == {}
    files = _files(payload)
    assert "container_name: modded-server" in files["docker-compose.yml"]
    assert '"25580:25565"' in files["docker-compose.yml"]
    assert "eclipse-temurin:17-jre" in files["docker-compose.yml"]
    assert "exec bash ./scripts/run.sh" in files["server/start_server.sh"]
    assert "accept_eula" not in payload["errors"]


async def test_preview_returns_field_errors_for_malformed_strings(client):
    response = await client.post(
        "/servers/new/preview",
        data={
            "name": "Bad Name",
            "memory_budget_gb": "eight",
            "port": "25565.5",
            "server_jar": "paper.jar",
            "loader": "unknown",
            "java_version": "latest",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["files"] == []
    assert payload["errors"]["name"]
    assert payload["errors"]["memory_budget_gb"] == "Enter a whole number."
    assert payload["errors"]["port"] == "Enter a whole number."
    assert payload["errors"]["java_version"] == "Enter a whole number."
    assert payload["errors"]["loader"]
    assert "accept_eula" not in payload["errors"]


async def test_preview_does_not_touch_db_disk_or_host_probes(client, monkeypatch):
    from mcontrol.domain import server_variables_form
    from mcontrol.infra import db_async
    from mcontrol.routes import new_server

    def forbidden(*args, **kwargs):
        raise AssertionError("preview attempted an external-state operation")

    monkeypatch.setattr(db_async, "list_servers", forbidden)
    monkeypatch.setattr(server_variables_form, "check_port_collision", forbidden)
    monkeypatch.setattr(server_variables_form, "check_port_bound", forbidden)
    monkeypatch.setattr(new_server.lifecycle_service, "probe_host", forbidden)
    monkeypatch.setattr(new_server.server_service, "scaffold_new_server", forbidden)

    response = await client.post(
        "/servers/new/preview",
        data={
            "name": "preview-server",
            "memory_budget_gb": "8",
            "port": "25565",
            "server_jar": "paper.jar",
            "loader": "paper",
            "java_version": "21",
        },
    )

    assert response.status_code == 200
    assert response.json()["errors"] == {}
