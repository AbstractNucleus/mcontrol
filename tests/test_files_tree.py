import os
import sys
from pathlib import Path

import pytest

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
    # follow-up: per-entry actions live inside a <details> popover.
    assert '<details class="file-tree__menu">' in body
    assert 'file-tree__menu-panel' in body


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
