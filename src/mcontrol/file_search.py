"""Per-server in-memory search index for the files tree.

App-wide state lifted out of `routes/files.py`. The index
is consulted on every debounced keystroke of the search input (see
issue #49), so memoising the walk is the win. The cache lives in the
process; single-uvicorn-worker operation is assumed and multi-worker
invalidation is explicitly out of scope.

FastAPI-unaware: this module imports neither `fastapi` nor the route
layer. Routes call `get_search_index` on hit and `invalidate` on
mutation; the helpers `_now`, `_INDEX_TTL_SECONDS`, and `_search_index`
remain module-level so tests can pin the clock or clear state between
runs (same pattern as before the split).
"""

import os
import stat
import time
from pathlib import Path

from mcontrol import file_safety

# High-cardinality subdirs inside a Minecraft world whose contents are
# addressed by machine-generated names (chunk regions, per-player data
# files, etc.). They almost never match operator-meaningful queries but
# saturate the result cap with noise. The skip only fires when the dir
# sits directly under a `world`-named or `DIM*`-prefixed parent so a
# top-level dir that happens to share a name is searched normally.
_SEARCH_DEFAULT_SKIP_DIRS = frozenset({
    "region",
    "entities",
    "poi",
    "playerdata",
    "stats",
    "advancements",
})

_INDEX_TTL_SECONDS = 60.0

# Module-level cache. Each value is a dict with optional `default` and
# `with_chunks` slots; each slot is `(built_at, entries, skipped_flag)`.
# Each server has two slots: the default `index` (skip-set applied at
# build time, per issue #50) and a separate `index_with_chunks`
# populated lazily when an operator passes `include_chunks=1`. Keeping
# them separate avoids re-walking on every toggle and avoids storing a
# superset that would then need re-filtering at query time.
_search_index: dict[str, dict[str, tuple[float, list[tuple[str, str, str]], bool]]] = {}


def _now() -> float:
    """Monotonic clock used for TTL checks. Indirected so tests can
    monkeypatch it without touching the global `time` module."""
    return time.monotonic()


def _is_world_like_parent(parent_name: str) -> bool:
    return parent_name == "world" or parent_name.startswith("DIM")


def invalidate(server_name: str) -> None:
    """Drop both cache slots for `server_name`. Called from every
    mutating handler. A no-op if the server has no cached index."""
    _search_index.pop(server_name, None)


def _build_index(
    base: Path, include_chunks: bool
) -> tuple[list[tuple[str, str, str]], bool]:
    """Walk `base` once and return (entries, skipped).

    `entries` is a list of `(name_lower, relpath, kind)` tuples; special
    files are filtered out at this stage. Symlinked directories are not
    descended (followlinks=False). When `include_chunks` is False the
    default skip-set (see `_SEARCH_DEFAULT_SKIP_DIRS`) is applied during
    the walk so chunk/region noise never enters the index.
    """
    entries: list[tuple[str, str, str]] = []
    skipped = False
    for root, dirs, files in os.walk(base, followlinks=False):
        dirs.sort()
        files.sort()
        if not include_chunks and _is_world_like_parent(Path(root).name):
            keep = [d for d in dirs if d not in _SEARCH_DEFAULT_SKIP_DIRS]
            if len(keep) != len(dirs):
                skipped = True
                dirs[:] = keep
        for entry_name in dirs + files:
            full = Path(root) / entry_name
            try:
                st = full.lstat()
            except OSError:
                continue
            if file_safety.is_special(st.st_mode):
                continue
            kind = (
                "symlink" if stat.S_ISLNK(st.st_mode)
                else ("dir" if stat.S_ISDIR(st.st_mode) else "file")
            )
            rel = full.relative_to(base).as_posix()
            entries.append((entry_name.lower(), rel, kind))
    return entries, skipped


def get_search_index(
    server_name: str, base: Path, include_chunks: bool
) -> tuple[list[tuple[str, str, str]], bool]:
    """Return the cached index for the (server, include_chunks) pair,
    rebuilding on miss or after TTL expiry."""
    slot_key = "with_chunks" if include_chunks else "default"
    server_slots = _search_index.get(server_name)
    if server_slots is not None:
        slot = server_slots.get(slot_key)
        if slot is not None:
            built_at, entries, skipped = slot
            if _now() - built_at < _INDEX_TTL_SECONDS:
                return entries, skipped

    entries, skipped = _build_index(base, include_chunks)
    _search_index.setdefault(server_name, {})[slot_key] = (
        _now(), entries, skipped,
    )
    return entries, skipped
