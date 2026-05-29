"""Server scaffolding. render docker-compose.yml + start_server.sh.

No per-server Dockerfile / entrypoint / .dockerignore. The generated
docker-compose.yml references eclipse-temurin:21-jre directly;
start_server.sh lives inside the bind-mounted server/ directory
alongside the operator's jars and configs.

Pure file IO. PR 2 wraps this with the new-server endpoint's DB-first
ordering and path-safety contract.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from mcontrol.infra.file_writer import atomic_write_text

_TEMPLATES_DIR = Path(__file__).parent / "templates"
# -Xmx = mem_limit - 2 GB headroom (JIT, native libs, mod metadata).
HEADROOM_GB = 2

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
    )


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
    """
    server_dir = base / name
    write_scaffold_files(server_dir, name, variables)
    atomic_write_text(server_dir / "server" / "eula.txt", "eula=true\n")
