import os
import sys
from pathlib import Path

import pytest

# ---- /files/upload -----------------------------------------------------

async def test_upload_writes_single_file_to_root(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": ""},
        files=[("files", ("note.txt", b"hello world"))],
    )

    assert response.status_code == 200
    target = server_dir / "note.txt"
    assert target.exists()
    assert target.read_bytes() == b"hello world"
    # Response is the re-rendered tree listing.
    assert "note.txt" in response.text


async def test_upload_writes_multiple_files(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": ""},
        files=[
            ("files", ("a.txt", b"alpha")),
            ("files", ("b.txt", b"beta")),
            ("files", ("c.bin", b"\x00\x01\x02")),
        ],
    )

    assert response.status_code == 200
    assert (server_dir / "a.txt").read_bytes() == b"alpha"
    assert (server_dir / "b.txt").read_bytes() == b"beta"
    assert (server_dir / "c.bin").read_bytes() == b"\x00\x01\x02"


async def test_upload_writes_into_subdirectory(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "mods").mkdir()

    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": "mods"},
        files=[("files", ("foo.jar", b"PK\x03\x04fake-jar"))],
    )

    assert response.status_code == 200
    assert (server_dir / "mods" / "foo.jar").read_bytes() == b"PK\x03\x04fake-jar"


async def test_upload_conflict_returns_409_and_writes_nothing(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "existing.txt").write_text("original\n", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": ""},
        files=[
            ("files", ("existing.txt", b"new-content")),
            ("files", ("brand-new.txt", b"second")),
        ],
    )

    assert response.status_code == 409
    body = response.text
    assert "file-upload-conflict" in body
    assert "existing.txt" in body
    assert "Overwrite" in body
    assert "Cancel" in body
    # Refuse-on-conflict: neither file written.
    assert (server_dir / "existing.txt").read_text(encoding="utf-8") == "original\n"
    assert not (server_dir / "brand-new.txt").exists()


async def test_upload_force_overwrites_existing(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "existing.txt").write_text("original\n", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": "", "force": "true"},
        files=[("files", ("existing.txt", b"replaced"))],
    )

    assert response.status_code == 200
    assert (server_dir / "existing.txt").read_bytes() == b"replaced"


async def test_upload_rejects_filename_with_slash(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": ""},
        files=[("files", ("../escape.txt", b"x"))],
    )

    assert response.status_code == 400
    # No file written anywhere under the server dir.
    assert list(server_dir.iterdir()) == []


async def test_upload_rejects_filename_with_backslash(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": ""},
        files=[("files", ("a\\b.txt", b"x"))],
    )

    assert response.status_code == 400


async def test_upload_rejects_dot_filename(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": ""},
        files=[("files", (".", b"x"))],
    )

    assert response.status_code == 400


async def test_upload_rejects_empty_filename(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": ""},
        files=[("files", ("", b"x"))],
    )

    # Starlette's multipart parser refuses an empty filename header with
    # 422 before our validator runs; the validator itself would 400 if it
    # ever did. Either way: refused, no file on disk.
    assert response.status_code in (400, 422)
    assert list(server_dir.iterdir()) == []


async def test_upload_rejects_path_traversal(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": "../escape"},
        files=[("files", ("ok.txt", b"x"))],
    )

    assert response.status_code == 400


async def test_upload_404_when_target_dir_missing(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": "no-such-dir"},
        files=[("files", ("x.txt", b"x"))],
    )

    assert response.status_code == 404


async def test_upload_400_when_target_is_a_file(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "f.txt").write_text("hi", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": "f.txt"},
        files=[("files", ("x.txt", b"x"))],
    )

    assert response.status_code == 400


async def test_upload_refuses_to_clobber_existing_directory(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "config").mkdir()

    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": "", "force": "true"},
        files=[("files", ("config", b"would-replace-dir"))],
    )

    assert response.status_code == 400
    # Directory still there.
    assert (server_dir / "config").is_dir()


@pytest.mark.skipif(sys.platform == "win32", reason="FIFOs are POSIX-only")
async def test_upload_refuses_to_clobber_special_file(
    client, fake_server, server_dir: Path
) -> None:
    os.mkfifo(server_dir / "myfifo")

    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": "", "force": "true"},
        files=[("files", ("myfifo", b"data"))],
    )

    assert response.status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_upload_force_replaces_symlink_without_following(
    client, fake_server, server_dir: Path, tmp_path: Path
) -> None:
    """A symlink at the target is treated as a conflict; force replaces
    the symlink itself (not its target), matching the slice's never-follow
    contract."""
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched", encoding="utf-8")
    (server_dir / "link.txt").symlink_to(outside)

    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": "", "force": "true"},
        files=[("files", ("link.txt", b"replacement"))],
    )

    assert response.status_code == 200
    # The symlink target is unchanged. we replaced the link entry, not
    # wrote through it.
    assert outside.read_text(encoding="utf-8") == "untouched"
    # The server-dir entry is now a regular file with the new bytes.
    new_target = server_dir / "link.txt"
    assert not new_target.is_symlink()
    assert new_target.read_bytes() == b"replacement"


async def test_upload_is_atomic_no_leftover_tempfile(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": ""},
        files=[("files", ("x.txt", b"hi"))],
    )

    assert response.status_code == 200
    # No leftover sibling `.x.txt.<rand>` tempfile.
    siblings = sorted(p.name for p in server_dir.iterdir())
    assert siblings == ["x.txt"]


async def test_upload_conflict_lists_only_conflicting_files(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("old", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/upload",
        data={"path": ""},
        files=[
            ("files", ("a.txt", b"new")),
            ("files", ("b.txt", b"new")),
            ("files", ("c.txt", b"new")),
        ],
    )

    assert response.status_code == 409
    body = response.text
    assert "a.txt" in body
    # Non-conflicting filenames must not be advertised in the modal.
    assert "b.txt" not in body
    assert "c.txt" not in body
