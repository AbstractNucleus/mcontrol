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

    assert "hx-get=\"/servers/atm10/files/tree?path=config\"" in response.text
    assert "hx-trigger=\"click once\"" in response.text


async def test_tree_file_entries_link_to_view(client, fake_server, server_dir: Path) -> None:
    (server_dir / "server.properties").write_text("level-name=world\n", encoding="utf-8")

    response = await client.get("/servers/atm10/files/tree")

    assert "hx-get=\"/servers/atm10/files/view?path=server.properties\"" in response.text
    assert "hx-target=\"#file-view\"" in response.text


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


async def test_view_renders_text_in_pre(client, fake_server, server_dir: Path) -> None:
    (server_dir / "server.properties").write_text("level-name=world\n", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/view", params={"path": "server.properties"}
    )

    assert response.status_code == 200
    body = response.text
    assert "level-name=world" in body
    assert "<pre" in body
    assert "file-view__content" in body


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
