import os
import stat
import sys
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mcontrol.services import file_archive

URL = "/servers/atm10/files"


def make_zip(server_dir: Path, entries: list[tuple[str, bytes]]) -> Path:
    path = server_dir / "source.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return path


async def test_zip_roundtrip_preserves_tree_and_source(client, fake_server, server_dir):
    (server_dir / "mods" / "empty").mkdir(parents=True)
    (server_dir / "mods" / "mod.jar").write_bytes(b"mod payload")
    (server_dir / "config.txt").write_bytes(b"settings")
    response = await client.post(
        URL + "/compress",
        data={
            "paths": ["mods", "mods/mod.jar", "config.txt", "mods"],
            "dest_dir": "",
            "archive_name": "backup.zip",
            "format": "zip",
        },
    )
    assert response.status_code == 204, response.text
    packed = server_dir / "backup.zip"
    before = packed.read_bytes()
    with zipfile.ZipFile(packed) as archive:
        assert set(archive.namelist()) == {"mods/", "mods/empty/", "mods/mod.jar", "config.txt"}
    response = await client.post(
        URL + "/extract", data={"path": "backup.zip", "dest_dir": "restored/nested"}
    )
    assert response.status_code == 204, response.text
    assert (server_dir / "restored/nested/mods/mod.jar").read_bytes() == b"mod payload"
    assert (server_dir / "restored/nested/config.txt").read_bytes() == b"settings"
    assert (server_dir / "restored/nested/mods/empty").is_dir()
    assert packed.read_bytes() == before
    assert not list(server_dir.glob(".mcontrol-archive-*"))


async def test_extract_here_merges_existing_directories(client, fake_server, server_dir):
    (server_dir / "mods").mkdir()
    (server_dir / "mods" / "existing.jar").write_bytes(b"existing")
    make_zip(server_dir, [("mods/", b""), ("mods/new.jar", b"new")])
    response = await client.post(URL + "/extract", data={"path": "source.zip", "dest_dir": ""})
    assert response.status_code == 204, response.text
    assert (server_dir / "mods/new.jar").read_bytes() == b"new"
    assert (server_dir / "mods/existing.jar").read_bytes() == b"existing"


@pytest.mark.parametrize(
    "member",
    [
        "../outside",
        "/absolute",
        "C:/drive",
        "a\\escape",
        "folder/../escape",
        "a//b",
        "a:stream",
        "NUL",
        "folder./x",
        "a\x00b",
    ],
)
async def test_extract_rejects_unsafe_paths(client, fake_server, server_dir, member):
    if "\x00" in member:
        # zipfile truncates NUL filenames at writing time, so mutate the stored name.
        source = make_zip(server_dir, [("a_b", b"payload")])
        source.write_bytes(source.read_bytes().replace(b"a_b", b"a\x00b"))
    elif "\\" in member:
        source = make_zip(server_dir, [(member.replace("\\", "/"), b"payload")])
        source.write_bytes(source.read_bytes().replace(b"a/escape", b"a\\escape"))
    else:
        make_zip(server_dir, [(member, b"payload")])
    response = await client.post(URL + "/extract", data={"path": "source.zip", "dest_dir": "out"})
    assert response.status_code == 400, response.text
    assert not (server_dir / "out").exists()


@pytest.mark.parametrize(
    "entries",
    [
        [("same", b"one"), ("same", b"two")],
        [("Name", b"one"), ("name", b"two")],
        [("a", b"file"), ("a/child", b"child")],
        [("a/child", b"child"), ("a", b"file")],
    ],
)
async def test_extract_rejects_conflicting_members(client, fake_server, server_dir, entries):
    make_zip(server_dir, entries)
    response = await client.post(URL + "/extract", data={"path": "source.zip", "dest_dir": "out"})
    assert response.status_code == 400
    assert not (server_dir / "out").exists()


async def test_extract_collision_preflight_does_not_publish_other_files(
    client, fake_server, server_dir
):
    (server_dir / "out").mkdir()
    (server_dir / "out/existing").write_bytes(b"keep")
    make_zip(server_dir, [("new", b"new"), ("existing", b"replace")])
    response = await client.post(URL + "/extract", data={"path": "source.zip", "dest_dir": "out"})
    assert response.status_code == 409
    assert (server_dir / "out/existing").read_bytes() == b"keep"
    assert not (server_dir / "out/new").exists()


async def test_corrupt_second_member_leaves_no_partial_destination(client, fake_server, server_dir):
    source = make_zip(server_dir, [("first", b"good"), ("second", b"unique_payload")])
    source.write_bytes(source.read_bytes().replace(b"unique_payload", b"corruptpayload"))
    response = await client.post(URL + "/extract", data={"path": "source.zip", "dest_dir": "out"})
    assert response.status_code == 400, response.text
    assert not (server_dir / "out").exists()
    assert not list(server_dir.glob(".mcontrol-archive-*"))


@pytest.mark.parametrize("kind", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR])
async def test_extract_rejects_link_and_special_members(client, fake_server, server_dir, kind):
    info = zipfile.ZipInfo("entry")
    info.create_system = 3
    info.external_attr = (kind | 0o777) << 16
    with zipfile.ZipFile(server_dir / "source.zip", "w") as archive:
        archive.writestr(info, b"target")
    response = await client.post(URL + "/extract", data={"path": "source.zip", "dest_dir": "out"})
    assert response.status_code == 400
    assert not (server_dir / "out").exists()


async def test_extract_limits(client, fake_server, server_dir, monkeypatch):
    make_zip(server_dir, [("one", b"1234"), ("two", b"5678")])
    monkeypatch.setattr(file_archive, "MAX_BYTES", 7)
    response = await client.post(URL + "/extract", data={"path": "source.zip", "dest_dir": "out"})
    assert response.status_code == 413
    assert not (server_dir / "out").exists()
    monkeypatch.setattr(file_archive, "MAX_BYTES", 1024)
    monkeypatch.setattr(file_archive, "MAX_MEMBERS", 1)
    response = await client.post(URL + "/extract", data={"path": "source.zip", "dest_dir": "out"})
    assert response.status_code == 413
    monkeypatch.setattr(file_archive, "MAX_MEMBERS", 10)
    monkeypatch.setattr(file_archive, "MAX_SECONDS", 0)
    response = await client.post(URL + "/extract", data={"path": "source.zip", "dest_dir": "out"})
    assert response.status_code == 413


async def test_zip_output_collision_preserves_archive(client, fake_server, server_dir):
    (server_dir / "a.txt").write_bytes(b"a")
    (server_dir / "backup.zip").write_bytes(b"existing")
    response = await client.post(
        URL + "/compress",
        data={
            "paths": ["a.txt"],
            "archive_name": "backup.zip",
            "format": "zip",
        },
    )
    assert response.status_code == 409
    assert (server_dir / "backup.zip").read_bytes() == b"existing"


@pytest.mark.parametrize(
    "changes",
    [
        {"paths": [""]},
        {"paths": ["../outside"]},
        {"archive_name": "../escape.zip"},
        {"archive_name": "wrong.rar"},
        {"format": "7z"},
        {"dest_dir": "/absolute"},
    ],
)
async def test_compress_rejects_invalid_requests(client, fake_server, server_dir, changes):
    (server_dir / "file.txt").write_bytes(b"payload")
    data = {"paths": ["file.txt"], "archive_name": "backup.zip", "format": "zip"} | changes
    response = await client.post(URL + "/compress", data=data)
    assert response.status_code == 400, response.text
    assert not (server_dir / "backup.zip").exists()


async def test_compress_common_ancestor_and_output_inside_source(client, fake_server, server_dir):
    (server_dir / "folder/deep").mkdir(parents=True)
    (server_dir / "folder/deep/file").write_bytes(b"payload")
    response = await client.post(
        URL + "/compress",
        data={
            "paths": ["folder"],
            "dest_dir": "folder",
            "archive_name": "backup.zip",
            "format": "zip",
        },
    )
    assert response.status_code == 204, response.text
    with zipfile.ZipFile(server_dir / "folder/backup.zip") as archive:
        assert set(archive.namelist()) == {"folder/", "folder/deep/", "folder/deep/file"}


async def test_archive_refuses_filesystem_symlinks(client, fake_server, server_dir):
    (server_dir / "real").mkdir()
    try:
        (server_dir / "linked").symlink_to(server_dir / "real", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    make_zip(server_dir, [("file", b"payload")])
    response = await client.post(
        URL + "/extract", data={"path": "source.zip", "dest_dir": "linked"}
    )
    assert response.status_code == 400
    response = await client.post(
        URL + "/compress",
        data={
            "paths": ["linked"],
            "archive_name": "backup.zip",
            "format": "zip",
        },
    )
    assert response.status_code == 400


async def test_rar_unavailable_is_clear(client, fake_server, server_dir, monkeypatch):
    monkeypatch.setattr(file_archive, "_decoder", lambda: None)
    monkeypatch.setattr(file_archive.shutil, "which", lambda _: None)
    (server_dir / "source.rar").write_bytes(b"not needed when decoder unavailable")
    capabilities = await client.get(URL + "/archive-capabilities")
    assert capabilities.json() == {"zip": True, "rar_extract": False, "rar_compress": False}
    response = await client.post(URL + "/extract", data={"path": "source.rar", "dest_dir": "out"})
    assert response.status_code == 501
    assert "RAR extraction unavailable" in response.json()["detail"]
    response = await client.post(
        URL + "/compress",
        data={
            "paths": ["source.rar"],
            "archive_name": "backup.rar",
            "format": "rar",
        },
    )
    assert response.status_code == 501
    assert "licensed rar" in response.json()["detail"]


def test_rar_metadata_rejects_hardlinks():
    archive = MagicMock()
    archive.needs_password.return_value = False
    archive.volumelist.return_value = ["source.rar"]
    member = MagicMock()
    member.is_symlink.return_value = False
    member.file_redir = (4, 0, "target")
    archive.infolist.return_value = [member]
    with pytest.raises(file_archive.HTTPException) as error:
        file_archive._rar_members(archive)
    assert "links and special" in error.value.detail


@pytest.mark.parametrize("version", ["rar3", "rar5"])
async def test_real_rar_reader(client, fake_server, server_dir, version):
    if file_archive._decoder() is None:
        pytest.skip("requires unrar, rar or libarchive bsdtar")
    fixture = Path(__file__).parent / "fixtures/archives" / f"testfile.{version}.rar"
    source = server_dir / "source.rar"
    source.write_bytes(fixture.read_bytes())
    response = await client.post(
        URL + "/extract",
        data={
            "path": "source.rar",
            "dest_dir": "out",
        },
    )
    assert response.status_code == 204, response.text
    assert (server_dir / "out/testfile.txt").read_bytes() == b"Testing 123\n"
    assert source.read_bytes() == fixture.read_bytes()


def test_publish_race_rolls_back_created_files(server_dir, monkeypatch):
    stage = server_dir / "stage"
    stage.mkdir()
    (stage / "one").write_bytes(b"one")
    (stage / "two").write_bytes(b"two")
    real_link = os.link

    def fail_second(source, dest):
        if Path(dest).name == "two":
            raise FileExistsError("racing writer")
        real_link(source, dest)

    monkeypatch.setattr(file_archive.os, "link", fail_second)
    with pytest.raises(FileExistsError):
        file_archive._publish(
            str(server_dir),
            stage,
            server_dir / "out",
            [
                file_archive.Member("one", False, 3, None),
                file_archive.Member("two", False, 3, None),
            ],
        )
    assert not (server_dir / "out").exists()


def test_publish_rollback_preserves_file_replaced_by_another_writer(server_dir, monkeypatch):
    stage = server_dir / "stage"
    stage.mkdir()
    (stage / "one").write_bytes(b"archive data")
    (stage / "two").write_bytes(b"second archive member")
    real_link = os.link

    def replace_first_then_fail(source, dest):
        if Path(dest).name == "two":
            replacement = server_dir / "replacement"
            replacement.write_bytes(b"new user data")
            os.replace(replacement, server_dir / "out/one")
            raise FileExistsError("another conflict")
        real_link(source, dest)

    monkeypatch.setattr(file_archive.os, "link", replace_first_then_fail)
    with pytest.raises(FileExistsError):
        file_archive._publish(
            str(server_dir),
            stage,
            server_dir / "out",
            [
                file_archive.Member("one", False, 12, None),
                file_archive.Member("two", False, 21, None),
            ],
        )
    assert (server_dir / "out/one").read_bytes() == b"new user data"
    assert not (server_dir / "out/two").exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows chmod has no executable bits")
async def test_zip_roundtrip_preserves_executable_bits(client, fake_server, server_dir):
    script = server_dir / "start.sh"
    script.write_bytes(b"#!/bin/sh\necho ready\n")
    script.chmod(0o4755)
    response = await client.post(
        URL + "/compress",
        data={
            "paths": ["start.sh"],
            "archive_name": "scripts.zip",
            "format": "zip",
        },
    )
    assert response.status_code == 204, response.text
    response = await client.post(
        URL + "/extract",
        data={
            "path": "scripts.zip",
            "dest_dir": "restored",
        },
    )
    assert response.status_code == 204, response.text
    assert stat.S_IMODE((server_dir / "restored/start.sh").stat().st_mode) == 0o755


def test_rar_pipe_enforces_declared_size_and_kills_process(tmp_path):
    with (tmp_path / "output").open("wb") as output:
        with pytest.raises(file_archive.HTTPException) as error:
            file_archive._rar_stream(
                [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 100000)"],
                output,
                time.monotonic() + 10,
                3,
            )
    assert error.value.status_code == 413


def test_rar_pipe_deadline_kills_hanging_decoder(tmp_path):
    started = time.monotonic()
    with (tmp_path / "output").open("wb") as output:
        with pytest.raises(file_archive.HTTPException) as error:
            file_archive._rar_stream(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                output,
                time.monotonic() + 0.2,
                100,
            )
    assert error.value.status_code == 413
    assert time.monotonic() - started < 5


def test_rar_creation_uses_separate_input_and_exact_tool_args(server_dir, monkeypatch):
    # The licensed writer is optional; test our command/staging contract, not the writer itself.
    (server_dir / "world").mkdir()
    (server_dir / "world/level.dat").write_bytes(b"world data")
    monkeypatch.setattr(file_archive.shutil, "which", lambda _: "rar-tool")

    def run(command, **kwargs):
        assert command[:7] == ["rar-tool", "a", "-r", "-idq", "-y", "-ep1", "--"]
        assert command[-1] == "."
        assert kwargs["shell"] is False
        assert kwargs["timeout"] <= file_archive.MAX_SECONDS
        inputs = Path(kwargs["cwd"])
        assert (inputs / "world/level.dat").read_bytes() == b"world data"
        assert not (inputs / "backup.rar").exists()
        Path(command[-2]).write_bytes(b"writer output")
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr(file_archive.subprocess, "run", run)
    file_archive.compress(str(server_dir), ["world"], "world", "backup.rar", "rar")
    assert (server_dir / "world/backup.rar").read_bytes() == b"writer output"
    assert not list(server_dir.glob(".mcontrol-archive-*"))
