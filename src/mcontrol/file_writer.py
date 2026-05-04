"""Atomic writes for operator-edited / operator-uploaded files under a
server's bind-mount.

Used by the file-browser save endpoint (slice 5 PR 2) and the upload
endpoint (slice 5 PR 3). Mirrors the env_writer pattern: write a
sibling tempfile, then `os.replace()` over the target so a partial
write can never leave a half-baked file on disk visible to the running
container.

Files land as root, same as slice 4's env_writer — no chown step.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically replace `path` with `content` (utf-8, lf line endings).

    The parent directory must already exist. A sibling tempfile is used
    so the rename is on the same filesystem and is therefore atomic on
    POSIX. On error the tempfile is best-effort unlinked.
    """
    fd, tmp_str = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def atomic_write_stream(path: Path, src: BinaryIO) -> None:
    """Atomically replace `path` with bytes streamed from `src`.

    Used for uploads, where the source is an `UploadFile` whose contents
    may be arbitrarily large (mod jars, world backups). `shutil.copyfileobj`
    streams in 64 KB chunks so memory stays bounded.

    Same atomicity contract as `atomic_write_text`: sibling tempfile +
    `os.replace`. If the target is a symlink, `os.replace` swaps the
    symlink itself for the new file — it does not write through.
    """
    fd, tmp_str = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "wb") as f:
            shutil.copyfileobj(src, f)
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
