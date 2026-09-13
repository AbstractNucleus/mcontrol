"""Cross-process advisory locks for cooperating panel mutations."""

import asyncio
import errno
import hashlib
import os
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import BinaryIO

_process_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def drain_on_cancel(awaitable: Awaitable[object]) -> object:
    """Delay cancellation until a started mutation has settled."""
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if not task.cancelled():
            task.exception()
        raise


def _try_lock_file(file: BinaryIO) -> bool:
    if os.name == "nt":
        import msvcrt

        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return False
            raise
    else:
        import fcntl

        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True


async def _acquire_file(file: BinaryIO) -> None:
    while not await asyncio.to_thread(_try_lock_file, file):
        await asyncio.sleep(0.05)


def _unlock_file(file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def _path(base: Path, name: str) -> Path:
    digest = hashlib.sha256(name.encode()).hexdigest()[:16]
    return base / ".mcontrol-locks" / f"{digest}.lock"


@asynccontextmanager
async def server_mutation_lock(base: Path, name: str) -> AsyncIterator[None]:
    """Serialize cooperating panel mutations for ``name``.

    The asyncio lock avoids tying up a worker thread for same-process waiters;
    the OS advisory lock covers multiple panel processes sharing ``base``.
    External Docker CLI commands do not participate in this lock.
    """
    lock_path = _path(base.resolve(), name)
    key = str(lock_path)
    async with _process_locks[key]:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as file:
            if file.tell() == 0:
                file.write(b"0")
                file.flush()
            await _acquire_file(file)
            try:
                yield
            finally:
                await asyncio.to_thread(_unlock_file, file)
