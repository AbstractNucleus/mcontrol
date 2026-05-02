from pathlib import Path

import pytest

from mcontrol import compose_runner


class _FakeProcess:
    def __init__(self, returncode: int, stderr: bytes = b""):
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return (b"", self._stderr)


@pytest.fixture
def captured_exec(monkeypatch):
    """Capture the args to asyncio.create_subprocess_exec, return a configurable fake."""
    seen: dict[str, object] = {}

    async def factory(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return seen.get("process", _FakeProcess(returncode=0))

    monkeypatch.setattr(compose_runner.asyncio, "create_subprocess_exec", factory)
    return seen


async def test_up_force_recreate_invokes_docker_compose_with_compose_file(captured_exec):
    await compose_runner.up_force_recreate(Path("/srv/atm10"))

    args = captured_exec["args"]
    assert args[0] == "docker"
    assert "compose" in args
    assert "-f" in args
    assert any(str(Path("/srv/atm10/docker-compose.yml")) == a for a in args)
    assert "up" in args
    assert "-d" in args
    assert "--force-recreate" in args


async def test_up_force_recreate_raises_on_nonzero_exit(captured_exec):
    captured_exec["process"] = _FakeProcess(returncode=1, stderr=b"compose: ENOENT")

    with pytest.raises(compose_runner.ComposeError) as exc_info:
        await compose_runner.up_force_recreate(Path("/srv/atm10"))

    assert "compose: ENOENT" in str(exc_info.value)


async def test_up_force_recreate_succeeds_on_zero_exit(captured_exec):
    captured_exec["process"] = _FakeProcess(returncode=0)

    # Should not raise.
    await compose_runner.up_force_recreate(Path("/srv/atm10"))
