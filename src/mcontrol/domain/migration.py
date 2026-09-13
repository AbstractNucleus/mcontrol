"""Safe conversion of a known legacy server layout to managed scaffold files."""

import json
import os
import re
import shlex
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any

import yaml

from mcontrol.domain import scaffolding
from mcontrol.infra.file_writer import atomic_write_text

_LEGACY_FILENAMES = ("Dockerfile", "entrypoint.sh", ".dockerignore", ".env")
_SETUP_FILENAMES = ("docker-compose.yml", "server/start_server.sh", *_LEGACY_FILENAMES)
_BACKUP_PREFIX = ".mcontrol-migration-backup-"
_MANIFEST = "manifest.json"
_XMX_RE = re.compile(r"-Xmx(\d+)[gG]\b")
_PORT_RE = re.compile(r'"(\d+):25565"')
_MEM_LIMIT_RE = re.compile(r"mem_limit:\s*(\d+)[gG]\b")
_JAVA_IMAGE_RE = re.compile(r"eclipse-temurin:(\d+)")
_JAVA_LINE_RE = re.compile(r"^\s*exec\s+java\s+(.+?)\s*$")
_SAFE_JAR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+ -]*\.jar\Z", re.IGNORECASE)
_UNSAFE_JVM_CHARS_RE = re.compile(r"[\r\n;&|<>`$\\#*?\[\]{}~]")
_SAFE_DOCKERFILE_LINES = (
    re.compile(r"FROM\s+eclipse-temurin:\d+-jre\Z", re.IGNORECASE),
    re.compile(r"COPY\s+entrypoint\.sh\s+/entrypoint\.sh\Z", re.IGNORECASE),
    re.compile(r"RUN\s+chmod\s+\+x\s+/entrypoint\.sh\Z", re.IGNORECASE),
    re.compile(
        r"RUN\s+sed\s+-i\s+'s/\\r\$//'\s+/entrypoint\.sh\s+&&\s+chmod\s+\+x\s+"
        r"/entrypoint\.sh\Z",
        re.IGNORECASE,
    ),
    re.compile(r"WORKDIR\s+/data\Z", re.IGNORECASE),
    re.compile(r'ENTRYPOINT\s+\[\s*"/entrypoint\.sh"\s*\]\Z', re.IGNORECASE),
)
_PUBLIC_VARIABLE_KEYS = {
    "memory_budget_gb",
    "port",
    "server_jar",
    "java_version",
    "jvm_extra_args",
}
_RCON_PREAMBLE = [
    "set -euo pipefail",
    'cd "$(dirname "$0")"',
    'if [[ -n "${RCON_PASSWORD:-}" && -f server.properties ]]; then',
    "if grep -q '^rcon.password=' server.properties; then",
    'sed -i "s/^rcon.password=.*/rcon.password=${RCON_PASSWORD}/" server.properties',
    "else",
    "printf '\\nrcon.password=%s\\n' \"${RCON_PASSWORD}\" >> server.properties",
    "fi",
    "fi",
]


class MigrationError(OSError):
    """Unsafe migration or recovery failure suitable for an operator message."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_compose_port(server_dir: Path) -> int | None:
    """Return the first simple host mapping targeting Minecraft TCP 25565."""
    try:
        compose = yaml.safe_load(_read_text(server_dir / "docker-compose.yml"))
        services = compose.get("services", {}) if isinstance(compose, dict) else {}
        if not isinstance(services, dict):
            return None
        for service in services.values():
            if not isinstance(service, dict):
                continue
            ports = service.get("ports", [])
            if not isinstance(ports, list):
                continue
            for port in ports:
                if not isinstance(port, str):
                    continue
                match = re.fullmatch(r"(\d+):25565(?:/tcp)?", port, re.IGNORECASE)
                if match:
                    return int(match.group(1))
    except (OSError, yaml.YAMLError):
        pass
    match = _PORT_RE.search(_read_text(server_dir / "docker-compose.yml"))
    return int(match.group(1)) if match else None


def legacy_files(server_dir: Path) -> list[Path]:
    """Return existing obsolete root files in stable display order."""
    return [server_dir / name for name in _LEGACY_FILENAMES if (server_dir / name).exists()]


def _script_commands(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _parse_launch(text: str) -> dict[str, Any] | None:
    commands = _script_commands(text)
    java_lines = [line for line in commands if _JAVA_LINE_RE.fullmatch(line)]
    if len(java_lines) != 1 or not commands or commands[-1] != java_lines[0]:
        return None
    other_lines = commands[:-1]
    safe_preamble = other_lines in ([], ["set -e"], ["set -euo pipefail"], _RCON_PREAMBLE)
    if not safe_preamble:
        return None
    match = _JAVA_LINE_RE.fullmatch(java_lines[0])
    assert match is not None
    try:
        tokens = shlex.split(match.group(1), posix=True)
    except ValueError:
        return None
    jar_indexes = [index for index, token in enumerate(tokens) if token == "-jar"]
    xmx_indexes = [index for index, token in enumerate(tokens) if _XMX_RE.fullmatch(token)]
    if len(jar_indexes) != 1 or len(xmx_indexes) != 1:
        return None
    jar_index, xmx_index = jar_indexes[0], xmx_indexes[0]
    if jar_index + 1 >= len(tokens) or xmx_index > jar_index:
        return None
    # The managed script only has `nogui` after the jar. World names and
    # application flags cannot be folded into JVM arguments safely.
    if tokens[jar_index + 2 :] not in ([], ["nogui"]):
        return None
    extra_tokens = tokens[:jar_index]
    extra_tokens.pop(xmx_index)
    xmx = _XMX_RE.fullmatch(tokens[xmx_index])
    assert xmx is not None
    parsed: dict[str, Any] = {
        "memory_budget_gb": int(xmx.group(1)) + scaffolding.HEADROOM_GB,
        "server_jar": tokens[jar_index + 1],
    }
    if extra_tokens:
        parsed["jvm_extra_args"] = shlex.join(extra_tokens)
    return parsed


def _legacy_launch(server_dir: Path) -> tuple[Path | None, dict[str, Any] | None]:
    for path in (server_dir / "server" / "start_server.sh", server_dir / "entrypoint.sh"):
        text = _read_text(path)
        if not text:
            continue
        parsed = _parse_launch(text)
        if parsed is not None:
            return path, parsed
        if "java" in text:
            return path, None
    return None, None


def parse_legacy_variables(server_dir: Path) -> dict[str, Any]:
    """Best-effort migration defaults, using a pending backup after a crash."""
    source_dir = latest_recoverable_backup(server_dir) or server_dir
    out: dict[str, Any] = {}
    _, launch = _legacy_launch(source_dir)
    if launch:
        out.update(launch)
    compose_text = _read_text(source_dir / "docker-compose.yml")
    port = parse_compose_port(source_dir)
    if port is not None:
        out["port"] = port
    if "memory_budget_gb" not in out:
        mem_match = _MEM_LIMIT_RE.search(compose_text)
        if mem_match:
            out["memory_budget_gb"] = int(mem_match.group(1))
    java_match = _JAVA_IMAGE_RE.search(_read_text(source_dir / "Dockerfile"))
    if java_match and int(java_match.group(1)) in scaffolding.JAVA_VERSIONS:
        out["java_version"] = int(java_match.group(1))
    return out


def _is_redirected(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _validate_paths(server_dir: Path) -> None:
    try:
        server_info = server_dir.lstat()
        inner_info = (server_dir / "server").lstat()
    except OSError as exc:
        raise MigrationError("The bound directory and its server/ directory must exist.") from exc
    if not stat.S_ISDIR(server_info.st_mode):
        raise MigrationError(f"Server directory is not a directory: {server_dir}")
    inner = server_dir / "server"
    if (
        not stat.S_ISDIR(inner_info.st_mode)
        or _is_redirected(inner)
        or inner.resolve() != server_dir.resolve() / "server"
    ):
        raise MigrationError(
            "server/ is a symlink, junction, or redirected path. Move the data into the bound "
            "server directory before migrating."
        )
    for filename in _SETUP_FILENAMES:
        path = server_dir / filename
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise MigrationError(f"Cannot inspect {filename}; no files were changed.") from exc
        if not stat.S_ISREG(mode) or _is_redirected(path):
            raise MigrationError(
                f"{filename} is not a regular local file. Replace that path before migrating."
            )


def _validate_requested_launch(variables: dict[str, Any]) -> None:
    jar = variables["server_jar"]
    if not isinstance(jar, str) or not _SAFE_JAR_RE.fullmatch(jar) or Path(jar).name != jar:
        raise MigrationError(
            "Server jar must be a direct .jar filename using letters, numbers, spaces, '.', '_', "
            "'+' or '-'."
        )
    extra = variables.get("jvm_extra_args", "")
    if not isinstance(extra, str) or _UNSAFE_JVM_CHARS_RE.search(extra):
        raise MigrationError(
            "JVM arguments contain shell expansion or control characters. Use literal JVM flags."
        )
    try:
        shlex.split(extra, posix=True)
    except ValueError as exc:
        raise MigrationError("JVM arguments contain unmatched quotes.") from exc


def _load_compose_service(
    name: str, server_dir: Path
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    try:
        text = (server_dir / "docker-compose.yml").read_text(encoding="utf-8")
    except OSError as exc:
        raise MigrationError("docker-compose.yml cannot be read; no files were changed.") from exc
    if "${" in text:
        raise MigrationError(
            "docker-compose.yml uses ${...} interpolation. Replace it with literal values before "
            "migrating because the legacy .env will be removed."
        )
    try:
        compose = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise MigrationError(
            "docker-compose.yml is not valid YAML; fix it before migrating."
        ) from exc
    if not isinstance(compose, dict) or not isinstance(compose.get("services"), dict):
        raise MigrationError("docker-compose.yml must contain a services mapping.")
    top_extra = set(compose) - {"version", "services"}
    if top_extra:
        raise MigrationError(
            "Compose has unsupported top-level settings: " + ", ".join(sorted(top_extra))
        )
    services = compose["services"]
    if len(services) != 1:
        raise MigrationError("Compose must contain exactly one service.")
    service_name = next(iter(services))
    if not isinstance(service_name, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*", service_name
    ):
        raise MigrationError("Compose service name is not safe to manage.")
    service = services[service_name]
    if not isinstance(service, dict):
        raise MigrationError("The managed Compose service must be a mapping.")
    return compose, service_name, service


def _validate_compose(
    name: str, variables: dict[str, Any], server_dir: Path
) -> dict[str, Any] | None:
    compose, service_name, service = _load_compose_service(name, server_dir)
    expected = yaml.safe_load(scaffolding.render_compose(name, variables))
    if compose == expected:
        return None
    allowed = {
        "build",
        "container_name",
        "restart",
        "mem_limit",
        "ports",
        "volumes",
        "labels",
        "env_file",
        "stdin_open",
        "tty",
    }
    unsupported = set(service) - allowed
    if unsupported:
        raise MigrationError(
            "Compose runtime settings cannot be preserved by managed regeneration: "
            + ", ".join(sorted(unsupported))
            + ". Move them elsewhere or migrate this server manually."
        )
    build = service.get("build")
    if build not in (".", {"context": "."}):
        raise MigrationError("Compose build must use this server directory ('build: .').")
    if service.get("container_name") != name:
        raise MigrationError(
            "Compose must explicitly set container_name to the server name before migrating, "
            "so Docker can confirm the correct container is stopped."
        )
    if service.get("restart", "unless-stopped") != "unless-stopped":
        raise MigrationError("Compose restart must be 'unless-stopped' before migrating.")
    ports = service.get("ports")
    if not isinstance(ports, list):
        raise MigrationError("Compose ports must be a list.")
    primary = [
        port
        for port in ports
        if isinstance(port, str)
        and re.fullmatch(r"\d+:25565(?:/tcp)?", port, re.IGNORECASE)
    ]
    extra_udp = [
        port
        for port in ports
        if isinstance(port, str) and re.fullmatch(r"\d+:\d+/udp", port, re.IGNORECASE)
    ]
    if len(primary) != 1 or len(primary) + len(extra_udp) != len(ports):
        raise MigrationError(
            "Compose may expose one Minecraft TCP port and simple numeric UDP mappings only."
        )
    for port in extra_udp:
        published, target = port.rsplit("/", 1)[0].split(":")
        if not all(1 <= int(number) <= 65535 for number in (published, target)):
            raise MigrationError("Compose contains an out-of-range UDP port.")
    volumes = service.get("volumes")
    if volumes not in (["./server:/data"], ["./server:/data:rw"]):
        raise MigrationError(
            "Compose must mount only './server:/data'. Custom or additional mounts cannot be "
            "preserved by Regenerate; remove them or migrate manually."
        )
    if service.get("stdin_open", True) is not True or service.get("tty", True) is not True:
        raise MigrationError("Compose stdin_open and tty must be true when present.")
    expected_label = f"com.noelkleen.service={service_name}"
    labels = service.get("labels", [])
    if labels not in ([], [expected_label], {"com.noelkleen.service": service_name}):
        raise MigrationError("Compose contains unsupported labels.")
    env_file = service.get("env_file")
    if env_file not in (None, ".env", [".env"], ["./.env"]):
        raise MigrationError("Compose env_file must be only .env.")
    if env_file is not None:
        env_path = server_dir / ".env"
        if not env_path.is_file():
            raise MigrationError("Compose uses .env, but the file is missing.")
    custom = (
        service_name != name
        or bool(extra_udp)
        or bool(labels)
        or env_file is not None
    )
    if not custom:
        return None
    return {
        "compose_service": service_name,
        "extra_udp_ports": [port.lower() for port in extra_udp],
        "labels": [expected_label] if labels else [],
        "env_file": ".env" if env_file is not None else None,
        "rcon_password_env": env_file is not None,
    }


def public_variables(variables: dict[str, Any]) -> dict[str, Any]:
    """Return only values controlled by the migration/Variables form."""
    return {key: value for key, value in variables.items() if key in _PUBLIC_VARIABLE_KEYS}


def prepare_variables(
    name: str, variables: dict[str, Any], server_dir: Path
) -> dict[str, Any]:
    """Attach a recognized, bounded runtime profile for durable rendering."""
    _validate_paths(server_dir)
    public = public_variables(variables)
    runtime = _validate_compose(name, public, server_dir)
    commands = _script_commands(_read_text(server_dir / "server" / "start_server.sh"))
    java_lines = [line for line in commands if _JAVA_LINE_RE.fullmatch(line)]
    has_rcon_prelude = (
        len(java_lines) == 1
        and bool(commands)
        and commands[-1] == java_lines[0]
        and commands[:-1] == _RCON_PREAMBLE
    )
    expects_rcon_prelude = bool(runtime and runtime.get("rcon_password_env"))
    if has_rcon_prelude != expects_rcon_prelude:
        raise MigrationError(
            "The recognized RCON startup prelude and Compose env_file .env must be used together."
        )
    if runtime is None:
        return public
    return {**public, scaffolding.MANAGED_RUNTIME_KEY: runtime}


def _validate_legacy_scripts(server_dir: Path) -> None:
    dockerfile = server_dir / "Dockerfile"
    if dockerfile.exists():
        lines = _script_commands(_read_text(dockerfile))
        supported = all(
            any(pattern.fullmatch(line) for pattern in _SAFE_DOCKERFILE_LINES)
            for line in lines
        )
        directives = [line.split(maxsplit=1)[0].upper() for line in lines]
        image_match = next(
            (_JAVA_IMAGE_RE.search(line) for line in lines if line.upper().startswith("FROM ")),
            None,
        )
        if (
            not lines
            or not supported
            or directives.count("FROM") != 1
            or len(directives) != len(set(directives))
            or image_match is None
            or int(image_match.group(1)) not in scaffolding.JAVA_VERSIONS
        ):
            raise MigrationError(
                "Dockerfile contains commands beyond the supported Java image, entrypoint copy, "
                "chmod, and ENTRYPOINT. Move that behavior elsewhere or migrate manually."
            )
    entrypoint = server_dir / "entrypoint.sh"
    if entrypoint.exists():
        commands = _script_commands(_read_text(entrypoint))
        remaining = [line for line in commands if line not in {"set -e", "set -euo pipefail"}]
        loading_entrypoint = [
            "cd /data",
            'if [ -f "start_server.sh" ]; then',
            "chmod +x start_server.sh",
            'exec ./start_server.sh "$@"',
            "fi",
            (
                'echo "No start script found. Place start_server.sh in the server data '
                'directory, then rebuild."'
            ),
            "exit 1",
        ]
        if remaining not in (
            ["exec ./start_server.sh"],
            ["cd /data && exec ./start_server.sh"],
            loading_entrypoint,
        ):
            raise MigrationError(
                "entrypoint.sh contains setup behavior that the managed scaffold cannot preserve. "
                "Move it into a supported start script or migrate manually."
            )
    env_path = server_dir / ".env"
    if env_path.exists():
        keys = []
        for number, line in enumerate(_read_text(env_path).splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, _ = line.partition("=")
            if not separator:
                raise MigrationError(f".env line {number} is invalid; fix it before migrating.")
            keys.append(key.strip())
        unexpected = sorted(set(keys) - {"RCON_PASSWORD"})
        if unexpected:
            raise MigrationError(
                ".env contains runtime settings that cannot be preserved: "
                + ", ".join(unexpected)
                + ". Move them elsewhere or migrate manually."
            )


def _write_manifest(
    backup: Path, files: list[str], status: str, intent: dict[str, Any] | None = None
) -> None:
    if intent is None:
        intent = json.loads((backup / _MANIFEST).read_text(encoding="utf-8"))["intent"]
    atomic_write_text(
        backup / _MANIFEST,
        json.dumps(
            {"version": 1, "files": files, "status": status, "intent": intent}, indent=2
        ) + "\n",
    )


def _backup_setup(server_dir: Path, name: str, variables: dict[str, Any]) -> Path:
    files = [filename for filename in _SETUP_FILENAMES if (server_dir / filename).exists()]
    try:
        backup = Path(tempfile.mkdtemp(prefix=_BACKUP_PREFIX, dir=server_dir))
        for filename in files:
            source, target = server_dir / filename, backup / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if hasattr(os, "chown"):
                owner = source.stat()
                os.chown(target, owner.st_uid, owner.st_gid)
            if target.read_bytes() != source.read_bytes():
                raise OSError(f"Backup verification failed for {filename}")
        _write_manifest(backup, files, "pending", {
            "name": name, "variables": variables, "files_ready": False,
        })
        (backup / "RESTORE.txt").write_text(
            "mcontrol migration setup backup. Keep the server stopped while restoring.\n"
            "Retry an unfinished migration in the panel using its saved values.\n"
            "If database confirmation was uncertain, resolve that attempt before manual recovery.\n"
            "For manual recovery, copy these files to the same relative paths in the parent\n"
            "server directory, preserving ownership and permissions. Originally absent files: "
            + (", ".join(name for name in _SETUP_FILENAMES if name not in files) or "none")
            + ".\nRestoring files alone does not reset the panel's migration status "
            "or variables.\n",
            encoding="utf-8",
        )
        return backup
    except OSError as exc:
        raise MigrationError(
            "Could not preserve the original setup. No setup files were changed. Check directory "
            "access and free disk space before retrying."
        ) from exc


def _read_manifest(server_dir: Path, backup: Path) -> dict[str, Any]:
    try:
        resolved_backup = backup.resolve(strict=True)
    except OSError as exc:
        raise MigrationError("Migration backup no longer exists.") from exc
    if (
        backup.parent.resolve() != server_dir.resolve()
        or resolved_backup.parent != server_dir.resolve()
        or not backup.name.startswith(_BACKUP_PREFIX)
        or _is_redirected(backup)
    ):
        raise MigrationError("Refusing to use a backup outside the bound server directory.")
    manifest_path = backup / _MANIFEST
    if _is_redirected(manifest_path):
        raise MigrationError("Migration backup manifest is redirected.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError("Migration backup manifest is missing or invalid.") from exc
    if not isinstance(manifest, dict):
        raise MigrationError("Migration backup manifest has an unsupported format.")
    files = manifest.get("files")
    if manifest.get("version") != 1 or not isinstance(files, list):
        raise MigrationError("Migration backup manifest has an unsupported format.")
    if any(name not in _SETUP_FILENAMES for name in files) or len(set(files)) != len(files):
        raise MigrationError("Migration backup manifest contains an unsafe path.")
    return manifest


def latest_recoverable_backup(server_dir: Path) -> Path | None:
    """Return the newest valid pending backup, if file conversion is uncommitted."""
    try:
        candidates = sorted(
            server_dir.glob(f"{_BACKUP_PREFIX}*"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError:
        return None
    for backup in candidates:
        try:
            manifest = _read_manifest(server_dir, backup)
        except MigrationError:
            continue
        if manifest.get("status") == "pending":
            return backup
    return None


def read_migration_intent(server_dir: Path, backup: Path) -> dict[str, Any]:
    """Return the durable attempt, including whether all file writes finished."""
    manifest = _read_manifest(server_dir, backup)
    intent = manifest.get("intent")
    if (
        not isinstance(intent, dict)
        or not isinstance(intent.get("name"), str)
        or not isinstance(intent.get("variables"), dict)
        or not isinstance(intent.get("files_ready"), bool)
    ):
        raise MigrationError("Migration recovery intent is invalid. Keep the server stopped.")
    return intent


def _atomic_restore(source: Path, target: Path) -> None:
    if not source.is_file() or _is_redirected(source):
        raise MigrationError(f"Backup file is missing or redirected: {source.name}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.restore-", dir=target.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        shutil.copy2(source, temp)
        if hasattr(os, "chown"):
            owner = source.stat()
            os.chown(temp, owner.st_uid, owner.st_gid)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def restore_backup(server_dir: Path, backup: Path) -> None:
    """Restore a pending backup, mark it restored, and retain its bytes."""
    _validate_paths(server_dir)
    manifest = _read_manifest(server_dir, backup)
    if manifest.get("status") != "pending":
        raise MigrationError("Migration backup is not pending and cannot be auto-restored.")
    files = manifest["files"]
    try:
        for filename in files:
            _atomic_restore(backup / filename, server_dir / filename)
        for filename in _SETUP_FILENAMES:
            if filename not in files:
                (server_dir / filename).unlink(missing_ok=True)
        _write_manifest(backup, files, "restored")
    except (OSError, MigrationError) as exc:
        raise MigrationError(
            f"Automatic recovery from {backup.name} could not finish. Keep the server stopped; "
            "the backup remains available for manual recovery."
        ) from exc


def mark_backup_complete(server_dir: Path, backup: Path) -> None:
    """Mark a pending backup committed after both database writes succeed."""
    manifest = _read_manifest(server_dir, backup)
    if manifest.get("status") != "pending":
        raise MigrationError("Migration backup is not pending and cannot be completed.")
    _write_manifest(backup, manifest["files"], "complete")


def migrate(name: str, variables: dict[str, Any], server_dir: Path) -> Path:
    """Validate, back up, convert, and remove obsolete root setup files."""
    variables = prepare_variables(name, variables, server_dir)
    _validate_requested_launch(variables)
    rendered_compose = scaffolding.render_compose(name, variables)
    rendered_start = scaffolding.render_start_script(variables)
    _validate_paths(server_dir)
    _validate_legacy_scripts(server_dir)
    launch_path, launch = _legacy_launch(server_dir)
    if launch_path is None or launch is None:
        raise MigrationError(
            "Could not safely reproduce the Java launch command. Use one line shaped like "
            "'exec java [JVM flags] -Xmx12G -jar server.jar nogui'; custom world names or other "
            "arguments after the jar must be migrated manually."
        )
    backup = _backup_setup(server_dir, name, variables)
    try:
        atomic_write_text(server_dir / "docker-compose.yml", rendered_compose)
        start_path = server_dir / "server" / "start_server.sh"
        atomic_write_text(start_path, rendered_start)
        start_path.chmod(0o755)
        for filename in _LEGACY_FILENAMES:
            runtime = variables.get(scaffolding.MANAGED_RUNTIME_KEY) or {}
            if filename == ".env" and runtime.get("env_file") == ".env":
                continue
            (server_dir / filename).unlink(missing_ok=True)
        manifest = _read_manifest(server_dir, backup)
        _write_manifest(backup, manifest["files"], "pending", {
            "name": name, "variables": variables, "files_ready": True,
        })
    except OSError as exc:
        try:
            restore_backup(server_dir, backup)
        except MigrationError as restore_exc:
            raise MigrationError(
                "Migration failed and automatic recovery could not finish. "
                "Keep the server stopped; "
                f"original setup files remain in {backup.name}."
            ) from restore_exc
        raise MigrationError(
            "Migration failed, so the original setup was restored. Fix directory access or free "
            "disk space before retrying."
        ) from exc
    return backup
