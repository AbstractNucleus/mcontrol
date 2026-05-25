"""Package-internal helpers shared across the files routes.

Directory listing + parent-listing computation, plus the view-size
constants. The path-safety primitives themselves live in
`mcontrol.file_safety` (reused across other route modules); this file
just bundles the listing-shape helpers that only the files routes need.
"""

import stat
from pathlib import Path

from mcontrol import file_safety

# Caps applied by the view endpoint. The save endpoint reads these via
# `view.py` rather than this module since save's mtime/conflict path
# does not consult them directly.
_TEXT_VIEW_BYTES_MAX = 5 * 1024 * 1024
_BINARY_SNIFF_BYTES = 8 * 1024


def _list_dir(target: Path, base: Path) -> list[dict]:
    entries: list[dict] = []
    for child in target.iterdir():
        try:
            st = child.lstat()
        except OSError:
            continue
        if file_safety.is_special(st.st_mode):
            continue
        rel = child.relative_to(base).as_posix()
        if child.is_symlink():
            kind = "symlink"
        elif stat.S_ISDIR(st.st_mode):
            kind = "dir"
        else:
            kind = "file"
        entries.append({"name": child.name, "path": rel, "kind": kind})
    entries.sort(key=lambda e: (0 if e["kind"] == "dir" else 1, e["name"].lower()))
    return entries


def _parent_listing(server_dir: str, target: Path) -> tuple[Path, list[dict]]:
    """Return (parent_dir, listing) for use as the action response.

    Delete and mkdir both refresh the parent of their target. the JS
    swaps that listing into the closest matching `<ul.file-tree__children>`.
    """
    base = Path(server_dir).resolve()
    parent = target.parent if target != base else base
    return parent, _list_dir(parent, base)
