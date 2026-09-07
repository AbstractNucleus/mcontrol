"""Server scaffolding. render docker-compose.yml + start_server.sh.

No per-server Dockerfile / entrypoint / .dockerignore. The generated
docker-compose.yml references eclipse-temurin:<java_version>-jre
directly; start_server.sh lives inside the bind-mounted server/
directory alongside the operator's jars and configs.

Pure file IO. PR 2 wraps this with the new-server endpoint's DB-first
ordering and path-safety contract.
"""

import os
import secrets
from contextlib import suppress
from pathlib import Path
from typing import Any

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

_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def render_compose(name: str, variables: dict[str, Any]) -> str:
    return _env.get_template("docker-compose.yml.j2").render(
        name=name,
        memory_budget_gb=variables["memory_budget_gb"],
        port=variables["port"],
        java_version=variables.get("java_version", DEFAULT_JAVA_VERSION),
    )


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
    return _env.get_template("start_server.sh.j2").render(
        xmx_gb=variables["memory_budget_gb"] - HEADROOM_GB,
        jvm_extra_args=variables.get("jvm_extra_args", ""),
        server_jar=variables["server_jar"],
    )


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
