import os
import sys
from pathlib import Path

import pytest

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


# ---- view-pane header (issues #54, #60, #61) --------------------------

async def test_view_text_shows_size_and_mtime_caption(
    client, fake_server, server_dir: Path
) -> None:
    """Issue #60: text-file view header carries the size + mtime caption."""
    (server_dir / "server.properties").write_text("level-name=world\n", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/view", params={"path": "server.properties"}
    )

    assert response.status_code == 200
    body = response.text
    assert "file-view__meta" in body
    # Small text payload renders as bytes.
    assert " B" in body
    assert "modified " in body


async def test_view_binary_shows_size_and_mtime_caption(
    client, fake_server, server_dir: Path
) -> None:
    """Issue #60: binary view shares the same metadata caption."""
    (server_dir / "world.dat").write_bytes(b"\x00\x01\x02\x03" * 256)

    response = await client.get(
        "/servers/atm10/files/view", params={"path": "world.dat"}
    )

    assert response.status_code == 200
    body = response.text
    assert "file-view__meta" in body
    assert "modified " in body


async def test_view_too_large_shows_size_and_mtime_caption(
    client, fake_server, server_dir: Path
) -> None:
    """Issue #60: too-large view shares the same metadata caption."""
    big = server_dir / "huge.log"
    big.write_text("a" * (6 * 1024 * 1024), encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/view", params={"path": "huge.log"}
    )

    assert response.status_code == 200
    body = response.text
    assert "file-view__meta" in body
    # >1 MiB file → MiB-formatted size in the caption.
    assert " MiB" in body
    assert "modified " in body


async def test_view_binary_renders_info_card_with_actions(
    client, fake_server, server_dir: Path
) -> None:
    """Issue #54: binary view replaces the dead-end caption with action buttons
    that reuse the tree popover's data-action-* selector contract."""
    (server_dir / "world.dat").write_bytes(b"\x00\x01\x02\x03" * 256)

    response = await client.get(
        "/servers/atm10/files/view", params={"path": "world.dat"}
    )

    assert response.status_code == 200
    body = response.text
    assert "file-view__info-card" in body
    # Download is a normal anchor with the download attribute.
    assert 'href="/servers/atm10/files/download?path=world.dat"' in body
    assert "download" in body
    # The three action buttons reuse the same data-action-* attributes
    # the tree popover uses, so existing JS handlers wire up automatically.
    assert "data-action-rename" in body
    assert "data-action-move" in body
    assert "data-action-delete" in body
    assert 'data-action-path="world.dat"' in body
    assert 'data-action-name="world.dat"' in body


async def test_view_too_large_renders_info_card_with_actions(
    client, fake_server, server_dir: Path
) -> None:
    """Issue #54: too-large view also exposes the four operations."""
    big = server_dir / "huge.log"
    big.write_text("a" * (6 * 1024 * 1024), encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/view", params={"path": "huge.log"}
    )

    assert response.status_code == 200
    body = response.text
    assert "file-view__info-card" in body
    assert "too large" in body
    assert 'href="/servers/atm10/files/download?path=huge.log"' in body
    assert "data-action-rename" in body
    assert "data-action-move" in body
    assert "data-action-delete" in body


async def test_view_renders_breadcrumb_segments(
    client, fake_server, server_dir: Path
) -> None:
    """Issue #61: deep paths render as breadcrumbs; preceding segments are
    interactive (carry data-breadcrumb-path), and the final segment is plain."""
    nested = server_dir / "config" / "forge"
    nested.mkdir(parents=True)
    (nested / "foo.toml").write_text("k = 'v'\n", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/view", params={"path": "config/forge/foo.toml"}
    )

    assert response.status_code == 200
    body = response.text
    # First two segments are clickable, keyed by their accumulated path.
    assert 'data-breadcrumb-path="config"' in body
    assert 'data-breadcrumb-path="config/forge"' in body
    # The leaf segment is rendered plain, not as a button.
    assert "file-view__breadcrumb-leaf" in body
    assert 'data-breadcrumb-path="config/forge/foo.toml"' not in body


async def test_view_breadcrumb_present_in_binary_and_too_large(
    client, fake_server, server_dir: Path
) -> None:
    """Issue #61: the breadcrumb is shared across all three view modes."""
    nested = server_dir / "mods"
    nested.mkdir()
    (nested / "thing.jar").write_bytes(b"\x00fake-jar")

    response = await client.get(
        "/servers/atm10/files/view", params={"path": "mods/thing.jar"}
    )
    assert response.status_code == 200
    assert 'data-breadcrumb-path="mods"' in response.text

    # Too-large variant
    big_dir = server_dir / "logs"
    big_dir.mkdir()
    (big_dir / "big.log").write_text("a" * (6 * 1024 * 1024), encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/view", params={"path": "logs/big.log"}
    )
    assert response.status_code == 200
    assert 'data-breadcrumb-path="logs"' in response.text


def test_file_view_size_caption_uses_format_bytes() -> None:
    """Issue #60: the file-view size caption uses the canonical base-1024
    formatter (IEC units), shared with the system-stats surfaces instead
    of a second near-duplicate banding function."""
    from mcontrol.infra.resources import format_bytes
    from mcontrol.templates import templates

    assert templates.env.filters["humansize"] is format_bytes
