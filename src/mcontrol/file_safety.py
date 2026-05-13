"""Path-safety helpers shared across filesystem-touching routes."""

import stat
from pathlib import Path

from fastapi import HTTPException


def is_special(mode: int) -> bool:
    return (
        stat.S_ISBLK(mode)
        or stat.S_ISCHR(mode)
        or stat.S_ISFIFO(mode)
        or stat.S_ISSOCK(mode)
    )


def resolve_within(base_dir: str, operator_path: str) -> Path:
    """Resolve operator_path under base_dir per the path-safety contract.

    Returns an absolute path that is guaranteed to live inside the
    resolved base_dir, with no symlink in any intermediate component.
    The returned path may not exist — callers handle 404 themselves.
    """
    base = Path(base_dir).resolve()
    cleaned = operator_path.replace("\\", "/").lstrip("/")
    if "\x00" in cleaned:
        raise HTTPException(status_code=400, detail="invalid path")
    parts = [p for p in cleaned.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        raise HTTPException(status_code=400, detail="path traversal not allowed")

    current = base
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise HTTPException(status_code=400, detail="symlinks are not followed")

    try:
        current.resolve(strict=False).relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="path outside server dir") from None
    return current


def validate_upload_filename(name: str) -> None:
    """Refuse any filename component the operator could weaponize.

    Multipart filenames are attacker-controlled and naive concatenation
    would let `foo/../../etc/passwd` escape the target dir. We forbid
    path separators, dot segments, empties and NULs before going near
    disk.
    """
    if not name:
        raise HTTPException(status_code=400, detail="empty filename")
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail=f"invalid filename: {name!r}")
    if name in (".", ".."):
        raise HTTPException(status_code=400, detail=f"invalid filename: {name!r}")
    if "\x00" in name:
        raise HTTPException(status_code=400, detail="invalid filename")


def stat_regular_file(target: Path) -> "stat.os.stat_result":
    """Return lstat() of `target`, refusing symlinks/special/dirs.

    Caller must already have run `resolve_within`. Raises 404 if the
    file vanished and 400 for symlink / special / directory.
    """
    try:
        st = target.lstat()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    if stat.S_ISLNK(st.st_mode):
        raise HTTPException(status_code=400, detail="symlinks are not followed")
    if is_special(st.st_mode):
        raise HTTPException(status_code=400, detail="not a regular file")
    if stat.S_ISDIR(st.st_mode):
        raise HTTPException(status_code=400, detail="not a file")
    return st
