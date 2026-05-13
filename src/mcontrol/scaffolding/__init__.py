"""Server scaffolding — render docker-compose.yml + start_server.sh.

Decision 023: no per-server Dockerfile / entrypoint / .dockerignore.
The generated docker-compose.yml references eclipse-temurin:21-jre
directly; start_server.sh lives inside the bind-mounted server/
directory alongside the operator's jars and configs.

Pure file IO. PR 2 wraps this with the new-server endpoint's DB-first
ordering and path-safety contract.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from mcontrol.file_writer import atomic_write_text

_TEMPLATES_DIR = Path(__file__).parent / "templates"
# Decision 009: -Xmx = mem_limit - 2 GB headroom (JIT, native libs, mod metadata).
_HEADROOM_GB = 2

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
        xmx_gb=variables["memory_budget_gb"] - _HEADROOM_GB,
        jvm_extra_args=variables.get("jvm_extra_args", ""),
        server_jar=variables["server_jar"],
    )


def scaffold(name: str, variables: dict[str, Any], base: Path) -> None:
    """Write the scaffold files for a new server under <base>/<name>/.

    Layout:
      <base>/<name>/docker-compose.yml
      <base>/<name>/server/start_server.sh   (chmod 0o755)
      <base>/<name>/server/eula.txt

    Both files go through file_writer.atomic_write_text so PR 4's
    regenerate flow inherits the same atomicity contract.
    """
    server_dir = base / name
    inner = server_dir / "server"
    inner.mkdir(parents=True, exist_ok=True)

    atomic_write_text(server_dir / "docker-compose.yml", render_compose(name, variables))
    start_path = inner / "start_server.sh"
    atomic_write_text(start_path, render_start_script(variables))
    start_path.chmod(0o755)
    atomic_write_text(inner / "eula.txt", "eula=true\n")
