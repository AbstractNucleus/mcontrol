"""Legacy itzg → scaffold-shape migration (slice 8).

Pure file IO + small regex parsing. No DB writes. those happen in
`routes/migrate.py`, which brackets the call to `migrate(...)` with
`db.update_variables` and `db.mark_scaffolded` for symmetry with
`routes/new_server.py`.

The target shape is a generated `docker-compose.yml`
referencing `eclipse-temurin:<java_version>-jre` directly + a re-rendered
`server/start_server.sh`. The migration deletes the four legacy build
files (Dockerfile, entrypoint.sh, .dockerignore, .env) and is
intentionally one-way.
"""

import re
from pathlib import Path
from typing import Any

from mcontrol.domain import scaffolding

_LEGACY_FILENAMES = ("Dockerfile", "entrypoint.sh", ".dockerignore", ".env")

_XMX_RE = re.compile(r"-Xmx(\d+)[gG]\b")
_JAR_RE = re.compile(r'-jar\s+"?([^"\s]+)"?')
_PORT_RE = re.compile(r'"(\d+):25565"')
_MEM_LIMIT_RE = re.compile(r"mem_limit:\s*(\d+)[gG]\b")
_JAVA_IMAGE_RE = re.compile(r"eclipse-temurin:(\d+)")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_compose_port(server_dir: Path) -> int | None:
    """First `"<host>:25565"` mapping in `<dir>/docker-compose.yml`, or
    None. Also used by the port-collision check for legacy rows whose
    `variables` never acquired a `port`."""
    match = _PORT_RE.search(_read_text(server_dir / "docker-compose.yml"))
    return int(match.group(1)) if match else None


def legacy_files(server_dir: Path) -> list[Path]:
    """Return paths of the legacy build files that exist under <dir>.

    Order matches `_LEGACY_FILENAMES`. A file's absence is fine. the
    migration is idempotent and `migrate()` unlinks with `missing_ok=True`
    regardless. This helper exists for the migration card preview.
    """
    return [server_dir / name for name in _LEGACY_FILENAMES if (server_dir / name).exists()]


def parse_legacy_variables(server_dir: Path) -> dict[str, Any]:
    """Best-effort parse to pre-populate the migration form.

    Reads `<dir>/server/start_server.sh` (falling back to the legacy
    `<dir>/entrypoint.sh`) for `-Xmx<N>g`, `-jar <file>`, and any flags
    between; `<dir>/docker-compose.yml` for the first `"<host>:25565"`
    mapping and, when no `-Xmx` was found, `mem_limit: <N>g`; and the
    legacy Dockerfile for its `eclipse-temurin:<N>` tag.
    `memory_budget_gb = parsed_xmx + 2` so the heap is preserved
    post-migration (slice-6's `-Xmx = budget − 2`).

    Failures leave the corresponding key absent; the caller renders blank
    fields and lets form validation catch any leftover holes.
    """
    out: dict[str, Any] = {}

    xmx_match = jar_match = None
    script_text = ""
    for script_path in (server_dir / "server" / "start_server.sh", server_dir / "entrypoint.sh"):
        script_text = _read_text(script_path)
        xmx_match = _XMX_RE.search(script_text)
        jar_match = _JAR_RE.search(script_text)
        if xmx_match or jar_match:
            break

    if xmx_match:
        out["memory_budget_gb"] = int(xmx_match.group(1)) + scaffolding.HEADROOM_GB
    if jar_match:
        out["server_jar"] = jar_match.group(1)
    if xmx_match and jar_match:
        between = script_text[xmx_match.end():jar_match.start()].strip()
        if between:
            out["jvm_extra_args"] = between

    compose_text = _read_text(server_dir / "docker-compose.yml")
    port_match = _PORT_RE.search(compose_text)
    if port_match:
        out["port"] = int(port_match.group(1))
    if "memory_budget_gb" not in out:
        mem_match = _MEM_LIMIT_RE.search(compose_text)
        if mem_match:
            out["memory_budget_gb"] = int(mem_match.group(1))

    java_match = _JAVA_IMAGE_RE.search(_read_text(server_dir / "Dockerfile"))
    if java_match and int(java_match.group(1)) in scaffolding.JAVA_VERSIONS:
        out["java_version"] = int(java_match.group(1))

    return out


def migrate(name: str, variables: dict[str, Any], server_dir: Path) -> None:
    """Converge `<server_dir>/` on slice-6 scaffold output.

    `server_dir` is the row's bound directory (Bindings may have
    repointed it away from `<base>/<name>`).

    Steps in order:
      1. Render + atomic-write docker-compose.yml and server/start_server.sh
         via `scaffolding.write_scaffold_files` (StrictUndefined raises
         before any IO).
      2. Unlink each legacy file with `missing_ok=True`.

    No DB writes; no rollback. Re-running after a partial success
    converges on the same end state. every step is idempotent.
    """
    scaffolding.write_scaffold_files(server_dir, name, variables)

    for filename in _LEGACY_FILENAMES:
        (server_dir / filename).unlink(missing_ok=True)
