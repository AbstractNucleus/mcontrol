"""Unit tests for infra.compose — subprocess is always mocked."""

import asyncio

import pytest

from mcontrol.infra import compose


class _FakeProc:
    def __init__(self, returncode=0, stdout=b"", stderr=b"", hang=False):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False
        self._hang = hang

    async def communicate(self):
        if self._hang and not self.killed:
            await asyncio.sleep(30)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


async def test_compose_up_runs_expected_argv(tmp_path, monkeypatch):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    seen: dict = {}

    async def fake_exec(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await compose.compose_up(tmp_path)

    assert seen["args"] == (
        "docker",
        "compose",
        "-f",
        str(tmp_path / "docker-compose.yml"),
        "--project-directory",
        str(tmp_path),
        "up",
        "-d",
    )
    assert seen["kwargs"]["stdout"] == asyncio.subprocess.PIPE
    assert seen["kwargs"]["stderr"] == asyncio.subprocess.PIPE


async def test_compose_up_raises_when_compose_file_missing(tmp_path):
    with pytest.raises(compose.ComposeError, match="no docker-compose.yml"):
        await compose.compose_up(tmp_path)


async def test_compose_up_raises_on_missing_binary(tmp_path, monkeypatch):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")

    async def fake_exec(*_a, **_k):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with pytest.raises(compose.ComposeError, match="docker CLI not found"):
        await compose.compose_up(tmp_path)


async def test_compose_up_raises_on_nonzero_with_stderr_tail(tmp_path, monkeypatch):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")

    async def fake_exec(*_a, **_k):
        return _FakeProc(returncode=1, stderr=b"no such image: eclipse-temurin")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with pytest.raises(compose.ComposeError, match="no such image"):
        await compose.compose_up(tmp_path)


async def test_compose_up_raises_on_timeout(tmp_path, monkeypatch):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    proc = _FakeProc(hang=True)

    async def fake_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with pytest.raises(compose.ComposeError, match="timed out"):
        await compose.compose_up(tmp_path, timeout_s=0.05)
    assert proc.killed is True


def test_compose_error_is_exception():
    assert issubclass(compose.ComposeError, Exception)
