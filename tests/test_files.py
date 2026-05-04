import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from mcontrol.routes.files import _resolve_within


@pytest.fixture
def server_dir(tmp_path: Path) -> Path:
    d = tmp_path / "srv"
    d.mkdir()
    return d


@pytest.fixture
def fake_server(monkeypatch, server_dir: Path):
    rows: dict[str, dict] = {
        "atm10": {"name": "atm10", "dir": str(server_dir)}
    }
    from mcontrol import db
    monkeypatch.setattr(db, "get_server", rows.get)
    return rows


# ---- _resolve_within unit tests ---------------------------------------

def test_resolve_within_root(server_dir: Path) -> None:
    assert _resolve_within(str(server_dir), "") == server_dir.resolve()


def test_resolve_within_subpath(server_dir: Path) -> None:
    (server_dir / "a").mkdir()
    assert _resolve_within(str(server_dir), "a") == (server_dir / "a").resolve()


def test_resolve_within_rejects_dotdot(server_dir: Path) -> None:
    with pytest.raises(HTTPException) as ei:
        _resolve_within(str(server_dir), "../etc")
    assert ei.value.status_code == 400


def test_resolve_within_rejects_absolute_traversal(server_dir: Path) -> None:
    with pytest.raises(HTTPException) as ei:
        _resolve_within(str(server_dir), "/../etc/passwd")
    assert ei.value.status_code == 400


def test_resolve_within_rejects_null_byte(server_dir: Path) -> None:
    with pytest.raises(HTTPException) as ei:
        _resolve_within(str(server_dir), "foo\x00bar")
    assert ei.value.status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_resolve_within_rejects_symlink_component(server_dir: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (server_dir / "linked").symlink_to(outside)
    with pytest.raises(HTTPException) as ei:
        _resolve_within(str(server_dir), "linked/anything")
    assert ei.value.status_code == 400


# ---- /files/tree -------------------------------------------------------

async def test_tree_returns_404_for_unknown_server(client, fake_server) -> None:
    response = await client.get("/servers/nope/files/tree")
    assert response.status_code == 404


async def test_tree_lists_root_including_hidden_and_scaffold(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / ".env").write_text("RCON_PASSWORD=x\n", encoding="utf-8")
    (server_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (server_dir / "server").mkdir()

    response = await client.get("/servers/atm10/files/tree")

    assert response.status_code == 200
    body = response.text
    assert ".env" in body
    assert "docker-compose.yml" in body
    assert "server/" in body


async def test_tree_dir_entries_emit_lazy_hx_get(client, fake_server, server_dir: Path) -> None:
    (server_dir / "config").mkdir()

    response = await client.get("/servers/atm10/files/tree")

    body = response.text
    assert "hx-get=\"/servers/atm10/files/tree?path=config\"" in body
    assert "hx-trigger=\"click once\"" in body
    # PR-3: each dir entry is also a drop target with a per-folder upload trigger.
    assert 'data-upload-target' in body
    assert 'data-upload-path="config"' in body
    assert 'data-upload-trigger' in body
    # PR-4: dir entries also carry mkdir + delete triggers.
    assert 'data-action-mkdir' in body
    assert 'data-action-delete' in body
    assert 'data-action-kind="dir"' in body
    assert 'data-action-name="config"' in body
    # PR-5: dir entries also carry rename + move triggers.
    assert 'data-action-rename' in body
    assert 'data-action-move' in body
    # PR-7: every entry carries a multi-select checkbox.
    assert 'data-select-path="config"' in body
    assert 'data-select-kind="dir"' in body


async def test_tree_file_entries_link_to_view(client, fake_server, server_dir: Path) -> None:
    (server_dir / "server.properties").write_text("level-name=world\n", encoding="utf-8")

    response = await client.get("/servers/atm10/files/tree")

    body = response.text
    assert "hx-get=\"/servers/atm10/files/view?path=server.properties\"" in body
    assert "hx-target=\"#file-view\"" in body
    # PR-4: file entries carry a one-shot delete trigger (no type-name confirm).
    assert 'data-action-delete' in body
    assert 'data-action-kind="file"' in body
    assert 'data-action-name="server.properties"' in body
    # PR-6: file entries carry a download anchor with the `download` attr.
    assert 'href="/servers/atm10/files/download?path=server.properties"' in body
    assert 'download' in body


async def test_tree_lazy_load_subdir(client, fake_server, server_dir: Path) -> None:
    nested = server_dir / "server" / "config"
    nested.mkdir(parents=True)
    (nested / "foo.toml").write_text("k = 'v'\n", encoding="utf-8")

    response = await client.get("/servers/atm10/files/tree?path=server/config")

    assert response.status_code == 200
    assert "foo.toml" in response.text


async def test_tree_400_on_path_traversal(client, fake_server) -> None:
    response = await client.get("/servers/atm10/files/tree", params={"path": "../etc"})
    assert response.status_code == 400


async def test_tree_404_on_missing_subdir(client, fake_server) -> None:
    response = await client.get("/servers/atm10/files/tree", params={"path": "nope"})
    assert response.status_code == 404


async def test_tree_400_when_path_is_a_file(client, fake_server, server_dir: Path) -> None:
    (server_dir / "file.txt").write_text("x", encoding="utf-8")
    response = await client.get("/servers/atm10/files/tree", params={"path": "file.txt"})
    assert response.status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_tree_renders_symlink_with_marker_but_refuses_to_follow(
    client, fake_server, server_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (server_dir / "linkdir").symlink_to(outside)

    listing = await client.get("/servers/atm10/files/tree")
    assert listing.status_code == 200
    assert "linkdir" in listing.text
    assert "file-tree__entry--symlink" in listing.text

    follow = await client.get("/servers/atm10/files/tree", params={"path": "linkdir"})
    assert follow.status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="FIFOs are POSIX-only")
async def test_tree_skips_special_files(client, fake_server, server_dir: Path) -> None:
    os.mkfifo(server_dir / "myfifo")
    response = await client.get("/servers/atm10/files/tree")
    assert response.status_code == 200
    assert "myfifo" not in response.text


# ---- /files/view -------------------------------------------------------

async def test_view_returns_404_for_unknown_server(client, fake_server) -> None:
    response = await client.get("/servers/nope/files/view", params={"path": "x"})
    assert response.status_code == 404


async def test_view_renders_text_in_editor(client, fake_server, server_dir: Path) -> None:
    target = server_dir / "server.properties"
    target.write_text("level-name=world\n", encoding="utf-8")
    expected_mtime_ns = target.stat().st_mtime_ns

    response = await client.get(
        "/servers/atm10/files/view", params={"path": "server.properties"}
    )

    assert response.status_code == 200
    body = response.text
    # Initial content lives in the textarea CodeMirror mounts over.
    assert "level-name=world" in body
    assert "data-file-editor" in body
    assert 'name="path" value="server.properties"' in body
    assert f'name="mtime_ns" value="{expected_mtime_ns}"' in body
    assert "/servers/atm10/files/save" in body
    # The read-only <pre> placeholder from PR 1 is gone for text mode.
    assert "<pre" not in body


async def test_view_binary_file_renders_placeholder(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "world.dat").write_bytes(b"\x00\x01\x02\x03" * 256)

    response = await client.get("/servers/atm10/files/view", params={"path": "world.dat"})

    assert response.status_code == 200
    assert "binary file" in response.text
    assert "<pre" not in response.text


async def test_view_large_text_file_renders_placeholder(
    client, fake_server, server_dir: Path
) -> None:
    big = server_dir / "huge.log"
    # 6 MB of plain ASCII (no null byte → not classified as binary).
    big.write_text("a" * (6 * 1024 * 1024), encoding="utf-8")

    response = await client.get("/servers/atm10/files/view", params={"path": "huge.log"})

    assert response.status_code == 200
    assert "too large" in response.text
    assert "<pre" not in response.text


async def test_view_400_on_traversal(client, fake_server) -> None:
    response = await client.get(
        "/servers/atm10/files/view", params={"path": "../etc/passwd"}
    )
    assert response.status_code == 400


async def test_view_404_for_missing_file(client, fake_server) -> None:
    response = await client.get(
        "/servers/atm10/files/view", params={"path": "no-such.txt"}
    )
    assert response.status_code == 404


async def test_view_400_on_directory(client, fake_server, server_dir: Path) -> None:
    (server_dir / "subdir").mkdir()
    response = await client.get("/servers/atm10/files/view", params={"path": "subdir"})
    assert response.status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_view_refuses_symlink(
    client, fake_server, server_dir: Path, tmp_path: Path
) -> None:
    target = tmp_path / "secret.txt"
    target.write_text("oops", encoding="utf-8")
    (server_dir / "link.txt").symlink_to(target)

    response = await client.get("/servers/atm10/files/view", params={"path": "link.txt"})

    assert response.status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="FIFOs are POSIX-only")
async def test_view_refuses_special_file(client, fake_server, server_dir: Path) -> None:
    os.mkfifo(server_dir / "myfifo")
    response = await client.get("/servers/atm10/files/view", params={"path": "myfifo"})
    assert response.status_code == 400


# ---- /files/save -------------------------------------------------------

async def test_save_writes_content_and_returns_fresh_mtime(
    client, fake_server, server_dir: Path
) -> None:
    target = server_dir / "server.properties"
    target.write_text("level-name=world\n", encoding="utf-8")
    mtime_ns = target.stat().st_mtime_ns

    response = await client.post(
        "/servers/atm10/files/save",
        data={
            "path": "server.properties",
            "content": "level-name=overworld\nmotd=hi\n",
            "mtime_ns": str(mtime_ns),
        },
    )

    assert response.status_code == 200
    assert target.read_text(encoding="utf-8") == "level-name=overworld\nmotd=hi\n"
    new_mtime_ns = target.stat().st_mtime_ns
    body = response.text
    assert f'name="mtime_ns" value="{new_mtime_ns}"' in body
    assert "saved" in body


async def test_save_normalizes_crlf_to_lf(
    client, fake_server, server_dir: Path
) -> None:
    target = server_dir / "notes.txt"
    target.write_text("a\n", encoding="utf-8")
    mtime_ns = target.stat().st_mtime_ns

    response = await client.post(
        "/servers/atm10/files/save",
        data={
            "path": "notes.txt",
            "content": "a\r\nb\r\n",
            "mtime_ns": str(mtime_ns),
        },
    )

    assert response.status_code == 200
    # Bytes on disk: no CR.
    assert target.read_bytes() == b"a\nb\n"


async def test_save_returns_409_on_mtime_mismatch(
    client, fake_server, server_dir: Path
) -> None:
    target = server_dir / "server.properties"
    target.write_text("a\n", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/save",
        data={
            "path": "server.properties",
            "content": "operator-edit\n",
            "mtime_ns": "1",  # bogus stale mtime
        },
    )

    assert response.status_code == 409
    body = response.text
    # Conflict banner exposes all three resolution paths.
    assert "file-conflict" in body
    assert "Reload" in body
    assert "Overwrite" in body
    assert "Cancel" in body
    # Editor stays mounted with the operator's pending content.
    assert "operator-edit" in body
    assert "data-file-editor" in body
    # The form's mtime_ns was bumped to the disk's current value so a
    # follow-up plain Save would also succeed.
    current_mtime = target.stat().st_mtime_ns
    assert f'name="mtime_ns" value="{current_mtime}"' in body
    # On-disk content is unchanged.
    assert target.read_text(encoding="utf-8") == "a\n"


async def test_save_force_overwrite_after_mismatch(
    client, fake_server, server_dir: Path
) -> None:
    target = server_dir / "server.properties"
    target.write_text("disk-version\n", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/save",
        data={
            "path": "server.properties",
            "content": "operator-version\n",
            "mtime_ns": "1",
            "force": "true",
        },
    )

    assert response.status_code == 200
    assert target.read_text(encoding="utf-8") == "operator-version\n"


async def test_save_400_on_traversal(client, fake_server) -> None:
    response = await client.post(
        "/servers/atm10/files/save",
        data={
            "path": "../etc/passwd",
            "content": "x",
            "mtime_ns": "0",
            "force": "true",
        },
    )
    assert response.status_code == 400


async def test_save_404_for_missing_file(client, fake_server) -> None:
    response = await client.post(
        "/servers/atm10/files/save",
        data={
            "path": "no-such.txt",
            "content": "x",
            "mtime_ns": "0",
            "force": "true",
        },
    )
    assert response.status_code == 404


async def test_save_400_on_directory(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "subdir").mkdir()
    response = await client.post(
        "/servers/atm10/files/save",
        data={
            "path": "subdir",
            "content": "x",
            "mtime_ns": "0",
            "force": "true",
        },
    )
    assert response.status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_save_refuses_symlink_target(
    client, fake_server, server_dir: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("untouched", encoding="utf-8")
    (server_dir / "link.txt").symlink_to(secret)

    response = await client.post(
        "/servers/atm10/files/save",
        data={
            "path": "link.txt",
            "content": "pwned",
            "mtime_ns": "0",
            "force": "true",
        },
    )

    assert response.status_code == 400
    assert secret.read_text(encoding="utf-8") == "untouched"


@pytest.mark.skipif(sys.platform == "win32", reason="FIFOs are POSIX-only")
async def test_save_refuses_special_file(
    client, fake_server, server_dir: Path
) -> None:
    os.mkfifo(server_dir / "myfifo")
    response = await client.post(
        "/servers/atm10/files/save",
        data={
            "path": "myfifo",
            "content": "x",
            "mtime_ns": "0",
            "force": "true",
        },
    )
    assert response.status_code == 400


async def test_save_is_atomic_no_partial_visible(
    client, fake_server, server_dir: Path
) -> None:
    """A successful save leaves no `.<name>.<rand>` tempfile next to target."""
    target = server_dir / "server.properties"
    target.write_text("a=1\n", encoding="utf-8")
    mtime_ns = target.stat().st_mtime_ns

    response = await client.post(
        "/servers/atm10/files/save",
        data={
            "path": "server.properties",
            "content": "a=2\n",
            "mtime_ns": str(mtime_ns),
        },
    )

    assert response.status_code == 200
    assert target.read_text(encoding="utf-8") == "a=2\n"
    # No leftover sibling tempfiles.
    siblings = [p.name for p in server_dir.iterdir()]
    assert siblings == ["server.properties"]


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
    # The symlink target is unchanged — we replaced the link entry, not
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
    # The original file is untouched — we never followed the link.
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


# ---- /files/tree?picker=1 ---------------------------------------------

async def test_tree_picker_returns_dirs_only(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "mods").mkdir()
    (server_dir / "config").mkdir()
    (server_dir / "server.properties").write_text("x", encoding="utf-8")
    (server_dir / "Dockerfile").write_text("y", encoding="utf-8")

    response = await client.get("/servers/atm10/files/tree?picker=1")

    assert response.status_code == 200
    body = response.text
    assert "mods" in body
    assert "config" in body
    # Files are filtered out of the picker.
    assert "server.properties" not in body
    assert "Dockerfile" not in body
    # Picker rows carry the select hook.
    assert "data-picker-select" in body
    # Lazy-load URLs preserve the picker flag.
    assert "picker=1" in body


async def test_tree_picker_recurses_with_flag(
    client, fake_server, server_dir: Path
) -> None:
    nested = server_dir / "server" / "config"
    nested.mkdir(parents=True)
    (nested / "deep").mkdir()
    (nested / "leaf.txt").write_text("x", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/tree", params={"path": "server/config", "picker": "1"}
    )

    assert response.status_code == 200
    body = response.text
    assert "deep" in body
    assert "leaf.txt" not in body


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
    # Source's parent (root) is what JS swaps in — moved.txt must be gone
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


# ---- /files/download ---------------------------------------------------

async def test_download_returns_bytes_with_attachment_disposition(
    client, fake_server, server_dir: Path
) -> None:
    target = server_dir / "world.dat"
    payload = b"\x00\x01\x02\x03binary-blob"
    target.write_bytes(payload)

    response = await client.get(
        "/servers/atm10/files/download", params={"path": "world.dat"}
    )

    assert response.status_code == 200
    assert response.content == payload
    cd = response.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert 'filename="world.dat"' in cd
    assert response.headers.get("content-type") == "application/octet-stream"


async def test_download_404_for_missing_file(client, fake_server) -> None:
    response = await client.get(
        "/servers/atm10/files/download", params={"path": "no-such.txt"}
    )
    assert response.status_code == 404


async def test_download_400_on_traversal(client, fake_server) -> None:
    response = await client.get(
        "/servers/atm10/files/download", params={"path": "../etc/passwd"}
    )
    assert response.status_code == 400


async def test_download_400_on_directory(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "subdir").mkdir()

    response = await client.get(
        "/servers/atm10/files/download", params={"path": "subdir"}
    )
    assert response.status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_download_refuses_symlink(
    client, fake_server, server_dir: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("oops", encoding="utf-8")
    (server_dir / "link.txt").symlink_to(secret)

    response = await client.get(
        "/servers/atm10/files/download", params={"path": "link.txt"}
    )
    assert response.status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="FIFOs are POSIX-only")
async def test_download_refuses_special_file(
    client, fake_server, server_dir: Path
) -> None:
    os.mkfifo(server_dir / "myfifo")
    response = await client.get(
        "/servers/atm10/files/download", params={"path": "myfifo"}
    )
    assert response.status_code == 400


async def test_download_404_for_unknown_server(client, fake_server) -> None:
    response = await client.get(
        "/servers/nope/files/download", params={"path": "anything"}
    )
    assert response.status_code == 404


# ---- /files/search -----------------------------------------------------

async def test_search_short_query_returns_placeholder(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "match.txt").write_text("x", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "m"}
    )

    assert response.status_code == 200
    body = response.text
    assert "type at least 2 characters" in body
    # Placeholder must NOT include any matching results.
    assert "match.txt" not in body


async def test_search_finds_basename_match_recursive(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "match.txt").write_text("x", encoding="utf-8")
    nested = server_dir / "sub" / "deep"
    nested.mkdir(parents=True)
    (nested / "alsoMATCH.log").write_text("y", encoding="utf-8")
    (server_dir / "skip.cfg").write_text("z", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "match"}
    )

    assert response.status_code == 200
    body = response.text
    assert "match.txt" in body
    # Case-insensitive substring matches the nested file too.
    assert "alsoMATCH.log" in body
    assert "sub/deep/alsoMATCH.log" in body
    assert "skip.cfg" not in body


async def test_search_no_results(client, fake_server, server_dir: Path) -> None:
    (server_dir / "foo.txt").write_text("x", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "zzznotthere"}
    )

    assert response.status_code == 200
    assert "no matches" in response.text


async def test_search_caps_at_limit_and_marks_truncated(
    client, fake_server, server_dir: Path, monkeypatch
) -> None:
    """Generate more than the cap so the truncated badge shows."""
    monkeypatch.setattr("mcontrol.routes.files._SEARCH_LIMIT", 5)
    for i in range(20):
        (server_dir / f"matchX-{i}.txt").write_text("x", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "matchX"}
    )

    assert response.status_code == 200
    body = response.text
    # Truncation marker present and result count is at the cap.
    assert "capped" in body or "truncated" in body
    # `data-select-path="matchX-` appears once per rendered hit.
    assert body.count('data-select-path="matchX-') == 5
    # Late files weren't rendered — the cap stopped the walk early.
    assert "matchX-19" not in body


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_search_does_not_descend_into_symlinked_dir(
    client, fake_server, server_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "matchABC.txt").write_text("x", encoding="utf-8")
    (server_dir / "linkdir").symlink_to(outside)

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "matchABC"}
    )

    assert response.status_code == 200
    # The file inside the symlinked dir must NOT be reached.
    assert "matchABC.txt" not in response.text


# ---- /files/bulk_delete -----------------------------------------------

async def test_bulk_delete_removes_multiple_files(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("x", encoding="utf-8")
    (server_dir / "b.txt").write_text("y", encoding="utf-8")
    (server_dir / "stay.txt").write_text("z", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["a.txt", "b.txt"], "confirm": "DELETE"},
    )

    assert response.status_code == 200
    assert not (server_dir / "a.txt").exists()
    assert not (server_dir / "b.txt").exists()
    assert (server_dir / "stay.txt").exists()


async def test_bulk_delete_recursive_dir(
    client, fake_server, server_dir: Path
) -> None:
    d = server_dir / "doomed"
    (d / "nested").mkdir(parents=True)
    (d / "nested" / "leaf.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["doomed"], "confirm": "DELETE"},
    )

    assert response.status_code == 200
    assert not d.exists()


async def test_bulk_delete_400_without_DELETE_confirm(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["a.txt"]},
    )

    assert response.status_code == 400
    assert (server_dir / "a.txt").exists()


async def test_bulk_delete_400_with_wrong_confirm(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["a.txt"], "confirm": "delete"},
    )

    assert response.status_code == 400
    assert (server_dir / "a.txt").exists()


async def test_bulk_delete_400_refuses_root_in_paths(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "marker.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["", "marker.txt"], "confirm": "DELETE"},
    )

    assert response.status_code == 400
    # Nothing deleted.
    assert (server_dir / "marker.txt").exists()


async def test_bulk_delete_404_on_any_missing_aborts_batch(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["a.txt", "no-such.txt"], "confirm": "DELETE"},
    )

    assert response.status_code == 404
    # Refuse-on-any-bad-input: a.txt must NOT have been deleted.
    assert (server_dir / "a.txt").exists()


# ---- /files/bulk_move -------------------------------------------------

async def test_bulk_move_relocates_multiple_files(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("a", encoding="utf-8")
    (server_dir / "b.txt").write_text("b", encoding="utf-8")
    (server_dir / "dst").mkdir()

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["a.txt", "b.txt"], "dest_dir": "dst"},
    )

    assert response.status_code == 200
    assert not (server_dir / "a.txt").exists()
    assert not (server_dir / "b.txt").exists()
    assert (server_dir / "dst" / "a.txt").read_text(encoding="utf-8") == "a"
    assert (server_dir / "dst" / "b.txt").read_text(encoding="utf-8") == "b"


async def test_bulk_move_409_on_any_collision_aborts_batch(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("a", encoding="utf-8")
    (server_dir / "b.txt").write_text("b", encoding="utf-8")
    (server_dir / "dst").mkdir()
    (server_dir / "dst" / "b.txt").write_text("victim", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["a.txt", "b.txt"], "dest_dir": "dst"},
    )

    assert response.status_code == 409
    # Refuse-on-any-collision: nothing moved.
    assert (server_dir / "a.txt").exists()
    assert (server_dir / "b.txt").exists()
    assert (server_dir / "dst" / "b.txt").read_text(encoding="utf-8") == "victim"


async def test_bulk_move_400_refuses_no_op_for_any_source(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("a", encoding="utf-8")
    (server_dir / "sub").mkdir()
    (server_dir / "sub" / "b.txt").write_text("b", encoding="utf-8")

    # `a.txt`'s parent IS the destination root → no-op for it.
    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["a.txt", "sub/b.txt"], "dest_dir": ""},
    )

    assert response.status_code == 400
    # Neither source moved.
    assert (server_dir / "a.txt").exists()
    assert (server_dir / "sub" / "b.txt").exists()


async def test_bulk_move_400_refuses_root_source(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "dst").mkdir()
    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": [""], "dest_dir": "dst"},
    )
    assert response.status_code == 400


async def test_bulk_move_400_refuses_into_descendant(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "parent" / "child").mkdir(parents=True)

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["parent"], "dest_dir": "parent/child"},
    )
    assert response.status_code == 400
    assert (server_dir / "parent" / "child").is_dir()


async def test_bulk_move_404_when_destination_missing(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("a", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["a.txt"], "dest_dir": "no-such"},
    )
    assert response.status_code == 404


# ---- server_detail integration ----------------------------------------

async def test_server_detail_renders_files_pane(client, monkeypatch) -> None:
    from mcontrol import db
    monkeypatch.setattr(db, "get_server", lambda n: {
        "name": "atm10",
        "container_name": None,
        "dir": "/srv/atm10",
        "image_base": None,
        "state": "running",
        "variables": {},
        "rcon_password": None,
        "created_at": "2026-04-29T10:00:00Z",
        "updated_at": "2026-04-29T10:00:00Z",
    })

    response = await client.get("/servers/atm10")

    assert response.status_code == 200
    body = response.text
    assert "files-pane" in body
    assert 'id="file-tree"' in body
    assert 'id="file-view"' in body
    assert 'hx-get="/servers/atm10/files/tree?path="' in body
    # PR-3: upload UI is wired into the pane.
    assert 'data-server-name="atm10"' in body
    assert 'id="file-action-status"' in body
    assert 'id="file-upload-input"' in body
    # Root drop target + root upload trigger both carry data-upload-path="".
    assert 'data-upload-target' in body
    assert 'data-upload-trigger' in body
    # PR-4: root mkdir trigger is wired into the eyebrow.
    assert 'data-action-mkdir' in body
    # PR-7: search input + bulk toolbar are present (toolbar starts hidden).
    assert 'id="file-search-input"' in body
    assert 'id="file-search-results"' in body
    assert 'id="file-bulk-toolbar"' in body
    assert 'data-bulk-action="delete"' in body
    assert 'data-bulk-action="move"' in body
