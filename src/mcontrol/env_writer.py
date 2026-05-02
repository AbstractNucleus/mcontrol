"""Atomic writer for the `RCON_PASSWORD=...` line in <dir>/.env.

Per decision 010, mcontrol owns this file's RCON_PASSWORD entry. Other
keys (operator-managed) are preserved verbatim. The write goes through
a temp file + os.replace so a partial write can't leave a half-baked
.env on disk.
"""

import os
import tempfile
from pathlib import Path

_RCON_KEY = "RCON_PASSWORD"


def write_rcon_password(env_path: Path, password: str) -> None:
    """Set RCON_PASSWORD=<password> in env_path, preserving other lines.

    Creates env_path (and parent dirs) if absent.
    """
    env_path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text().splitlines()

    new_lines: list[str] = []
    replaced = False
    for line in existing_lines:
        if line.startswith(f"{_RCON_KEY}="):
            new_lines.append(f"{_RCON_KEY}={password}")
            replaced = True
        else:
            new_lines.append(line)

    if not replaced:
        new_lines.append(f"{_RCON_KEY}={password}")

    body = "\n".join(new_lines) + "\n"

    # Atomic replace: write to a sibling temp file, then rename over.
    fd, tmp_str = tempfile.mkstemp(prefix=".env.", dir=str(env_path.parent))
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        tmp_path.replace(env_path)
    except Exception:
        # Best-effort cleanup of the temp file if the rename failed.
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def read_rcon_password(env_path: Path) -> str | None:
    """Return the current RCON_PASSWORD value, or None if not set."""
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{_RCON_KEY}="):
            return line.split("=", 1)[1]
    return None
