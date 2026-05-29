import os
import sys
from pathlib import Path

import pytest

# ---- /files/save -------------------------------------------------------

async def test_save_writes_content_and_returns_fresh_mtime(
    client, fake_server, server_dir: Path
) -> None:
    """Issue #57: success returns just the meta fragment (fresh mtime +
    saved indicator) so the htmx swap doesn't tear down the CodeMirror
    EditorView and lose cursor/scroll position."""
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
    # Meta slot carries the fresh mtime and the saved indicator.
    assert 'id="file-editor-meta"' in body
    assert f'name="mtime_ns" value="{new_mtime_ns}"' in body
    assert "saved" in body
    # Success path must NOT re-render the editor. that would destroy the
    # mounted EditorView and reset the cursor (the whole point of #57).
    assert "data-file-editor" not in body
    assert "<textarea" not in body


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
    # Issue #57: the form's hx-target points at the small meta slot for
    # successful saves; on conflict we override it so the full view swaps
    # back into #file-view, which re-mounts the editor with the conflict
    # banner.
    assert response.headers["HX-Retarget"] == "#file-view"
    assert response.headers["HX-Reswap"] == "innerHTML"


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
