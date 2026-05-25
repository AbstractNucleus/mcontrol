"""Disk-backed per-server whitelist + ops file ops (slice 7 PR 1).

This module is the only writer of ``<server-dir>/server/whitelist.json``
and ``<server-dir>/server/ops.json``. These files are the source of
truth for membership; the DB roster (slice 7 PR 0) holds identities only.

Vanilla shape:

  - ``whitelist.json``: list of ``{"uuid", "name"}``.
  - ``ops.json``      . list of ``{"uuid", "name", "level", "bypassesPlayerLimit"}``.
  - 2-space indent, trailing newline, insertion order preserved on round-trip.

mtime stale-write guard mirrors the slice-5 file-editor pattern: read
returns ``(entries, mtime_ns)``; write asserts the file's current
mtime_ns matches the value the caller saw at read time, raising
:class:`StaleWriteError` on drift. Pass ``mtime_ns=0`` to mean
"expected no file". useful for first-time writes; if a file appears
between the call site's intent and the write, the guard refuses.

The running-server write path lives in slice 7 PR 2 and goes through
RCON instead. This module is the offline path.
"""

import json
from pathlib import Path
from typing import Any

from mcontrol.file_writer import atomic_write_text

_OP_DEFAULT_LEVEL = 4
_OP_DEFAULT_BYPASSES = False

_file_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}


class MembershipError(Exception):
    """Base class for membership.py failures."""


class MalformedFileError(MembershipError):
    """Raised when whitelist.json or ops.json doesn't parse as a list of objects."""


class StaleWriteError(MembershipError):
    """File on disk changed since the caller's read. operator should retry."""


def whitelist_path(server_dir: Path) -> Path:
    return Path(server_dir) / "server" / "whitelist.json"


def ops_path(server_dir: Path) -> Path:
    return Path(server_dir) / "server" / "ops.json"


def _read(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Returns ``(entries, mtime_ns)``. Missing file → ``([], 0)``."""
    try:
        st = path.stat()
    except FileNotFoundError:
        return [], 0
    cache_key = (str(path), st.st_mtime_ns)
    if cache_key in _file_cache:
        return _file_cache[cache_key], st.st_mtime_ns
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError as exc:
        raise MalformedFileError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise MalformedFileError(f"{path} is not a list of objects")
    _file_cache[cache_key] = data
    return data, st.st_mtime_ns


def _write(
    path: Path, entries: list[dict[str, Any]], expected_mtime_ns: int
) -> int:
    """Atomic write with mtime guard. Returns the new mtime_ns."""
    try:
        current_mtime_ns = path.stat().st_mtime_ns
    except FileNotFoundError:
        current_mtime_ns = 0
    if current_mtime_ns != expected_mtime_ns:
        raise StaleWriteError(
            f"{path} changed since read (expected mtime_ns={expected_mtime_ns}, "
            f"current={current_mtime_ns}); retry"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(entries, indent=2) + "\n"
    atomic_write_text(path, content)
    return path.stat().st_mtime_ns


# --- Whitelist ----------------------------------------------------------------


def read_whitelist(server_dir: Path) -> tuple[list[dict[str, Any]], int]:
    return _read(whitelist_path(server_dir))


def write_whitelist(
    server_dir: Path, entries: list[dict[str, Any]], expected_mtime_ns: int
) -> int:
    return _write(whitelist_path(server_dir), entries, expected_mtime_ns)


def add_whitelist_entry(server_dir: Path, *, uuid: str, name: str) -> bool:
    """Read, append ``{"uuid", "name"}`` if uuid not already present, write.

    Returns True if a write occurred, False if the uuid was already on
    the list (no-op). Raises :class:`StaleWriteError` if the file
    changed between read and write."""
    entries, mtime_ns = read_whitelist(server_dir)
    if any(e.get("uuid") == uuid for e in entries):
        return False
    entries.append({"uuid": uuid, "name": name})
    write_whitelist(server_dir, entries, mtime_ns)
    return True


def remove_whitelist_entry(server_dir: Path, *, uuid: str) -> bool:
    """Read, drop entries matching ``uuid``, write. Returns True if a
    write occurred, False if the uuid wasn't on the list."""
    entries, mtime_ns = read_whitelist(server_dir)
    new_entries = [e for e in entries if e.get("uuid") != uuid]
    if len(new_entries) == len(entries):
        return False
    write_whitelist(server_dir, new_entries, mtime_ns)
    return True


# --- Ops ----------------------------------------------------------------------


def read_ops(server_dir: Path) -> tuple[list[dict[str, Any]], int]:
    return _read(ops_path(server_dir))


def write_ops(
    server_dir: Path, entries: list[dict[str, Any]], expected_mtime_ns: int
) -> int:
    return _write(ops_path(server_dir), entries, expected_mtime_ns)


def add_op_entry(server_dir: Path, *, uuid: str, name: str) -> bool:
    """Read, append a vanilla-default op entry if uuid not present, write.

    New entries are written as ``{"uuid", "name", "level": 4,
    "bypassesPlayerLimit": false}``. there is no level
    dropdown in the UI. Existing entries with non-default levels are
    preserved on round-trip because we never rewrite their fields."""
    entries, mtime_ns = read_ops(server_dir)
    if any(e.get("uuid") == uuid for e in entries):
        return False
    entries.append(
        {
            "uuid": uuid,
            "name": name,
            "level": _OP_DEFAULT_LEVEL,
            "bypassesPlayerLimit": _OP_DEFAULT_BYPASSES,
        }
    )
    write_ops(server_dir, entries, mtime_ns)
    return True


def remove_op_entry(server_dir: Path, *, uuid: str) -> bool:
    """Read, drop entries matching ``uuid``, write. Returns True if a
    write occurred, False if the uuid wasn't on the list."""
    entries, mtime_ns = read_ops(server_dir)
    new_entries = [e for e in entries if e.get("uuid") != uuid]
    if len(new_entries) == len(entries):
        return False
    write_ops(server_dir, new_entries, mtime_ns)
    return True


# --- Cross-server scan --------------------------------------------------------


def scan_memberships(servers: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Walk every server's ``whitelist.json`` and ``ops.json``.

    Returns a flat list of records, each ``{server_name, kind, uuid,
    name}``. ``kind`` is ``"whitelist"`` or ``"ops"``. Order:
    server-by-server in the input order; for each server, whitelist
    entries first, then ops entries; within each kind, file insertion
    order.

    Used by:
      - PR 3 Import. walks every file, upserts unknown UUIDs into
        ``app_mcontrol.players``.
      - PR 3 central Players page. per-row "Whitelisted on / Op on"
        summary.
      - PR 4 cascade-remove pre-scan. which servers does this UUID
        appear on?

    Missing files are treated as empty. Malformed files are skipped
    silently. the per-server health banner (PR 2) is the surface for
    that failure mode."""
    out: list[dict[str, str]] = []
    for server in servers:
        server_dir = Path(server["dir"])
        for kind, reader in (
            ("whitelist", read_whitelist),
            ("ops", read_ops),
        ):
            try:
                entries, _ = reader(server_dir)
            except MalformedFileError:
                continue
            for entry in entries:
                uuid = entry.get("uuid")
                name = entry.get("name")
                if not uuid or not name:
                    continue
                out.append(
                    {
                        "server_name": server["name"],
                        "kind": kind,
                        "uuid": uuid,
                        "name": name,
                    }
                )
    return out
