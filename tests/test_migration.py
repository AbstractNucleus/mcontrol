"""Tests for migration.py: pure parse/render/atomic-write primitives.

Slice 8 PR 0. No DB; no UI. Fixtures synthesise an `atm10`-shaped
legacy layout under tmp_path: Dockerfile + entrypoint.sh + .dockerignore +
.env at the server root, server/start_server.sh inside the bind mount,
and a docker-compose.yml that references the `:25565` port mapping.
"""

import os
from pathlib import Path

import pytest

from mcontrol.domain import migration

# ---- fixture ------------------------------------------------------


def _legacy_layout(
    base: Path,
    name: str = "atm10",
    *,
    xmx: str = "12G",
    jar: str = "neoforge-21.1.86-server.jar",
    extra: str = "-XX:+UseG1GC",
    host_port: int = 25571,
) -> Path:
    server_dir = base / name
    inner = server_dir / "server"
    inner.mkdir(parents=True)

    dockerfile = (
        "FROM eclipse-temurin:17-jre\n"
        "COPY entrypoint.sh /entrypoint.sh\n"
        "RUN chmod +x /entrypoint.sh\n"
        'ENTRYPOINT ["/entrypoint.sh"]\n'
    )
    entrypoint = "#!/usr/bin/env bash\nset -e\ncd /data && exec ./start_server.sh\n"
    dockerignore = "server/world\nserver/logs\n"
    env = "RCON_PASSWORD=rconer\n"
    compose = (
        "services:\n"
        f"  {name}:\n"
        "    build: .\n"
        f"    container_name: {name}\n"
        "    restart: unless-stopped\n"
        "    ports:\n"
        f'      - "{host_port}:25565"\n'
        "      - \"25575:25575\"\n"
        "    volumes:\n"
        "      - ./server:/data\n"
        "    env_file: .env\n"
    )
    start = (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        f"exec java -Xmx{xmx} {extra} -jar {jar} nogui\n"
    )

    (server_dir / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    (server_dir / "entrypoint.sh").write_text(entrypoint, encoding="utf-8")
    (server_dir / ".dockerignore").write_text(dockerignore, encoding="utf-8")
    (server_dir / ".env").write_text(env, encoding="utf-8")
    (server_dir / "docker-compose.yml").write_text(compose, encoding="utf-8")
    (inner / "start_server.sh").write_text(start, encoding="utf-8")

    return server_dir


# ---- legacy_files -------------------------------------------------


def test_legacy_files_returns_all_four_when_present(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    found = migration.legacy_files(server_dir)
    names = [p.name for p in found]
    assert names == ["Dockerfile", "entrypoint.sh", ".dockerignore", ".env"]


def test_legacy_files_skips_absent_files(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    (server_dir / ".env").unlink()
    (server_dir / ".dockerignore").unlink()
    names = [p.name for p in migration.legacy_files(server_dir)]
    assert names == ["Dockerfile", "entrypoint.sh"]


def test_legacy_files_empty_when_dir_already_scaffolded(tmp_path):
    server_dir = tmp_path / "fresh"
    (server_dir / "server").mkdir(parents=True)
    assert migration.legacy_files(server_dir) == []


# ---- parse_legacy_variables ---------------------------------------


def test_parse_legacy_variables_extracts_full_atm10_shape(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    parsed = migration.parse_legacy_variables(server_dir)

    # Budget = parsed -Xmx + 2 GB headroom.
    assert parsed["memory_budget_gb"] == 14
    assert parsed["server_jar"] == "neoforge-21.1.86-server.jar"
    assert parsed["jvm_extra_args"] == "-XX:+UseG1GC"
    assert parsed["port"] == 25571
    assert parsed["java_version"] == 17


def test_parse_legacy_variables_omits_jvm_extra_args_when_none_present(tmp_path):
    server_dir = _legacy_layout(tmp_path, extra="")
    parsed = migration.parse_legacy_variables(server_dir)
    assert "jvm_extra_args" not in parsed
    assert parsed["memory_budget_gb"] == 14
    assert parsed["server_jar"] == "neoforge-21.1.86-server.jar"


def test_parse_legacy_variables_handles_lowercase_xmx_suffix(tmp_path):
    server_dir = _legacy_layout(tmp_path, xmx="8g")
    parsed = migration.parse_legacy_variables(server_dir)
    assert parsed["memory_budget_gb"] == 10


def test_parse_legacy_variables_picks_first_25565_mapping(tmp_path):
    server_dir = _legacy_layout(tmp_path, host_port=30000)
    parsed = migration.parse_legacy_variables(server_dir)
    assert parsed["port"] == 30000


def test_parse_legacy_variables_returns_empty_when_no_files(tmp_path):
    server_dir = tmp_path / "empty"
    server_dir.mkdir()
    parsed = migration.parse_legacy_variables(server_dir)
    assert parsed == {}


def test_parse_legacy_variables_yields_partial_on_parse_failure(tmp_path):
    """Garbled start_server.sh + valid compose = port-only result."""
    server_dir = _legacy_layout(tmp_path)
    (server_dir / "server" / "start_server.sh").write_text(
        "#!/usr/bin/env bash\necho garbled\n", encoding="utf-8"
    )
    parsed = migration.parse_legacy_variables(server_dir)
    assert parsed["port"] == 25571
    assert parsed["java_version"] == 17
    assert "memory_budget_gb" not in parsed
    assert "server_jar" not in parsed


# ---- migrate ------------------------------------------------------


_VARS = {
    "memory_budget_gb": 14,
    "port": 25571,
    "server_jar": "neoforge-21.1.86-server.jar",
    "jvm_extra_args": "-XX:+UseG1GC",
}


def test_migrate_writes_scaffold_files_with_expected_contents(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    migration.migrate("atm10", _VARS, server_dir)

    compose = (server_dir / "docker-compose.yml").read_text(encoding="utf-8")
    start = (server_dir / "server" / "start_server.sh").read_text(encoding="utf-8")

    # Compose converges on slice-6 shape.
    assert "image: eclipse-temurin:21-jre" in compose
    assert "container_name: atm10" in compose
    assert "mem_limit: 14g" in compose
    assert '- "25571:25565"' in compose
    assert "build:" not in compose
    # Heap preserved: 14 GB budget − 2 GB headroom = -Xmx12g.
    assert "-Xmx12g" in start
    assert '-jar "neoforge-21.1.86-server.jar"' in start
    assert "-XX:+UseG1GC" in start


def test_migrate_unlinks_all_four_legacy_files(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    migration.migrate("atm10", _VARS, server_dir)

    assert not (server_dir / "Dockerfile").exists()
    assert not (server_dir / "entrypoint.sh").exists()
    assert not (server_dir / ".dockerignore").exists()
    assert not (server_dir / ".env").exists()


def test_migrate_leaves_world_data_untouched(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    world = server_dir / "server" / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"level-bytes")
    (server_dir / "server" / "ops.json").write_text("[]\n", encoding="utf-8")

    migration.migrate("atm10", _VARS, server_dir)

    assert (world / "level.dat").read_bytes() == b"level-bytes"
    assert (server_dir / "server" / "ops.json").read_text(encoding="utf-8") == "[]\n"


def test_migrate_is_idempotent_on_re_run(tmp_path):
    """Second call after success: no files left to unlink, files re-rendered."""
    server_dir = _legacy_layout(tmp_path)
    migration.migrate("atm10", _VARS, server_dir)
    migration.migrate("atm10", _VARS, server_dir)

    compose = server_dir / "docker-compose.yml"
    start = server_dir / "server" / "start_server.sh"
    assert compose.exists() and start.exists()
    assert "image: eclipse-temurin:21-jre" in compose.read_text(encoding="utf-8")


def test_migrate_tolerates_missing_legacy_files(tmp_path):
    """Partial-fail reruns: a previous call removed some legacy files;
    a re-click should still succeed without raising."""
    server_dir = _legacy_layout(tmp_path)
    (server_dir / "Dockerfile").unlink()
    (server_dir / ".env").unlink()

    migration.migrate("atm10", _VARS, server_dir)

    assert not (server_dir / "entrypoint.sh").exists()
    assert not (server_dir / ".dockerignore").exists()


def test_migrate_raises_before_any_io_when_variables_incomplete(tmp_path):
    """Template render is the first step; missing required vars must
    raise without touching disk so the operator can fix the form."""
    server_dir = _legacy_layout(tmp_path)
    incomplete = {"memory_budget_gb": 14, "port": 25571}  # no server_jar

    with pytest.raises(KeyError):
        migration.migrate("atm10", incomplete, server_dir)

    # Legacy files still present; render failed before any unlink.
    assert (server_dir / "Dockerfile").exists()
    assert (server_dir / "entrypoint.sh").exists()
    # Original compose untouched.
    assert "build: ." in (server_dir / "docker-compose.yml").read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="chmod exec bit is a no-op on Windows")
def test_migrate_marks_start_script_executable(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    migration.migrate("atm10", _VARS, server_dir)
    start = server_dir / "server" / "start_server.sh"
    assert start.stat().st_mode & 0o100


def test_parse_legacy_variables_falls_back_to_entrypoint_sh(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    (server_dir / "server" / "start_server.sh").unlink()
    (server_dir / "entrypoint.sh").write_text(
        "#!/usr/bin/env bash\n"
        "exec java -Xmx10G -jar server.jar nogui\n",
        encoding="utf-8",
    )

    parsed = migration.parse_legacy_variables(server_dir)
    assert parsed["memory_budget_gb"] == 12
    assert parsed["server_jar"] == "server.jar"


def test_parse_legacy_variables_falls_back_to_mem_limit(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    (server_dir / "server" / "start_server.sh").write_text(
        "#!/usr/bin/env bash\necho garbled\n", encoding="utf-8"
    )
    (server_dir / "entrypoint.sh").write_text(
        "#!/usr/bin/env bash\nexec ./start_server.sh\n", encoding="utf-8"
    )
    compose = (server_dir / "docker-compose.yml").read_text(encoding="utf-8")
    (server_dir / "docker-compose.yml").write_text(
        compose.replace("restart: unless-stopped\n", "mem_limit: 12g\n"),
        encoding="utf-8",
    )

    parsed = migration.parse_legacy_variables(server_dir)
    assert parsed["memory_budget_gb"] == 12


def test_parse_compose_port_reads_first_25565_mapping(tmp_path):
    server_dir = _legacy_layout(tmp_path, host_port=25567)
    assert migration.parse_compose_port(server_dir) == 25567


def test_migrate_uses_bound_server_dir_not_base_name(tmp_path):
    """Bindings may repoint the row away from <base>/<name>."""
    server_dir = tmp_path / "repointed"
    _legacy_layout(tmp_path, name="repointed")

    migration.migrate("loading", _VARS, server_dir)

    assert (server_dir / "docker-compose.yml").exists()
    assert "image: eclipse-temurin:21-jre" in (
        server_dir / "docker-compose.yml"
    ).read_text(encoding="utf-8")
    assert not (tmp_path / "loading").exists()


def test_migrate_loading_legacy_compose_shape(tmp_path):
    """Real production shape: build, mem_limit, extra UDP port, env_file, labels."""
    server_dir = tmp_path / "loading"
    inner = server_dir / "server"
    inner.mkdir(parents=True)
    (server_dir / "Dockerfile").write_text(
        "FROM eclipse-temurin:21-jre\n", encoding="utf-8"
    )
    (server_dir / "entrypoint.sh").write_text(
        "#!/usr/bin/env bash\n"
        "exec java -Xmx10G -jar server.jar nogui\n",
        encoding="utf-8",
    )
    (server_dir / ".dockerignore").write_text("server/world\n", encoding="utf-8")
    (server_dir / ".env").write_text("RCON_PASSWORD=secret\n", encoding="utf-8")
    (server_dir / "docker-compose.yml").write_text(
        "services:\n"
        "  loading:\n"
        "    build: .\n"
        "    container_name: loading\n"
        "    mem_limit: 12g\n"
        "    ports:\n"
        '      - "25567:25565"\n'
        '      - "24467:24467/udp"\n'
        "    env_file: .env\n"
        "    volumes:\n"
        "      - ./server:/data\n"
        "    labels:\n"
        "      com.example.keep: leftover\n",
        encoding="utf-8",
    )

    parsed = migration.parse_legacy_variables(server_dir)
    assert parsed["memory_budget_gb"] == 12
    assert parsed["port"] == 25567
    assert parsed["server_jar"] == "server.jar"
    assert parsed["java_version"] == 21

    vars_ = {
        "memory_budget_gb": 12,
        "port": 25567,
        "server_jar": "server.jar",
        "java_version": 21,
    }
    migration.migrate("loading", vars_, server_dir)

    compose = (server_dir / "docker-compose.yml").read_text(encoding="utf-8")
    assert "image: eclipse-temurin:21-jre" in compose
    assert "stop_grace_period: 90s" in compose
    assert "mem_limit: 12g" in compose
    assert "build:" not in compose
    assert not (server_dir / "Dockerfile").exists()
    assert not (server_dir / "entrypoint.sh").exists()
    assert (inner / "server.properties").exists() is False
