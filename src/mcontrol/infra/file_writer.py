"""Atomic writes for operator-edited / operator-uploaded files under a
server's bind-mount.

Used by the file-browser save endpoint (slice 5 PR 2) and the upload
endpoint (slice 5 PR 3). Writes a sibling tempfile, then `os.replace()`
over the target so a partial write can never leave a half-baked file on
disk visible to the running container.

Replacing a file keeps its mode and owner; a new file lands as 0644 owned
like its parent directory. chown is best-effort (needs root), so dev runs
as an ordinary user are unaffected.
"""

import asyncio
import os
import shutil
import stat
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO


def _chown_best_effort(path: Path, uid: int, gid: int) -> None:
    chown = getattr(os, "chown", None)
    if chown is None:
        return
    with suppress(PermissionError):
        chown(path, uid, gid)


def _adopt_ownership(tmp: Path, path: Path) -> None:
    """Give the tempfile the mode/owner `path` should end up with.

    mkstemp creates 0600 and os.replace keeps the tempfile's inode, so
    without this every panel write ends up root-only and the operator
    (or a non-root Minecraft image) loses read access. A symlink at
    `path` is being replaced, not written through, so it counts as new.
    """
    try:
        st = path.lstat()
    except FileNotFoundError:
        st = None
    if st is not None and not stat.S_ISLNK(st.st_mode):
        mode, uid, gid = stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid
    else:
        pst = path.parent.stat()
        mode, uid, gid = 0o644, pst.st_uid, pst.st_gid
    os.chmod(tmp, mode)
    _chown_best_effort(tmp, uid, gid)


def mkdir_inherit_owner(path: Path) -> None:
    """Create `path` as 0755 owned like its parent (chown best-effort)."""
    path.mkdir()
    os.chmod(path, 0o755)
    pst = path.parent.stat()
    _chown_best_effort(path, pst.st_uid, pst.st_gid)


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
        _adopt_ownership(tmp, path)
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
    symlink itself for the new file; it does not write through.
    """
    fd, tmp_str = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "wb") as f:
            shutil.copyfileobj(src, f)
        _adopt_ownership(tmp, path)
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


async def atomic_write_text_async(path: Path, content: str) -> None:
    """Async wrapper around `atomic_write_text`. Runs in a worker thread.

    Multi-megabyte writes would otherwise stall every other in-flight
    request under the single-worker uvicorn posture.
    """
    await asyncio.to_thread(atomic_write_text, path, content)


async def atomic_write_stream_async(path: Path, src: BinaryIO) -> None:
    """Async wrapper around `atomic_write_stream`. Runs in a worker thread.

    Upload bodies can be arbitrarily large (mod jars, world backups);
    streaming them inline would block the event loop for the duration
    of the copy.
    """
    await asyncio.to_thread(atomic_write_stream, path, src)
