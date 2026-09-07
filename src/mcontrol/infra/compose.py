"""Run ``docker compose up -d`` for a server directory.

The panel image ships the docker CLI and compose plugin. Freshly
scaffolded servers have a compose file but no container; Start and
Recreate go through here rather than asking the operator to SSH.
"""

import asyncio
from pathlib import Path

_DEFAULT_TIMEOUT_S = 180.0
_STDERR_TAIL = 2000


class ComposeError(Exception):
    """``docker compose up`` failed, timed out, or the CLI is missing."""


async def compose_up(server_dir: Path, *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> None:
    compose_file = server_dir / "docker-compose.yml"
    if not compose_file.is_file():
        raise ComposeError(f"no docker-compose.yml in {server_dir}")
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "--project-directory",
            str(server_dir),
            "up",
            "-d",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ComposeError("docker CLI not found") from exc
    try:
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise ComposeError(f"docker compose up timed out after {timeout_s:.0f}s") from None
    if proc.returncode != 0:
        tail = (stderr or b"").decode("utf-8", errors="replace")[-_STDERR_TAIL:]
        raise ComposeError(
            f"docker compose up failed ({proc.returncode}): {tail.strip() or 'no stderr'}"
        )
