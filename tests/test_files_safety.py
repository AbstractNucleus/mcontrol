import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from mcontrol.infra.file_safety import resolve_within

# ---- _resolve_within unit tests ---------------------------------------

def test_resolve_within_root(server_dir: Path) -> None:
    assert resolve_within(str(server_dir), "") == server_dir.resolve()


def test_resolve_within_subpath(server_dir: Path) -> None:
    (server_dir / "a").mkdir()
    assert resolve_within(str(server_dir), "a") == (server_dir / "a").resolve()


def test_resolve_within_rejects_dotdot(server_dir: Path) -> None:
    with pytest.raises(HTTPException) as ei:
        resolve_within(str(server_dir), "../etc")
    assert ei.value.status_code == 400


def test_resolve_within_rejects_absolute_traversal(server_dir: Path) -> None:
    with pytest.raises(HTTPException) as ei:
        resolve_within(str(server_dir), "/../etc/passwd")
    assert ei.value.status_code == 400


def test_resolve_within_rejects_null_byte(server_dir: Path) -> None:
    with pytest.raises(HTTPException) as ei:
        resolve_within(str(server_dir), "foo\x00bar")
    assert ei.value.status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_resolve_within_rejects_symlink_component(server_dir: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (server_dir / "linked").symlink_to(outside)
    with pytest.raises(HTTPException) as ei:
        resolve_within(str(server_dir), "linked/anything")
    assert ei.value.status_code == 400
