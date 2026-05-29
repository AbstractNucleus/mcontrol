import os
import sys
from pathlib import Path

import pytest

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
