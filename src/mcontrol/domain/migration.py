"""Legacy itzg → scaffold-shape migration (slice 8).

Pure file IO + small regex parsing. No DB writes — those happen in
`routes/migrate.py`, which brackets the call to `migrate(...)` with
`db.update_variables` and `db.mark_scaffolded` for symmetry with
`routes/new_server.py`.

Decision 023 fixes the target shape: a generated `docker-compose.yml`
referencing `eclipse-temurin:21-jre` directly + a re-rendered
`server/start_server.sh`. The migration deletes the four legacy build
files (Dockerfile, entrypoint.sh, .dockerignore, .env) and is
intentionally one-way (decision 028, ratified on PR 1).
"""

import re
from pathlib import Path
from typing import Any

from mcontrol.domain import scaffolding
from mcontrol.file_writer import atomic_write_text

_LEGACY_FILENAMES = ("Dockerfile", "entrypoint.sh", ".dockerignore", ".env")
_HEADROOM_GB = 2  # decision 009; mirrored from scaffolding._HEADROOM_GB.

_XMX_RE = re.compile(r"-Xmx(\d+)[gG]\b")
_JAR_RE = re.compile(r"-jar\s+(\S+)")
_PORT_RE = re.compile(r'"(\d+):25565"')


def legacy_files(server_dir: Path) -> list[Path]:
    """Return paths of the legacy build files that exist under <dir>.

    Order matches `_LEGACY_FILENAMES`. A file's absence is fine — the
    migration is idempotent and `migrate()` unlinks with `missing_ok=True`
    regardless. This helper exists for the migration card preview.
    """
    return [server_dir / name for name in _LEGACY_FILENAMES if (server_dir / name).exists()]


def parse_legacy_variables(server_dir: Path) -> dict[str, Any]:
    """Best-effort parse to pre-populate the migration form.

    Reads `<dir>/server/start_server.sh` for `-Xmx<N>g`, `-jar <file>`,
    and any flags between, and `<dir>/docker-compose.yml` for the first
    `"<host>:25565"` mapping. `memory_budget_gb = parsed_xmx + 2` so the
    heap is preserved post-migration (slice-6's `-Xmx = budget − 2`).

    Failures leave the corresponding key absent; the caller renders blank
    fields and lets form validation catch any leftover holes.
    """
    out: dict[str, Any] = {}

    start_path = server_dir / "server" / "start_server.sh"
    try:
        start_text = start_path.read_text(encoding="utf-8")
    except OSError:
        start_text = ""

    xmx_match = _XMX_RE.search(start_text)
    jar_match = _JAR_RE.search(start_text)
    if xmx_match:
        out["memory_budget_gb"] = int(xmx_match.group(1)) + _HEADROOM_GB
    if jar_match:
        out["server_jar"] = jar_match.group(1)
    if xmx_match and jar_match:
        between = start_text[xmx_match.end():jar_match.start()].strip()
        if between:
            out["jvm_extra_args"] = between

    compose_path = server_dir / "docker-compose.yml"
    try:
        compose_text = compose_path.read_text(encoding="utf-8")
    except OSError:
        compose_text = ""
    port_match = _PORT_RE.search(compose_text)
    if port_match:
        out["port"] = int(port_match.group(1))

    return out


def migrate(name: str, variables: dict[str, Any], base: Path) -> None:
    """Converge `<base>/<name>/` on slice-6 scaffold output.

    Steps in order:
      1. Render both templates (StrictUndefined raises here, before any IO).
      2. Atomic-write `<dir>/docker-compose.yml`.
      3. Atomic-write `<dir>/server/start_server.sh` (chmod 0o755).
      4. Unlink each legacy file with `missing_ok=True`.

    No DB writes; no rollback. Re-running after a partial success
    converges on the same end state — every step is idempotent.
    """
    rendered_compose = scaffolding.render_compose(name, variables)
    rendered_start = scaffolding.render_start_script(variables)

    server_dir = base / name
    inner = server_dir / "server"
    inner.mkdir(parents=True, exist_ok=True)

    atomic_write_text(server_dir / "docker-compose.yml", rendered_compose)
    start_path = inner / "start_server.sh"
    atomic_write_text(start_path, rendered_start)
    start_path.chmod(0o755)

    for filename in _LEGACY_FILENAMES:
        (server_dir / filename).unlink(missing_ok=True)
