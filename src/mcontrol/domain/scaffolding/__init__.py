"""Server scaffolding. render docker-compose.yml + start_server.sh.

No per-server Dockerfile / entrypoint / .dockerignore. The generated
docker-compose.yml references eclipse-temurin:<java_version>-jre
directly; start_server.sh lives inside the bind-mounted server/
directory alongside the operator's jars and configs.

Pure file IO. PR 2 wraps this with the new-server endpoint's DB-first
ordering and path-safety contract.
"""

import os
import re
import secrets
import shlex
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from mcontrol.infra.file_writer import atomic_write_text

_TEMPLATES_DIR = Path(__file__).parent / "templates"
# -Xmx = mem_limit - 2 GB headroom (JIT, native libs, mod metadata).
HEADROOM_GB = 2
# Smallest budget that still leaves a 1 GB heap; the validator and every
# form's min= attribute read this so they can't drift from the template.
MEMORY_MIN_GB = HEADROOM_GB + 1

# eclipse-temurin tags the scaffold may reference. Rows written before
# java_version existed have no key and must keep rendering :21-jre, or
# Regenerate would show a spurious diff on every existing server.
JAVA_VERSIONS: tuple[int, ...] = (17, 21, 25)
DEFAULT_JAVA_VERSION = 21

RCON_PORT = 25575
MANAGED_RUNTIME_KEY = "managed_runtime"
_SERVICE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_UDP_PORT_RE = re.compile(r"(\d{1,5}):(\d{1,5})/udp\Z")

_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def _managed_runtime(variables: dict[str, Any]) -> dict[str, Any] | None:
    value = variables.get(MANAGED_RUNTIME_KEY)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("managed_runtime must be an object")
    service = value.get("compose_service")
    if not isinstance(service, str) or not _SERVICE_RE.fullmatch(service):
        raise ValueError("managed_runtime compose_service is invalid")
    ports = value.get("extra_udp_ports", [])
    if not isinstance(ports, list) or any(not isinstance(port, str) for port in ports):
        raise ValueError("managed_runtime extra_udp_ports must be a list")
    for port in ports:
        match = _UDP_PORT_RE.fullmatch(port)
        if match is None or any(not 1 <= int(number) <= 65535 for number in match.groups()):
            raise ValueError("managed_runtime contains an invalid UDP port")
    expected_label = f"com.noelkleen.service={service}"
    if value.get("labels", []) not in ([], [expected_label]):
        raise ValueError("managed_runtime contains unsupported labels")
    env_file = value.get("env_file")
    rcon = value.get("rcon_password_env", False)
    if env_file not in (None, ".env") or not isinstance(rcon, bool):
        raise ValueError("managed_runtime environment settings are invalid")
    if bool(env_file) != rcon:
        raise ValueError("managed_runtime RCON environment settings are incomplete")
    return value


def render_compose(name: str, variables: dict[str, Any]) -> str:
    rendered = _env.get_template("docker-compose.yml.j2").render(
        name=name,
        memory_budget_gb=variables["memory_budget_gb"],
        port=variables["port"],
        java_version=variables.get("java_version", DEFAULT_JAVA_VERSION),
    )
    runtime = _managed_runtime(variables)
    if runtime is None:
        return rendered
    compose = yaml.safe_load(rendered)
    service = compose["services"].pop(name)
    service_name = runtime["compose_service"]
    compose["services"][service_name] = service
    service["ports"].extend(runtime.get("extra_udp_ports", []))
    if runtime.get("labels"):
        service["labels"] = runtime["labels"]
    if runtime.get("env_file"):
        service["env_file"] = [runtime["env_file"]]
    return yaml.safe_dump(compose, sort_keys=False, allow_unicode=True)


def render_server_properties(rcon_password: str) -> str:
    return _env.get_template("server.properties.j2").render(
        rcon_port=RCON_PORT,
        rcon_password=rcon_password,
    )


def generate_rcon_password() -> str:
    # 18 random bytes → exactly 24 URL-safe chars, no padding.
    return secrets.token_urlsafe(18)


def _inherit_owner(base: Path, *dirs: Path) -> None:
    """Best-effort chown of freshly created dirs to <base>'s owner, so a
    root-running panel doesn't leave root:root dirs the operator can't
    touch. No-op when not root (PermissionError) or on Windows (no
    os.chown)."""
    with suppress(PermissionError, AttributeError):
        st = base.stat()
        for d in dirs:
            os.chown(d, st.st_uid, st.st_gid)


def render_start_script(variables: dict[str, Any]) -> str:
    custom_start_script = variables.get("custom_start_script", "")
    if custom_start_script:
        error = custom_start_script_error(custom_start_script)
        if error:
            raise ValueError(error)
    runtime = _managed_runtime(variables)
    rcon_prelude = ""
    if runtime and runtime.get("rcon_password_env"):
        rcon_prelude = (
            'cd "$(dirname "$0")"\n\n'
            'if [[ -n "${RCON_PASSWORD:-}" && -f server.properties ]]; then\n'
            "  if grep -q '^rcon.password=' server.properties; then\n"
            '    sed -i "s/^rcon.password=.*/rcon.password=${RCON_PASSWORD}/" '
            "server.properties\n"
            "  else\n"
            "    printf '\\nrcon.password=%s\\n' \"${RCON_PASSWORD}\" >> server.properties\n"
            "  fi\n"
            "fi\n\n"
        )
    elif custom_start_script:
        rcon_prelude = 'cd "$(dirname "$0")"\n\n'
    return _env.get_template("start_server.sh.j2").render(
        xmx_gb=variables["memory_budget_gb"] - HEADROOM_GB,
        jvm_extra_args=variables.get("jvm_extra_args", ""),
        server_jar=variables["server_jar"] if not custom_start_script else "",
        custom_start_script=(
            shlex.quote(f"./{PurePosixPath(custom_start_script)}")
            if custom_start_script else ""
        ),
        rcon_prelude=rcon_prelude,
    )


def custom_start_script_error(value: str) -> str | None:
    """Check a Linux script path relative to the server data directory."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\\" in value
        or ":" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or PurePosixPath(value).is_absolute()
        or ".." in value.split("/")
    ):
        return (
            "Use a relative Linux .sh path inside server/; "
            "absolute paths and .. are not allowed."
        )
    path = PurePosixPath(value)
    if path.suffix != ".sh":
        return "Use a Linux .sh script, such as run.sh; Windows .bat scripts are not supported."
    if path == PurePosixPath("start_server.sh"):
        return "start_server.sh is managed by mcontrol. Choose the modpack's own script."
    return None


def write_scaffold_files(
    server_dir: Path, name: str, variables: dict[str, Any]
) -> None:
    """Render and atomically write the two generated files under
    ``<server_dir>/``: ``docker-compose.yml`` and
    ``server/start_server.sh`` (chmod 0o755).

    Both templates render *before* any write, so a StrictUndefined hole
    raises before touching disk. Shared by the new-server scaffold, the
    legacy migration, and the regenerate confirm so all three stay
    byte-identical and inherit the atomic-write contract.
    """
    rendered_compose = render_compose(name, variables)
    rendered_start = render_start_script(variables)

    inner = server_dir / "server"
    inner.mkdir(parents=True, exist_ok=True)

    atomic_write_text(server_dir / "docker-compose.yml", rendered_compose)
    start_path = inner / "start_server.sh"
    atomic_write_text(start_path, rendered_start)
    start_path.chmod(0o755)


def scaffold(name: str, variables: dict[str, Any], base: Path) -> None:
    """Write the scaffold files for a new server under <base>/<name>/.

    Layout:
      <base>/<name>/docker-compose.yml
      <base>/<name>/server/start_server.sh   (chmod 0o755)
      <base>/<name>/server/eula.txt
      <base>/<name>/server/server.properties (RCON enabled; only when absent)

    server.properties is written here and nowhere else: the console,
    players card and online chip all need RCON, but the file is
    operator-owned afterwards, so migrate/regenerate never touch it.
    """
    server_dir = base / name
    inner = server_dir / "server"
    inner.mkdir(parents=True, exist_ok=True)
    _inherit_owner(base, server_dir, inner)

    write_scaffold_files(server_dir, name, variables)
    atomic_write_text(inner / "eula.txt", "eula=true\n")

    props_path = inner / "server.properties"
    if not props_path.exists():
        atomic_write_text(
            props_path, render_server_properties(generate_rcon_password())
        )
