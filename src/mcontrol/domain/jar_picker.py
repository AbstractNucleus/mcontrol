"""Discover runnable jar choices from a server's container working directory."""

from pathlib import Path


def existing_jars(server_dir: Path, server_base_path: Path) -> tuple[str, ...]:
    """Return safe jar filenames from ``<bound server dir>/server``.

    The generated container starts in that directory. Only direct, regular files
    are choices: library and mod jars below subdirectories are not server entry
    points, and symlinks are excluded even when they resolve back inside it.
    """
    try:
        base = server_base_path.resolve()
        bound_dir = server_dir.resolve()
    except (OSError, RuntimeError):
        return ()
    try:
        bound_dir.relative_to(base)
    except ValueError:
        return ()

    working_dir = bound_dir / "server"
    try:
        resolved_working_dir = working_dir.resolve(strict=True)
    except (OSError, RuntimeError):
        return ()
    if working_dir.is_symlink() or resolved_working_dir != working_dir:
        return ()
    if not working_dir.is_dir():
        return ()

    try:
        jars = []
        for entry in working_dir.iterdir():
            if entry.suffix.lower() != ".jar" or entry.is_symlink():
                continue
            resolved_entry = entry.resolve(strict=True)
            if resolved_entry.parent == resolved_working_dir and entry.is_file():
                jars.append(entry.name)
    except (OSError, RuntimeError):
        return ()
    return tuple(sorted(jars, key=lambda name: (name.casefold(), name)))
