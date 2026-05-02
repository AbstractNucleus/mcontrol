"""Async wrapper over `docker compose` (v2 plugin) for the slice-4
lifecycle path that needs `--force-recreate` semantics.

We shell out (rather than calling aiodocker directly) because the
per-server docker-compose.yml is the source of truth for the MC
container's full shape (image, env, volumes, networks). Re-implementing
that in aiodocker would mean parsing compose ourselves; ~50 MB of
docker-cli + compose-plugin in the runtime image is a better trade.
"""

import asyncio
from pathlib import Path


class ComposeError(RuntimeError):
    """Raised when `docker compose` exits non-zero."""


async def up_force_recreate(server_dir: Path) -> None:
    """Run `docker compose -f <server_dir>/docker-compose.yml up -d --force-recreate`.

    Raises ComposeError with the captured stderr on non-zero exit.
    """
    compose_file = server_dir / "docker-compose.yml"

    proc = await asyncio.create_subprocess_exec(
        "docker", "compose",
        "-f", str(compose_file),
        "up", "-d", "--force-recreate",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip() or "docker compose failed"
        raise ComposeError(message)
