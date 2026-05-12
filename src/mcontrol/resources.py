"""Per-server resource reads (slice 9 PR 0).

Three pure-ish functions feeding the detail-page Resources card:

  - read_container_stats(container_name) -> dict
        Tagged dict: {"status": "ok", cpu_percent, mem_used, mem_limit}
        on success; {"status": "not-running"} when the container exists
        but isn't running; {"status": "unreachable"} when the daemon is
        unreachable or the container is missing entirely. Three states
        so the card caption can be specific without the route having to
        call back into docker_client to disambiguate.
  - read_disk_usage(server_dir) -> int
        Recursive byte total of server_dir, walked with
        follow_symlinks=False so an operator-introduced symlink can't
        redirect the walk outside the bind-mount or double-count target
        bytes.
  - format_bytes(n) -> str
        Base-1024, KiB/MiB/GiB/TiB.

Decisions: 006 (engine API via the existing socket mount), 008 (dir is
a real host path), 009 (mem_limit reflects what the cgroup is actually
enforcing, read from the same stats payload), 021 (caller resolves the
container via db.container_name_for(row)).
"""

import os
from contextlib import suppress
from pathlib import Path
from typing import Any

import aiodocker

from mcontrol.settings import Settings


def _settings() -> Settings:
    return Settings()


async def read_container_stats(container_name: str) -> dict[str, Any]:
    try:
        docker = aiodocker.Docker(url=_settings().docker_host)
    except Exception:
        return {"status": "unreachable"}

    try:
        try:
            container = await docker.containers.get(container_name)
        except Exception:
            return {"status": "unreachable"}

        try:
            info = await container.show()
        except Exception:
            return {"status": "unreachable"}
        if not info.get("State", {}).get("Running", False):
            return {"status": "not-running"}

        try:
            result = await container.stats(stream=False)
        except Exception:
            return {"status": "unreachable"}
        snapshot = result[0] if isinstance(result, list) else result

        return {
            "status": "ok",
            "cpu_percent": _cpu_percent(snapshot),
            "mem_used": _mem_used(snapshot),
            "mem_limit": int(snapshot.get("memory_stats", {}).get("limit", 0) or 0),
        }
    finally:
        with suppress(Exception):
            await docker.close()


def _cpu_percent(snapshot: dict[str, Any]) -> float:
    """`docker stats`-style aggregated CPU percent across cores.

    Returns 0.0 on the zero-delta first-tick edge — matches the
    daemon's own behaviour when precpu_stats is empty."""
    cpu = snapshot.get("cpu_stats", {}) or {}
    pre = snapshot.get("precpu_stats", {}) or {}
    cpu_total = cpu.get("cpu_usage", {}).get("total_usage", 0) or 0
    pre_total = pre.get("cpu_usage", {}).get("total_usage", 0) or 0
    sys_total = cpu.get("system_cpu_usage", 0) or 0
    pre_sys = pre.get("system_cpu_usage", 0) or 0
    cpu_delta = cpu_total - pre_total
    sys_delta = sys_total - pre_sys
    online = cpu.get("online_cpus") or 1
    if cpu_delta > 0 and sys_delta > 0:
        return (cpu_delta / sys_delta) * online * 100.0
    return 0.0


def _mem_used(snapshot: dict[str, Any]) -> int:
    """Working-set memory: usage minus page-cache, matching `docker
    stats`. cgroup v2 reports inactive_file; cgroup v1 reports cache;
    older shapes report neither and we fall back to raw usage."""
    mem = snapshot.get("memory_stats", {}) or {}
    usage = int(mem.get("usage", 0) or 0)
    stats = mem.get("stats", {}) or {}
    if "inactive_file" in stats:
        return max(0, usage - int(stats["inactive_file"] or 0))
    if "cache" in stats:
        return max(0, usage - int(stats["cache"] or 0))
    return usage


# Cache: resolved path → (mtime, total_bytes). Invalidated when root mtime changes.
_disk_cache: dict[Path, tuple[float, int]] = {}


def read_disk_usage(server_dir: Path) -> int:
    """Recursive byte total of server_dir.

    Walks with ``follow_symlinks=False`` on both ``scandir`` and
    ``stat`` — an operator-introduced symlink contributes only its own
    link-inode bytes, and a symlink to a directory is not recursed
    into. Missing root returns 0.

    Result is cached by (resolved path, root mtime). A cache hit skips
    the full-tree walk; the cache entry is replaced when the root mtime
    advances (e.g. a file was added or removed directly under the root).
    """
    root = Path(server_dir).resolve()

    try:
        mtime = root.stat().st_mtime
    except OSError:
        mtime = None

    if mtime is not None:
        cached = _disk_cache.get(root)
        if cached is not None and cached[0] == mtime:
            return cached[1]

    total = 0
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            it = os.scandir(current)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        with it:
            for entry in it:
                try:
                    if entry.is_symlink():
                        with suppress(OSError):
                            total += entry.stat(follow_symlinks=False).st_size
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                        continue
                    with suppress(OSError):
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue

    if mtime is not None:
        _disk_cache[root] = (mtime, total)
    return total


def format_bytes(n: int) -> str:
    """Base-1024 byte formatter — KiB/MiB/GiB/TiB with one decimal."""
    if n < 1024:
        return f"{n} B"
    val = float(n)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        val /= 1024
        if val < 1024 or unit == "TiB":
            return f"{val:.1f} {unit}"
    return f"{val:.1f} TiB"
