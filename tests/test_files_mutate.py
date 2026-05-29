import os
import sys
from pathlib import Path

import pytest

# ---- /files/delete -----------------------------------------------------

async def test_delete_removes_a_regular_file(
    client, fake_server, server_dir: Path
) -> None:
    target = server_dir / "doomed.txt"
    target.write_text("bye", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/delete",
        data={"path": "doomed.txt"},
    )

    assert response.status_code == 200
    assert not target.exists()


async def test_delete_returns_parent_listing(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "stay.txt").write_text("ok", encoding="utf-8")
    (server_dir / "go.txt").write_text("bye", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/delete",
        data={"path": "go.txt"},
    )

    assert response.status_code == 200
    body = response.text
    assert "stay.txt" in body
    assert "go.txt" not in body


async def test_delete_directory_requires_confirm_name(
    client, fake_server, server_dir: Path
) -> None:
    d = server_dir / "config"
    d.mkdir()
    (d / "inside.txt").write_text("x", encoding="utf-8")

    # No confirm_name → 400, dir untouched.
    response = await client.post(
        "/servers/atm10/files/delete",
        data={"path": "config"},
    )
    assert response.status_code == 400
    assert d.is_dir()
    assert (d / "inside.txt").exists()


async def test_delete_directory_with_wrong_confirm_name(
    client, fake_server, server_dir: Path
) -> None:
    d = server_dir / "config"
    d.mkdir()

    response = await client.post(
        "/servers/atm10/files/delete",
        data={"path": "config", "confirm_name": "configg"},
    )
    assert response.status_code == 400
    assert d.is_dir()


async def test_delete_directory_recursive_with_matching_confirm_name(
    client, fake_server, server_dir: Path
) -> None:
    d = server_dir / "config"
    (d / "nested").mkdir(parents=True)
    (d / "a.txt").write_text("a", encoding="utf-8")
    (d / "nested" / "b.txt").write_text("b", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/delete",
        data={"path": "config", "confirm_name": "config"},
    )

    assert response.status_code == 200
    assert not d.exists()


async def test_delete_refuses_root(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "marker.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/delete",
        data={"path": "", "confirm_name": Path(server_dir).name},
    )
    assert response.status_code == 400
    # Server-dir root + its marker file are still on disk.
    assert server_dir.exists()
    assert (server_dir / "marker.txt").exists()


async def test_delete_404_on_missing(client, fake_server) -> None:
    response = await client.post(
        "/servers/atm10/files/delete",
        data={"path": "no-such.txt"},
    )
    assert response.status_code == 404


async def test_delete_400_on_traversal(client, fake_server) -> None:
    response = await client.post(
        "/servers/atm10/files/delete",
        data={"path": "../etc/passwd"},
    )
    assert response.status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_delete_symlink_unlinks_link_not_target(
    client, fake_server, server_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched", encoding="utf-8")
    link = server_dir / "link.txt"
    link.symlink_to(outside)

    response = await client.post(
        "/servers/atm10/files/delete",
        data={"path": "link.txt"},
    )

    assert response.status_code == 200
    assert not link.exists() and not link.is_symlink()
    # The original file is untouched. we never followed the link.
    assert outside.read_text(encoding="utf-8") == "untouched"


@pytest.mark.skipif(sys.platform == "win32", reason="FIFOs are POSIX-only")
async def test_delete_refuses_special_file(
    client, fake_server, server_dir: Path
) -> None:
    fifo = server_dir / "myfifo"
    os.mkfifo(fifo)

    response = await client.post(
        "/servers/atm10/files/delete",
        data={"path": "myfifo"},
    )
    assert response.status_code == 400
    assert fifo.exists()


# ---- /files/mkdir ------------------------------------------------------

async def test_mkdir_creates_directory_at_root(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/mkdir",
        data={"path": "", "dirname": "newdir"},
    )

    assert response.status_code == 200
    assert (server_dir / "newdir").is_dir()
    # Response is the parent (root) listing including the new entry.
    assert "newdir" in response.text


async def test_mkdir_creates_directory_in_subpath(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "mods").mkdir()

    response = await client.post(
        "/servers/atm10/files/mkdir",
        data={"path": "mods", "dirname": "client"},
    )

    assert response.status_code == 200
    assert (server_dir / "mods" / "client").is_dir()


async def test_mkdir_409_when_name_already_exists_as_file(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "collision").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/mkdir",
        data={"path": "", "dirname": "collision"},
    )
    assert response.status_code == 409
    assert (server_dir / "collision").is_file()


async def test_mkdir_409_when_name_already_exists_as_dir(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "collision").mkdir()

    response = await client.post(
        "/servers/atm10/files/mkdir",
        data={"path": "", "dirname": "collision"},
    )
    assert response.status_code == 409


async def test_mkdir_404_when_parent_missing(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/mkdir",
        data={"path": "no-such-parent", "dirname": "x"},
    )
    assert response.status_code == 404


async def test_mkdir_400_when_parent_is_a_file(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "f.txt").write_text("hi", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/mkdir",
        data={"path": "f.txt", "dirname": "x"},
    )
    assert response.status_code == 400


async def test_mkdir_rejects_traversal_in_dirname(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/mkdir",
        data={"path": "", "dirname": "../escape"},
    )
    assert response.status_code == 400
    # No directory created.
    assert list(server_dir.iterdir()) == []


async def test_mkdir_rejects_dot_dirname(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/mkdir",
        data={"path": "", "dirname": "."},
    )
    assert response.status_code == 400


async def test_mkdir_rejects_traversal_in_path(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/mkdir",
        data={"path": "../etc", "dirname": "x"},
    )
    assert response.status_code == 400


# ---- /files/rename -----------------------------------------------------

async def test_rename_renames_a_file(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "old.txt").write_text("hi", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/rename",
        data={"path": "old.txt", "new_name": "new.txt"},
    )

    assert response.status_code == 200
    assert not (server_dir / "old.txt").exists()
    assert (server_dir / "new.txt").read_text(encoding="utf-8") == "hi"
    body = response.text
    assert "new.txt" in body
    assert "old.txt" not in body


async def test_rename_renames_a_directory(
    client, fake_server, server_dir: Path
) -> None:
    d = server_dir / "old"
    d.mkdir()
    (d / "inside.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/rename",
        data={"path": "old", "new_name": "new"},
    )

    assert response.status_code == 200
    assert not d.exists()
    assert (server_dir / "new" / "inside.txt").read_text(encoding="utf-8") == "x"


async def test_rename_409_on_collision(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "src.txt").write_text("a", encoding="utf-8")
    (server_dir / "dest.txt").write_text("b", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/rename",
        data={"path": "src.txt", "new_name": "dest.txt"},
    )
    assert response.status_code == 409
    # Neither file mutated.
    assert (server_dir / "src.txt").read_text(encoding="utf-8") == "a"
    assert (server_dir / "dest.txt").read_text(encoding="utf-8") == "b"


async def test_rename_400_refuses_root(
    client, fake_server, server_dir: Path
) -> None:
    response = await client.post(
        "/servers/atm10/files/rename",
        data={"path": "", "new_name": "irrelevant"},
    )
    assert response.status_code == 400


async def test_rename_404_on_missing(client, fake_server) -> None:
    response = await client.post(
        "/servers/atm10/files/rename",
        data={"path": "no-such.txt", "new_name": "x.txt"},
    )
    assert response.status_code == 404


async def test_rename_400_on_traversal_in_path(client, fake_server) -> None:
    response = await client.post(
        "/servers/atm10/files/rename",
        data={"path": "../etc/passwd", "new_name": "x"},
    )
    assert response.status_code == 400


async def test_rename_rejects_invalid_new_name(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "ok.txt").write_text("x", encoding="utf-8")

    for bad in ["../escape", "with/slash", "with\\backslash", "..", "."]:
        response = await client.post(
            "/servers/atm10/files/rename",
            data={"path": "ok.txt", "new_name": bad},
        )
        assert response.status_code == 400, f"expected 400 for new_name={bad!r}"
    # File unchanged across all bad attempts.
    assert (server_dir / "ok.txt").read_text(encoding="utf-8") == "x"


async def test_rename_no_op_keeps_file(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "same.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/rename",
        data={"path": "same.txt", "new_name": "same.txt"},
    )
    assert response.status_code == 200
    assert (server_dir / "same.txt").read_text(encoding="utf-8") == "x"


# ---- /files/move ------------------------------------------------------

async def test_move_relocates_a_file(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "f.txt").write_text("x", encoding="utf-8")
    (server_dir / "subdir").mkdir()

    response = await client.post(
        "/servers/atm10/files/move",
        data={"source": "f.txt", "dest_dir": "subdir"},
    )

    assert response.status_code == 200
    assert not (server_dir / "f.txt").exists()
    assert (server_dir / "subdir" / "f.txt").read_text(encoding="utf-8") == "x"


async def test_move_relocates_a_directory(
    client, fake_server, server_dir: Path
) -> None:
    src = server_dir / "from"
    src.mkdir()
    (src / "leaf.txt").write_text("x", encoding="utf-8")
    (server_dir / "to").mkdir()

    response = await client.post(
        "/servers/atm10/files/move",
        data={"source": "from", "dest_dir": "to"},
    )

    assert response.status_code == 200
    assert not src.exists()
    assert (server_dir / "to" / "from" / "leaf.txt").read_text(encoding="utf-8") == "x"


async def test_move_response_is_source_parent_listing(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "moved.txt").write_text("x", encoding="utf-8")
    (server_dir / "stayer.txt").write_text("y", encoding="utf-8")
    (server_dir / "elsewhere").mkdir()

    response = await client.post(
        "/servers/atm10/files/move",
        data={"source": "moved.txt", "dest_dir": "elsewhere"},
    )

    assert response.status_code == 200
    body = response.text
    # Source's parent (root) is what JS swaps in. moved.txt must be gone
    # from it, stayer.txt must still appear.
    assert "stayer.txt" in body
    assert "moved.txt" not in body


async def test_move_409_on_destination_collision(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "f.txt").write_text("source", encoding="utf-8")
    (server_dir / "dst").mkdir()
    (server_dir / "dst" / "f.txt").write_text("victim", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/move",
        data={"source": "f.txt", "dest_dir": "dst"},
    )

    assert response.status_code == 409
    # Neither side mutated.
    assert (server_dir / "f.txt").read_text(encoding="utf-8") == "source"
    assert (server_dir / "dst" / "f.txt").read_text(encoding="utf-8") == "victim"


async def test_move_400_refuses_root_source(client, fake_server) -> None:
    response = await client.post(
        "/servers/atm10/files/move",
        data={"source": "", "dest_dir": "anywhere"},
    )
    assert response.status_code == 400


async def test_move_400_refuses_no_op(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "f.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/move",
        data={"source": "f.txt", "dest_dir": ""},
    )
    assert response.status_code == 400
    # File still in place.
    assert (server_dir / "f.txt").read_text(encoding="utf-8") == "x"


async def test_move_400_refuses_into_descendant(
    client, fake_server, server_dir: Path
) -> None:
    parent = server_dir / "parent"
    (parent / "child").mkdir(parents=True)

    response = await client.post(
        "/servers/atm10/files/move",
        data={"source": "parent", "dest_dir": "parent/child"},
    )
    assert response.status_code == 400
    # Source still in place.
    assert (parent / "child").is_dir()


async def test_move_404_on_missing_source(client, fake_server) -> None:
    response = await client.post(
        "/servers/atm10/files/move",
        data={"source": "no-such.txt", "dest_dir": ""},
    )
    assert response.status_code == 404


async def test_move_404_on_missing_destination(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "f.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/move",
        data={"source": "f.txt", "dest_dir": "no-such-dir"},
    )
    assert response.status_code == 404


async def test_move_400_when_destination_is_a_file(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "f.txt").write_text("x", encoding="utf-8")
    (server_dir / "g.txt").write_text("y", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/move",
        data={"source": "f.txt", "dest_dir": "g.txt"},
    )
    assert response.status_code == 400


async def test_move_400_on_traversal(client, fake_server) -> None:
    response = await client.post(
        "/servers/atm10/files/move",
        data={"source": "../etc/passwd", "dest_dir": ""},
    )
    assert response.status_code == 400
