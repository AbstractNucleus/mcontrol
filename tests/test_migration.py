"""Tests for migration.py: pure parse/render/atomic-write primitives.

Slice 8 PR 0. No DB; no UI. Fixtures synthesise an `atm10`-shaped
legacy layout under tmp_path: Dockerfile + entrypoint.sh + .dockerignore +
.env at the server root, server/start_server.sh inside the bind mount,
and a docker-compose.yml that references the `:25565` port mapping.
"""

import os
from pathlib import Path

import pytest

from mcontrol.domain import migration, scaffolding

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
        "    volumes:\n"
        "      - ./server:/data\n"
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


def test_migrate_removes_legacy_files_after_backup(tmp_path):
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


def test_parse_compose_port_treats_null_ports_as_unavailable(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    path = server_dir / "docker-compose.yml"
    path.write_text("services:\n  atm10:\n    ports: null\n")

    assert migration.parse_compose_port(server_dir) is None


def test_migrate_uses_bound_server_dir_not_base_name(tmp_path):
    """Bindings may repoint the row away from <base>/<name>."""
    server_dir = tmp_path / "repointed"
    _legacy_layout(tmp_path, name="loading").rename(server_dir)

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
    original = (server_dir / "docker-compose.yml").read_bytes()
    with pytest.raises(migration.MigrationError):
        migration.migrate("loading", vars_, server_dir)
    assert (server_dir / "docker-compose.yml").read_bytes() == original
    assert (server_dir / "Dockerfile").exists()
    assert not list(server_dir.glob(".mcontrol-migration-backup-*"))


def test_backup_preserves_original_bytes_and_survives_retry(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    originals = {p.relative_to(server_dir): p.read_bytes()
                 for p in server_dir.rglob('*') if p.is_file()}
    first = migration.migrate('atm10', _VARS, server_dir)
    second = migration.migrate('atm10', _VARS, server_dir)
    assert first != second
    for relative, data in originals.items():
        assert (first / relative).read_bytes() == data
    assert (first / 'RESTORE.txt').is_file()


def test_backup_failure_leaves_setup_unchanged(tmp_path, monkeypatch):
    server_dir = _legacy_layout(tmp_path)
    originals = {p.relative_to(server_dir): p.read_bytes()
                 for p in server_dir.rglob('*') if p.is_file()}
    real_copy = migration.shutil.copy2
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('disk full')
        return real_copy(source, target)

    monkeypatch.setattr(migration.shutil, 'copy2', fail_second)
    with pytest.raises(migration.MigrationError, match='No setup files were changed'):
        migration.migrate('atm10', _VARS, server_dir)
    for relative, data in originals.items():
        assert (server_dir / relative).read_bytes() == data


def test_write_failure_keeps_recoverable_originals(tmp_path, monkeypatch):
    server_dir = _legacy_layout(tmp_path)
    compose = (server_dir / 'docker-compose.yml').read_bytes()
    start = (server_dir / 'server/start_server.sh').read_bytes()

    real_write = migration.atomic_write_text

    def partial_write(path, content):
        if path == server_dir / 'server/start_server.sh':
            raise OSError('disk full')
        return real_write(path, content)

    monkeypatch.setattr(migration, 'atomic_write_text', partial_write)
    with pytest.raises(migration.MigrationError, match='original setup was restored'):
        migration.migrate('atm10', _VARS, server_dir)
    backup, = server_dir.glob('.mcontrol-migration-backup-*')
    assert (backup / 'docker-compose.yml').read_bytes() == compose
    assert (backup / 'server/start_server.sh').read_bytes() == start
    assert (server_dir / 'docker-compose.yml').read_bytes() == compose
    assert (server_dir / 'server/start_server.sh').read_bytes() == start


def test_special_setup_path_rejected_before_changes(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    compose = (server_dir / 'docker-compose.yml').read_bytes()
    (server_dir / '.env').unlink()
    (server_dir / '.env').mkdir()
    with pytest.raises(migration.MigrationError):
        migration.migrate('atm10', _VARS, server_dir)
    assert (server_dir / 'docker-compose.yml').read_bytes() == compose
    assert not list(server_dir.glob('.mcontrol-migration-backup-*'))


def test_migrate_keeps_mods_jars_and_user_settings(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    data = {'mods/example.jar': b'mod', 'server.jar': b'jar',
            'server.properties': b'motd=Custom', 'config/custom.toml': b'custom=true'}
    for relative, content in data.items():
        target = server_dir / 'server' / relative
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(content)
    migration.migrate('atm10', _VARS, server_dir)
    for relative, content in data.items():
        assert (server_dir / 'server' / relative).read_bytes() == content


def _snapshot_setup(server_dir):
    return {name: (server_dir / name).read_bytes()
            for name in migration._SETUP_FILENAMES if (server_dir / name).is_file()}


@pytest.mark.parametrize('runtime', [
    {'ports': ['25571:25565', '8123:8123']},
    {'volumes': ['./server:/data', './extra:/extra']},
    {'environment': {'CUSTOM': 'required'}},
    {'env_file': '.env'},
    {'labels': {'custom': 'required'}},
    {'command': ['java', '-jar', 'special.jar']},
    {'working_dir': '/custom'},
    {'network_mode': 'host'},
])
def test_custom_runtime_rejected_without_changing_files(tmp_path, runtime):
    import yaml

    server_dir = _legacy_layout(tmp_path)
    path = server_dir / 'docker-compose.yml'
    compose = yaml.safe_load(path.read_text())
    compose['services']['atm10'].update(runtime)
    path.write_text(yaml.safe_dump(compose))
    original = _snapshot_setup(server_dir)
    with pytest.raises(migration.MigrationError):
        migration.migrate('atm10', _VARS, server_dir)
    assert _snapshot_setup(server_dir) == original
    assert not list(server_dir.glob('.mcontrol-migration-backup-*'))


def test_simple_udp_mapping_is_preserved_by_managed_rendering(tmp_path):
    import yaml

    server_dir = _legacy_layout(tmp_path)
    path = server_dir / "docker-compose.yml"
    compose = yaml.safe_load(path.read_text())
    compose["services"]["atm10"]["ports"].append("24467:24467/udp")
    path.write_text(yaml.safe_dump(compose))

    variables = migration.prepare_variables("atm10", _VARS, server_dir)

    assert "24467:24467/udp" in scaffolding.render_compose("atm10", variables)


@pytest.mark.parametrize('script', [
    'exec java -Xmx12G -jar server.jar --world custom nogui',
    'exec java -Xmx12G -jar server.jar nogui --port 25566',
    'export CUSTOM=important\nexec java -Xmx12G -jar server.jar nogui',
    'cd /another-world\nexec java -Xmx12G -jar server.jar nogui',
    'prepare-world\nexec java -Xmx12G -jar server.jar nogui',
])
def test_custom_launch_rejected_before_changes(tmp_path, script):
    server_dir = _legacy_layout(tmp_path)
    (server_dir / 'server/start_server.sh').write_text(script + '\n')
    original = _snapshot_setup(server_dir)
    with pytest.raises(migration.MigrationError):
        migration.migrate('atm10', _VARS, server_dir)
    assert _snapshot_setup(server_dir) == original
    assert not list(server_dir.glob('.mcontrol-migration-backup-*'))


def test_parser_keeps_jvm_flags_before_and_after_heap(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    (server_dir / 'server/start_server.sh').write_text(
        'exec java -Dcustom=value -Xmx12G -XX:+UseG1GC -jar server.jar nogui\n'
    )
    parsed = migration.parse_legacy_variables(server_dir)
    assert parsed['jvm_extra_args'] == '-Dcustom=value -XX:+UseG1GC'
    migration.migrate('atm10', {**_VARS, **parsed}, server_dir)
    assert '-Dcustom=value -XX:+UseG1GC' in (server_dir / 'server/start_server.sh').read_text()


@pytest.mark.parametrize('java', [17, 25])
def test_pending_backup_retains_retry_defaults_and_can_restore(tmp_path, java):
    server_dir = _legacy_layout(tmp_path)
    path = server_dir / 'Dockerfile'
    path.write_text(path.read_text().replace(':17-jre', f':{java}-jre'))
    original = _snapshot_setup(server_dir)
    backup = migration.migrate('atm10', {**_VARS, 'java_version': java}, server_dir)
    assert not path.exists()
    assert migration.latest_recoverable_backup(server_dir) == backup
    assert migration.parse_legacy_variables(server_dir)['java_version'] == java
    migration.restore_backup(server_dir, backup)
    assert _snapshot_setup(server_dir) == original
    assert migration.latest_recoverable_backup(server_dir) is None
    assert (backup / 'Dockerfile').read_bytes() == original['Dockerfile']


def test_completed_backup_is_kept_but_not_pending(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    backup = migration.migrate('atm10', _VARS, server_dir)
    migration.mark_backup_complete(server_dir, backup)
    assert migration.latest_recoverable_backup(server_dir) is None
    assert (backup / 'Dockerfile').is_file()


@pytest.mark.parametrize('relative, extra', [
    ('Dockerfile', 'RUN install-something\n'),
    ('entrypoint.sh', 'prepare-world\n'),
    ('.env', 'CUSTOM_WORLD=important\n'),
])
def test_custom_legacy_setup_is_not_discarded(tmp_path, relative, extra):
    server_dir = _legacy_layout(tmp_path)
    path = server_dir / relative
    path.write_text(path.read_text() + extra)
    original = _snapshot_setup(server_dir)
    with pytest.raises(migration.MigrationError):
        migration.migrate('atm10', _VARS, server_dir)
    assert _snapshot_setup(server_dir) == original


def test_redirected_working_directory_rejected(tmp_path, monkeypatch):
    server_dir = _legacy_layout(tmp_path)
    original = _snapshot_setup(server_dir)
    real_resolve = Path.resolve

    def redirected(path, *args, **kwargs):
        if path == server_dir / 'server':
            return tmp_path / 'outside'
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'resolve', redirected)
    with pytest.raises(migration.MigrationError):
        migration.migrate('atm10', _VARS, server_dir)
    assert _snapshot_setup(server_dir) == original
    assert not list(server_dir.glob('.mcontrol-migration-backup-*'))


@pytest.mark.skipif(not hasattr(os, 'chown') or not hasattr(os, 'geteuid') or
                    (hasattr(os, 'geteuid') and os.geteuid() != 0),
                    reason='requires Linux root to verify different file owner')
def test_backup_and_restore_preserve_private_file_ownership(tmp_path):
    import stat

    server_dir = _legacy_layout(tmp_path)
    env_path = server_dir / '.env'
    os.chown(env_path, 1234, 1235)
    env_path.chmod(0o600)
    original = env_path.read_bytes()
    backup = migration.migrate('atm10', _VARS, server_dir)
    migration.restore_backup(server_dir, backup)
    restored = env_path.stat()
    assert (restored.st_uid, restored.st_gid) == (1234, 1235)
    assert stat.S_IMODE(restored.st_mode) == 0o600
    assert env_path.read_bytes() == original


def test_pending_intent_records_requested_values_and_completed_files(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    variables = {**_VARS, 'java_version': 25}
    backup = migration.migrate('atm10', variables, server_dir)
    assert migration.read_migration_intent(server_dir, backup) == {
        'name': 'atm10', 'variables': variables, 'files_ready': True,
    }
    migration.mark_backup_complete(server_dir, backup)
    assert migration.read_migration_intent(server_dir, backup)['variables'] == variables


def test_crash_during_file_write_leaves_prepared_intent_and_recoverable_files(
    tmp_path, monkeypatch
):
    server_dir = _legacy_layout(tmp_path)
    original = _snapshot_setup(server_dir)
    real_write = migration.atomic_write_text

    def simulated_crash(path, content):
        if path == server_dir / 'server/start_server.sh':
            raise KeyboardInterrupt('process terminated')
        return real_write(path, content)

    monkeypatch.setattr(migration, 'atomic_write_text', simulated_crash)
    with pytest.raises(KeyboardInterrupt):
        migration.migrate('atm10', _VARS, server_dir)
    backup = migration.latest_recoverable_backup(server_dir)
    assert backup is not None
    assert migration.read_migration_intent(server_dir, backup)['files_ready'] is False
    migration.restore_backup(server_dir, backup)
    assert _snapshot_setup(server_dir) == original


def test_compose_generated_container_name_cannot_bypass_stopped_check(tmp_path):
    server_dir = _legacy_layout(tmp_path)
    path = server_dir / 'docker-compose.yml'
    path.write_text(path.read_text().replace('    container_name: atm10\n', ''))
    original = _snapshot_setup(server_dir)
    with pytest.raises(migration.MigrationError, match='explicitly set container_name'):
        migration.migrate('atm10', _VARS, server_dir)
    assert _snapshot_setup(server_dir) == original
    assert not list(server_dir.glob('.mcontrol-migration-backup-*'))


def test_supported_runtime_rejects_out_of_range_udp_before_backup(tmp_path):
    import yaml

    server_dir = _legacy_layout(tmp_path, name="loading")
    path = server_dir / "docker-compose.yml"
    compose = yaml.safe_load(path.read_text())
    service = compose["services"].pop("loading")
    compose["services"]["minecraft"] = service
    service.update(
        ports=["25571:25565", "70000:24467/udp"],
        labels=["com.noelkleen.service=minecraft"],
        env_file=[".env"],
        stdin_open=True,
        tty=True,
    )
    path.write_text(yaml.safe_dump(compose))

    with pytest.raises(migration.MigrationError, match="out-of-range UDP"):
        migration.migrate("loading", _VARS, server_dir)

    assert not list(server_dir.glob(".mcontrol-migration-backup-*"))
