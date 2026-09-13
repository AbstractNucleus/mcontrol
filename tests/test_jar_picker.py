from pathlib import Path

import pytest

from mcontrol.domain.jar_picker import existing_jars


def test_existing_jars_lists_only_direct_regular_jar_files(tmp_path: Path) -> None:
    working_dir = tmp_path / "server"
    working_dir.mkdir()
    (working_dir / "zeta.jar").write_bytes(b"jar")
    (working_dir / "Alpha.JAR").write_bytes(b"jar")
    (working_dir / "readme.txt").write_text("not a jar", encoding="utf-8")
    mods = working_dir / "mods"
    mods.mkdir()
    (mods / "mod.jar").write_bytes(b"jar")

    assert existing_jars(tmp_path, tmp_path) == ("Alpha.JAR", "zeta.jar")


def test_existing_jars_uses_server_working_dir_and_handles_missing_dir(
    tmp_path: Path,
) -> None:
    (tmp_path / "wrong-place.jar").write_bytes(b"jar")

    assert existing_jars(tmp_path, tmp_path) == ()


def test_existing_jars_excludes_symlink_entries(
    tmp_path: Path, monkeypatch
) -> None:
    working_dir = tmp_path / "server"
    working_dir.mkdir()
    linked = working_dir / "linked.jar"
    linked.write_bytes(b"jar")
    original = Path.is_symlink

    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == linked or original(path),
    )

    assert existing_jars(tmp_path, tmp_path) == ()


def test_existing_jars_rejects_bound_directory_outside_configured_base(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside"
    working_dir = outside / "server"
    working_dir.mkdir(parents=True)
    (working_dir / "outside.jar").write_bytes(b"jar")

    assert existing_jars(outside, base) == ()


def test_existing_jars_rejects_redirected_working_directory(
    tmp_path: Path, monkeypatch
) -> None:
    bound_dir = tmp_path / "bound"
    working_dir = bound_dir / "server"
    working_dir.mkdir(parents=True)
    (working_dir / "paper.jar").write_bytes(b"jar")
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    original = Path.resolve

    def fake_resolve(path: Path, *args, **kwargs) -> Path:
        if path == working_dir:
            return redirected
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    assert existing_jars(bound_dir, tmp_path) == ()


def test_existing_jars_rejects_real_symlinked_working_directory(
    tmp_path: Path,
) -> None:
    bound_dir = tmp_path / "bound"
    bound_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "outside.jar").write_bytes(b"jar")
    try:
        (bound_dir / "server").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("creating directory symlinks is not permitted on this host")

    assert existing_jars(bound_dir, tmp_path) == ()


def test_existing_jars_rejects_real_symlinked_jar(tmp_path: Path) -> None:
    working_dir = tmp_path / "bound" / "server"
    working_dir.mkdir(parents=True)
    outside = tmp_path / "outside.jar"
    outside.write_bytes(b"jar")
    try:
        (working_dir / "linked.jar").symlink_to(outside)
    except OSError:
        pytest.skip("creating file symlinks is not permitted on this host")

    assert existing_jars(tmp_path / "bound", tmp_path) == ()
