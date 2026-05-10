"""Tombstone listing + purge (slice 11, decision 030).

Closes the "Empty trash" affordance that decision 026 named in its
trade-off line. The producer side is ``routes/delete_server.py``: a
deleted server's directory is renamed to ``<base>/.deleted-<name>-<ts>/``
and the row is removed. This module is the missing purge half — it
parses those directory names back into structured records and removes
them from disk.

Read side reuses ``resources.read_disk_usage`` for the bytes column —
the walk is the same primitive, already path-safe with
``follow_symlinks=False``.

Path-safety: the regex gate + parent-equality check in ``purge_one``
ensures we only ever ``shutil.rmtree`` directories whose name matches
the tombstone shape and whose resolved parent is exactly ``base``.
URL-decoded payloads like ``..`` / ``../foo`` / ``foo/bar`` fail the
regex and never reach the filesystem.
"""

import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from mcontrol.resources import read_disk_usage

_DEFAULT_PURGE_AGE_DAYS = 7

# Mirrors the slug shape from routes/new_server.py (`_NAME_RE`). Greedy
# backtrack on the slug + the trailing `-\d+$` anchor pins the unix-ts
# to the rightmost `-<digits>` run, so a slug-with-hyphens parses
# correctly (e.g. `.deleted-kobra-2022-1700000000` → name=`kobra-2022`,
# ts=`1700000000`).
_TOMB_RE = re.compile(r"^\.deleted-(?P<name>[a-z][a-z0-9-]{2,31})-(?P<ts>\d+)$")


@dataclass(frozen=True)
class Tombstone:
    dir_name: str
    original_name: str
    deleted_at_unix: int
    age_seconds: int
    bytes: int


def _parse(dir_name: str) -> tuple[str, int] | None:
    m = _TOMB_RE.fullmatch(dir_name)
    if m is None:
        return None
    return m.group("name"), int(m.group("ts"))


def list_tombstones(base: Path) -> list[Tombstone]:
    """Scan ``base`` for ``.deleted-<name>-<ts>/`` directories and return
    a list of ``Tombstone`` records, oldest first.

    Malformed dot-dirs (``.git``, ``.lost+found``, ``.deleted-foo``
    without the trailing ``-<unix-ts>``) are silently skipped — this
    list is "tombstones I produced," not "every dot-dir under ``<base>``."
    Symlinks with tombstone-shaped names are skipped to avoid following
    them on the bytes-read or on later purge.

    Returns ``[]`` when ``base`` doesn't exist.
    """
    base = Path(base).resolve()
    if not base.exists():
        return []

    now = int(time.time())
    out: list[Tombstone] = []
    with os.scandir(base) as it:
        for entry in it:
            if entry.is_symlink():
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
            parsed = _parse(entry.name)
            if parsed is None:
                continue
            original_name, deleted_at_unix = parsed
            tomb_path = Path(entry.path)
            out.append(
                Tombstone(
                    dir_name=entry.name,
                    original_name=original_name,
                    deleted_at_unix=deleted_at_unix,
                    age_seconds=max(0, now - deleted_at_unix),
                    bytes=read_disk_usage(tomb_path),
                )
            )
    out.sort(key=lambda t: t.deleted_at_unix)
    return out


def purge_one(base: Path, dir_name: str) -> None:
    """Remove a single tombstone directory from disk.

    Path-safety:
      1. ``dir_name`` must fullmatch ``_TOMB_RE``. URL-decoded payloads
         like ``..`` / ``../foo`` / ``foo/bar`` / ``foo%00bar`` fail
         the regex (hyphen + dot + slash + null are all outside
         ``[a-z0-9-]``) and never reach the filesystem.
      2. ``target.parent`` must equal ``base.resolve()``. Defends
         against the theoretical "regex passed but ``Path`` resolution
         still landed us elsewhere" case.
      3. ``target`` must be a real directory, not a symlink.
    """
    if _parse(dir_name) is None:
        raise ValueError(f"not a tombstone name: {dir_name!r}")

    base = Path(base).resolve()
    target = (base / dir_name).resolve()
    if target.parent != base:
        raise ValueError(f"tombstone resolves outside base: {dir_name!r}")
    if target.is_symlink() or not target.is_dir():
        raise ValueError(f"tombstone is not a directory: {dir_name!r}")

    shutil.rmtree(target)


def purge_older_than(
    base: Path, days: int = _DEFAULT_PURGE_AGE_DAYS
) -> list[Tombstone]:
    """Purge every tombstone older than ``days`` days. Returns the list
    of tombstones that were purged (in the order they were removed).

    Best-effort: a failure on one tombstone is recorded as the loop
    moving past it; the remaining sweep continues. The returned list
    contains only the tombstones whose ``rmtree`` completed cleanly.
    """
    cutoff_seconds = days * 86400
    purged: list[Tombstone] = []
    for t in list_tombstones(base):
        if t.age_seconds < cutoff_seconds:
            continue
        try:
            purge_one(base, t.dir_name)
        except (OSError, ValueError):
            continue
        purged.append(t)
    return purged
