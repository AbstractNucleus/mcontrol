"""Bounded archive operations with staged data and no replacement of user files.

ZIP uses Python's decoder. RAR metadata uses rarfile; decoding requires bsdtar,
unrar or rar on PATH, and creating RAR archives requires the licensed rar tool.
"""

import os
import queue
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import zipfile
import zlib
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import rarfile
from fastapi import HTTPException

from mcontrol.infra import file_safety
from mcontrol.infra.file_writer import _adopt_ownership, mkdir_inherit_owner

MAX_BYTES = 20 * 1024**3
MAX_MEMBERS = 100_000
MAX_SECONDS = 600
CHUNK_SIZE = 64 * 1024
_BAD_CHARS = frozenset('<>:"\\|?*')


@dataclass(frozen=True)
class Member:
    name: str
    directory: bool
    size: int
    info: object
    executable_bits: int = 0


@dataclass(frozen=True)
class CreatedEntry:
    path: Path
    device: int
    inode: int
    directory: bool

    @classmethod
    def from_stat(cls, path: Path, info: os.stat_result) -> "CreatedEntry":
        return cls(path, info.st_dev, info.st_ino, stat.S_ISDIR(info.st_mode))


def _error(detail: str, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


def _check_time(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise _error(f"archive operation exceeds the {MAX_SECONDS} second limit", 413)


def _name_parts(name: str, *, directory: bool = False) -> list[str]:
    # Reject ambiguous Windows names even on Linux, including drive paths and ADS.
    cleaned = name[:-1] if directory and name.endswith("/") else name
    parts = cleaned.split("/")
    if not cleaned or any(
        not p
        or p in {".", ".."}
        or p.endswith((".", " "))
        or any(c in _BAD_CHARS or ord(c) < 32 or ord(c) == 127 for c in p)
        or len(p.encode("utf-8")) > 255
        or p.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
        for p in parts
    ):
        raise _error(f"unsafe archive path: {name!r}")
    return parts


def _resolve(base: str, path: str, *, root: bool = True) -> Path:
    if path:
        _name_parts(path)
    elif not root:
        raise _error("select a file or folder, not the server root")
    return file_safety.resolve_within(base, path)


def _decoder() -> tuple[str, str] | None:
    for tool in ("unrar", "rar", "bsdtar"):
        if executable := shutil.which(tool):
            return tool, executable
    # Windows ships libarchive's bsdtar under the name tar.exe. Do not mistake
    # GNU tar or another unrelated tar implementation for a RAR decoder.
    if os.name == "nt" and (executable := shutil.which("tar")):
        try:
            version = subprocess.run(
                [executable, "--version"], capture_output=True, timeout=2, shell=False
            )
            if version.returncode == 0 and version.stdout.startswith(b"bsdtar "):
                return "bsdtar", executable
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def capabilities() -> dict[str, bool]:
    return {
        "zip": True,
        "rar_extract": _decoder() is not None,
        "rar_compress": shutil.which("rar") is not None,
    }


def _directory(path: Path, *, missing: bool = False) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        if missing:
            return
        raise _error("destination directory not found", 404) from None
    if not stat.S_ISDIR(mode):
        raise _error("destination is not a directory")


def _validate_members(members: list[Member], deadline: float) -> None:
    if len(members) > MAX_MEMBERS:
        raise _error(f"archive exceeds the {MAX_MEMBERS} entry limit", 413)
    total = 0
    entries: dict[str, bool] = {}
    required_dirs: set[str] = set()
    for member in members:
        _check_time(deadline)
        parts = _name_parts(member.name, directory=member.directory)
        key = "/".join(parts).casefold()
        if key in entries:
            raise _error(f"duplicate archive path: {member.name}")
        if (not member.directory and key in required_dirs) or any(
            entries.get("/".join(parts[:i]).casefold()) is False for i in range(1, len(parts))
        ):
            raise _error(f"archive file/directory conflict: {member.name}")
        entries[key] = member.directory
        required_dirs.update("/".join(parts[:i]).casefold() for i in range(1, len(parts)))
        if member.size < 0:
            raise _error("invalid archive member size")
        total += member.size
        if total > MAX_BYTES:
            raise _error(f"archive exceeds the {MAX_BYTES // 1024**3} GiB byte limit", 413)


def _zip_members(archive: zipfile.ZipFile) -> list[Member]:
    members = []
    if len(archive.infolist()) > MAX_MEMBERS:
        raise _error(f"archive exceeds the {MAX_MEMBERS} entry limit", 413)
    for info in archive.infolist():
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise _error(f"archive links and special files are not allowed: {info.filename}")
        if info.flag_bits & 1:
            raise _error("password-protected archives are not supported")
        if info.orig_filename != info.filename:
            raise _error("unsafe archive filename")
        members.append(Member(info.filename, info.is_dir(), info.file_size, info, mode & 0o111))
    return members


def _rar_members(archive: rarfile.RarFile) -> list[Member]:
    members = []
    if len(archive.infolist()) > MAX_MEMBERS:
        raise _error(f"archive exceeds the {MAX_MEMBERS} entry limit", 413)
    if archive.needs_password():
        raise _error("password-protected archives are not supported")
    if len(archive.volumelist()) != 1:
        raise _error("multipart RAR archives are not supported")
    for info in archive.infolist():
        mode = getattr(info, "mode", 0)
        # file_redir includes hardlinks and other RAR5 redirections.
        if (
            info.is_symlink()
            or getattr(info, "file_redir", None)
            or (
                info.host_os == rarfile.RAR_OS_UNIX
                and stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
            )
        ):
            raise _error(f"archive links and special files are not allowed: {info.filename}")
        members.append(
            Member(
                info.filename,
                info.is_dir(),
                info.file_size,
                info,
                mode & 0o111 if info.host_os == rarfile.RAR_OS_UNIX else 0,
            )
        )
    return members


def _preflight(base: str, dest: Path, members: list[Member]) -> None:
    _directory(dest, missing=True)
    for member in members:
        target = dest.joinpath(*_name_parts(member.name, directory=member.directory))
        file_safety.resolve_within(base, target.relative_to(Path(base).resolve()).as_posix())
        for parent in target.parents:
            if parent == Path(base).resolve().parent:
                break
            if parent.exists() and not parent.is_dir():
                raise _error(f"destination file/directory conflict: {member.name}", 409)
        if target.exists() and not (member.directory and target.is_dir()):
            raise _error(f"already exists at destination: {member.name}", 409)


def _copy(src: BinaryIO, dst: BinaryIO, deadline: float, limit: int) -> int:
    size = 0
    while True:
        _check_time(deadline)
        chunk = src.read(CHUNK_SIZE)
        if not chunk:
            return size
        size += len(chunk)
        if size > limit:
            raise _error(
                f"archive exceeds its declared size or {MAX_BYTES // 1024**3} GiB limit", 413
            )
        dst.write(chunk)


def _rar_stream(command: list[str], dst: BinaryIO, deadline: float, limit: int) -> int:
    """Read a decoder pipe with bounded buffering and a deadline, even if it hangs."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        shell=False,
    )
    chunks: queue.Queue[bytes | Exception | None] = queue.Queue(maxsize=2)
    stopped = threading.Event()

    def reader() -> None:
        try:
            while not stopped.is_set():
                chunk = process.stdout.read(CHUNK_SIZE)
                item = chunk or None
                while not stopped.is_set():
                    try:
                        chunks.put(item, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                if not chunk:
                    return
        except Exception as exc:
            with suppress(queue.Full):
                chunks.put(exc, timeout=0.1)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    size = 0
    try:
        while True:
            _check_time(deadline)
            try:
                chunk = chunks.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty:
                _check_time(deadline)
                raise _error("RAR decoder timed out", 413) from None
            if isinstance(chunk, Exception):
                raise chunk
            if chunk is None:
                break
            size += len(chunk)
            if size > limit:
                raise _error("RAR member exceeds its declared size", 413)
            dst.write(chunk)
        if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
            raise _error("RAR extraction failed; the archive may be corrupt or unsupported")
        return size
    finally:
        stopped.set()
        if process.poll() is None:
            process.kill()
        process.wait()
        thread.join(timeout=2)
        process.stdout.close()


def _make_dirs(base: str, target: Path, created: list[CreatedEntry]) -> None:
    if target == Path(base).resolve():
        return
    file_safety.resolve_within(base, target.relative_to(Path(base).resolve()).as_posix())
    if target.exists():
        _directory(target)
        return
    _make_dirs(base, target.parent, created)
    mkdir_inherit_owner(target)
    created.append(CreatedEntry.from_stat(target, target.lstat()))


def _rollback_created(base: str, created: list[CreatedEntry]) -> None:
    for entry in reversed(created):
        # Other file routes and external writers can replace entries while this
        # operation runs. Their replacements are not ours to remove.
        with suppress(OSError, HTTPException, ValueError):
            file_safety.resolve_within(
                base, entry.path.parent.relative_to(Path(base).resolve()).as_posix()
            )
            current = entry.path.lstat()
            if (current.st_dev, current.st_ino) != (entry.device, entry.inode):
                continue
            if entry.directory:
                if stat.S_ISDIR(current.st_mode):
                    entry.path.rmdir()  # Refuses to remove any new contents.
            elif stat.S_ISREG(current.st_mode):
                entry.path.unlink()


def _publish(
    base: str, stage: Path, dest: Path, members: list[Member], deadline: float | None = None
) -> None:
    # Recheck after decoding. Exclusive links cannot silently replace a racing writer.
    _preflight(base, dest, members)
    created: list[CreatedEntry] = []
    try:
        _make_dirs(base, dest, created)
        for member in members:
            if deadline is not None:
                _check_time(deadline)
            relative = "/".join(_name_parts(member.name, directory=member.directory))
            target = dest / relative
            _make_dirs(base, target if member.directory else target.parent, created)
            if not member.directory:
                file_safety.resolve_within(
                    base, target.relative_to(Path(base).resolve()).as_posix()
                )
                _adopt_ownership(stage / relative, target)
                os.chmod(stage / relative, 0o644 | member.executable_bits)
                identity = CreatedEntry.from_stat(target, (stage / relative).lstat())
                os.link(stage / relative, target)
                created.append(identity)
    except Exception:
        _rollback_created(base, created)
        raise


def extract(base: str, path: str, dest_dir: str) -> None:
    source = _resolve(base, path, root=False)
    source_info = file_safety.stat_regular_file(source)
    if source_info.st_size > MAX_BYTES:
        raise _error(f"archive exceeds the {MAX_BYTES // 1024**3} GiB byte limit", 413)
    dest = _resolve(base, dest_dir)
    deadline = time.monotonic() + MAX_SECONDS
    suffix = source.suffix.lower()
    if suffix not in {".zip", ".rar"}:
        raise _error("only ZIP and RAR archives can be extracted")
    decoder = _decoder() if suffix == ".rar" else None
    if suffix == ".rar" and decoder is None:
        raise _error("RAR extraction unavailable: install bsdtar, unrar or rar on the host", 501)
    try:
        with (
            zipfile.ZipFile(source)
            if suffix == ".zip"
            else rarfile.RarFile(source, errors="strict") as archive
        ):
            members = _zip_members(archive) if suffix == ".zip" else _rar_members(archive)
            _validate_members(members, deadline)
            _preflight(base, dest, members)
            with tempfile.TemporaryDirectory(prefix=".mcontrol-archive-", dir=base) as temporary:
                stage = Path(temporary)
                for member in members:
                    _check_time(deadline)
                    target = stage.joinpath(*_name_parts(member.name, directory=member.directory))
                    if member.directory:
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as output:
                        if suffix == ".zip":
                            with archive.open(member.info) as input_file:
                                size = _copy(input_file, output, deadline, member.size)
                        else:
                            tool, executable = decoder
                            command = (
                                [
                                    executable,
                                    "-xOf",
                                    str(source),
                                    "--",
                                    member.name.replace("[", r"\[").replace("]", r"\]"),
                                ]
                                if tool == "bsdtar"
                                else [
                                    executable,
                                    "p",
                                    "-inul",
                                    "-p-",
                                    "--",
                                    str(source),
                                    member.name,
                                ]
                            )
                            size = _rar_stream(command, output, deadline, member.size)
                    if size != member.size:
                        raise _error(f"corrupt archive member: {member.name}")
                _check_time(deadline)
                _publish(base, stage, dest, members, deadline)
    except HTTPException:
        raise
    except subprocess.TimeoutExpired as exc:
        raise _error(f"archive operation exceeds the {MAX_SECONDS} second limit", 413) from exc
    except (
        zipfile.BadZipFile,
        zlib.error,
        rarfile.Error,
        OSError,
        RuntimeError,
        NotImplementedError,
        EOFError,
        ValueError,
    ) as exc:
        raise _error(
            f"archive extraction failed: {exc}", 409 if isinstance(exc, FileExistsError) else 400
        ) from exc


def _source_plan(base: str, paths: list[str], deadline: float) -> tuple[Path, list[Member]]:
    if not paths:
        raise _error("no files selected")
    targets = {_resolve(base, path, root=False) for path in paths}
    roots = sorted(p for p in targets if not any(parent in targets for parent in p.parents))
    ancestor = Path(os.path.commonpath([str(p.parent) for p in roots]))
    members: list[Member] = []

    def walk(target: Path) -> Iterator[tuple[Path, os.stat_result]]:
        _check_time(deadline)
        file_safety.resolve_within(base, target.relative_to(Path(base).resolve()).as_posix())
        try:
            info = target.lstat()
        except FileNotFoundError:
            raise _error(f"selected path not found: {target.name}", 404) from None
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise _error(f"links and special files cannot be compressed: {target.name}")
        yield target, info
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(target.iterdir()):
                yield from walk(child)

    for root in roots:
        for target, info in walk(root):
            directory = stat.S_ISDIR(info.st_mode)
            members.append(
                Member(
                    target.relative_to(ancestor).as_posix(),
                    directory,
                    0 if directory else info.st_size,
                    (target, info),
                )
            )
            if len(members) > MAX_MEMBERS:
                raise _error(f"selection exceeds the {MAX_MEMBERS} entry limit", 413)
    _validate_members(members, deadline)
    return ancestor, members


def _source_open(base: str, target: Path, expected: os.stat_result) -> BinaryIO:
    file_safety.resolve_within(base, target.relative_to(Path(base).resolve()).as_posix())
    descriptor = os.open(
        target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    )
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (
        expected.st_dev,
        expected.st_ino,
    ):
        os.close(descriptor)
        raise _error("selected file changed while compressing")
    return os.fdopen(descriptor, "rb")


def compress(
    base: str, paths: list[str], dest_dir: str, archive_name: str, archive_format: str
) -> None:
    if archive_format not in {"zip", "rar"}:
        raise _error("archive format must be zip or rar")
    if len(_name_parts(archive_name)) != 1 or not archive_name.lower().endswith(
        f".{archive_format}"
    ):
        raise _error(f"archive name must be a single .{archive_format} filename")
    executable = shutil.which("rar") if archive_format == "rar" else None
    if archive_format == "rar" and executable is None:
        raise _error("RAR creation unavailable: install the licensed rar tool on the host", 501)
    dest = _resolve(base, dest_dir)
    _directory(dest)
    output = _resolve(base, (dest.relative_to(Path(base).resolve()) / archive_name).as_posix())
    if output.exists():
        raise _error(f"already exists: {archive_name}", 409)
    deadline = time.monotonic() + MAX_SECONDS
    try:
        _, members = _source_plan(base, paths, deadline)
        with tempfile.TemporaryDirectory(prefix=".mcontrol-archive-", dir=base) as temporary:
            stage = Path(temporary)
            archive_path = stage / archive_name
            if archive_format == "zip":
                with zipfile.ZipFile(
                    archive_path, "w", compression=zipfile.ZIP_DEFLATED
                ) as archive:
                    for member in members:
                        _check_time(deadline)
                        if member.directory:
                            archive.writestr(member.name + "/", b"")
                        else:
                            target, info = member.info
                            entry = zipfile.ZipInfo(member.name)
                            entry.create_system = 3
                            entry.external_attr = (
                                stat.S_IFREG | 0o644 | (info.st_mode & 0o111)
                            ) << 16
                            entry.compress_type = zipfile.ZIP_DEFLATED
                            with (
                                _source_open(base, target, info) as source,
                                archive.open(entry, "w", force_zip64=True) as packed,
                            ):
                                size = _copy(source, packed, deadline, member.size)
                            if size != member.size:
                                raise _error("selected file changed while compressing")
            else:
                inputs = stage / "input"
                inputs.mkdir()
                for member in members:
                    target = inputs / member.name
                    if member.directory:
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        source_path, info = member.info
                        with (
                            _source_open(base, source_path, info) as source,
                            target.open("xb") as dst,
                        ):
                            if _copy(source, dst, deadline, member.size) != member.size:
                                raise _error("selected file changed while compressing")
                        os.chmod(target, 0o644 | (info.st_mode & 0o111))
                _check_time(deadline)
                result = subprocess.run(
                    [executable, "a", "-r", "-idq", "-y", "-ep1", "--", str(archive_path), "."],
                    cwd=inputs,
                    timeout=max(0.001, deadline - time.monotonic()),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
                if result.returncode != 0 or not archive_path.is_file():
                    raise _error("RAR creation failed")
            _check_time(deadline)
            _resolve(base, output.relative_to(Path(base).resolve()).as_posix())
            _adopt_ownership(archive_path, output)
            os.link(archive_path, output)
    except HTTPException:
        raise
    except subprocess.TimeoutExpired as exc:
        raise _error(f"archive operation exceeds the {MAX_SECONDS} second limit", 413) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise _error(
            f"archive creation failed: {exc}", 409 if isinstance(exc, FileExistsError) else 400
        ) from exc
