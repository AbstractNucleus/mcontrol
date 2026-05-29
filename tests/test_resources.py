"""Tests for the resources module (slice 9 PR 0).

Three units under test:
  - read_container_stats  → faked aiodocker; covers ok / not-running /
                            unreachable and the cgroup v1 / v2 / raw
                            memory branches plus the zero-delta first-tick
                            CPU edge.
  - read_disk_usage       → tmp_path; covers nested files, hidden files,
                            and the never-follow-symlinks contract.
  - format_bytes          → table-driven; covers the unit boundaries.
"""

import sys

import pytest

from mcontrol.infra import resources

# ---------------------------------------------------------------------------
# read_container_stats. faked aiodocker
# ---------------------------------------------------------------------------


def _stats_payload(
    *,
    cpu_total: int = 200,
    pre_cpu_total: int = 100,
    sys_total: int = 1000,
    pre_sys_total: int = 500,
    online_cpus: int = 4,
    mem_usage: int = 4 * 1024 * 1024 * 1024,
    mem_limit: int = 12 * 1024 * 1024 * 1024,
    mem_stats: dict | None = None,
) -> dict:
    return {
        "cpu_stats": {
            "cpu_usage": {"total_usage": cpu_total},
            "system_cpu_usage": sys_total,
            "online_cpus": online_cpus,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": pre_cpu_total},
            "system_cpu_usage": pre_sys_total,
        },
        "memory_stats": {
            "usage": mem_usage,
            "limit": mem_limit,
            "stats": mem_stats if mem_stats is not None else {},
        },
    }


def _fake_docker(*, container=None, get_raises: bool = False):
    """Build a fake aiodocker.Docker instance with a configured container.

    The single-client refactor (#98) means resources.read_container_stats
    receives the client as an argument rather than constructing one; tests
    just hand back a fake instance.
    """

    class _Containers:
        async def get(self, name):  # noqa: ARG002
            if get_raises:
                raise RuntimeError("404 not found")
            return container

    class _Docker:
        def __init__(self):
            self.containers = _Containers()

    return _Docker()


class _FakeContainer:
    def __init__(self, *, running: bool = True, payload: dict | None = None):
        self._running = running
        self._payload = payload if payload is not None else _stats_payload()
        self._stats_raises = False
        self._show_raises = False

    async def show(self):
        if self._show_raises:
            raise RuntimeError("show failed")
        return {"State": {"Running": self._running}}

    async def stats(self, *, stream: bool):
        assert stream is False, "card uses single-snapshot stream=false"
        if self._stats_raises:
            raise RuntimeError("stats failed")
        # aiodocker returns a list when stream=False; mirror that.
        return [self._payload]


async def test_read_stats_returns_unreachable_when_container_missing(env):
    docker = _fake_docker(get_raises=True)
    assert await resources.read_container_stats(docker, "atm10") == {"status": "unreachable"}


async def test_read_stats_returns_not_running_when_state_is_stopped(env):
    docker = _fake_docker(container=_FakeContainer(running=False))
    assert await resources.read_container_stats(docker, "atm10") == {"status": "not-running"}


async def test_read_stats_returns_unreachable_when_stats_call_raises(env):
    container = _FakeContainer(running=True)
    container._stats_raises = True
    docker = _fake_docker(container=container)
    assert await resources.read_container_stats(docker, "atm10") == {"status": "unreachable"}


async def test_read_stats_ok_with_known_inputs_matches_docker_stats_math(env):
    # cpu_delta=100, sys_delta=500, online=4 → (100/500)*4*100 = 80.0
    payload = _stats_payload(
        cpu_total=200,
        pre_cpu_total=100,
        sys_total=1000,
        pre_sys_total=500,
        online_cpus=4,
        mem_usage=8 * 1024**3,
        mem_limit=12 * 1024**3,
        mem_stats={"inactive_file": 1 * 1024**3},
    )
    docker = _fake_docker(container=_FakeContainer(payload=payload))

    result = await resources.read_container_stats(docker, "atm10")

    assert result["status"] == "ok"
    assert result["cpu_percent"] == pytest.approx(80.0)
    # mem_used = usage - inactive_file = 8 GiB - 1 GiB = 7 GiB
    assert result["mem_used"] == 7 * 1024**3
    assert result["mem_limit"] == 12 * 1024**3


async def test_read_stats_uses_cache_when_inactive_file_absent_cgroup_v1(env):
    payload = _stats_payload(
        mem_usage=8 * 1024**3,
        mem_stats={"cache": 2 * 1024**3},
    )
    docker = _fake_docker(container=_FakeContainer(payload=payload))

    result = await resources.read_container_stats(docker, "atm10")

    # mem_used = usage - cache = 6 GiB
    assert result["mem_used"] == 6 * 1024**3


async def test_read_stats_falls_back_to_raw_usage_when_neither_present(env):
    payload = _stats_payload(
        mem_usage=5 * 1024**3,
        mem_stats={},
    )
    docker = _fake_docker(container=_FakeContainer(payload=payload))

    result = await resources.read_container_stats(docker, "atm10")

    assert result["mem_used"] == 5 * 1024**3


async def test_read_stats_zero_cpu_delta_returns_zero(env):
    """First-tick edge: precpu_stats == cpu_stats means deltas are zero."""
    payload = _stats_payload(
        cpu_total=100,
        pre_cpu_total=100,
        sys_total=500,
        pre_sys_total=500,
    )
    docker = _fake_docker(container=_FakeContainer(payload=payload))

    result = await resources.read_container_stats(docker, "atm10")

    assert result["cpu_percent"] == 0.0


async def test_read_stats_handles_dict_return_shape(env):
    """Defensive: some aiodocker versions return a dict, not a list."""

    class _DictContainer(_FakeContainer):
        async def stats(self, *, stream: bool):  # noqa: ARG002
            return self._payload

    docker = _fake_docker(container=_DictContainer())
    result = await resources.read_container_stats(docker, "atm10")
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# read_disk_usage
# ---------------------------------------------------------------------------


def test_read_disk_usage_empty_dir_is_zero(tmp_path):
    assert resources.read_disk_usage(tmp_path) == 0


def test_read_disk_usage_missing_dir_is_zero(tmp_path):
    assert resources.read_disk_usage(tmp_path / "nope") == 0


def test_read_disk_usage_sums_nested_files(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 100)
    sub = tmp_path / "mods"
    sub.mkdir()
    (sub / "b.jar").write_bytes(b"y" * 250)
    deeper = sub / "config"
    deeper.mkdir()
    (deeper / "c.toml").write_bytes(b"z" * 50)

    assert resources.read_disk_usage(tmp_path) == 400


def test_read_disk_usage_includes_dot_prefixed_files(tmp_path):
    (tmp_path / ".env").write_bytes(b"a" * 40)
    (tmp_path / "visible.txt").write_bytes(b"b" * 10)

    assert resources.read_disk_usage(tmp_path) == 50


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_read_disk_usage_does_not_follow_file_symlinks(tmp_path):
    """A symlink contributes only its own inode bytes. the target's
    payload is not double-counted."""
    target = tmp_path / "target.bin"
    target.write_bytes(b"x" * 1000)
    link = tmp_path / "link.bin"
    link.symlink_to(target)

    total = resources.read_disk_usage(tmp_path)

    link_size = link.lstat().st_size  # length of the link's stored target path
    assert total == 1000 + link_size


def test_read_disk_usage_cache_hit_avoids_walk(tmp_path, monkeypatch):
    """Second call with unchanged root mtime returns the cached value without re-walking."""
    (tmp_path / "f.bin").write_bytes(b"x" * 50)

    assert resources.read_disk_usage(tmp_path) == 50

    walk_count = {"n": 0}
    real_scandir = resources.os.scandir

    def counting_scandir(path):
        walk_count["n"] += 1
        return real_scandir(path)

    monkeypatch.setattr(resources.os, "scandir", counting_scandir)

    assert resources.read_disk_usage(tmp_path) == 50
    assert walk_count["n"] == 0


def test_read_disk_usage_cache_invalidated_on_root_mtime_change(tmp_path):
    """Writing a file directly to root advances the root mtime and forces a re-walk."""
    (tmp_path / "f.bin").write_bytes(b"x" * 50)

    assert resources.read_disk_usage(tmp_path) == 50

    (tmp_path / "g.bin").write_bytes(b"y" * 70)

    assert resources.read_disk_usage(tmp_path) == 120


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_read_disk_usage_does_not_recurse_into_directory_symlinks(tmp_path):
    """A symlink-to-directory is treated as a leaf. the target's
    contents are not walked. This is what stops an operator-introduced
    backup-dir symlink from inflating the number."""
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (outside / "huge.bin").write_bytes(b"x" * 5000)

    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "small.bin").write_bytes(b"y" * 30)
    (server_dir / "linkdir").symlink_to(outside, target_is_directory=True)

    total = resources.read_disk_usage(server_dir)

    link_size = (server_dir / "linkdir").lstat().st_size
    assert total == 30 + link_size


# ---------------------------------------------------------------------------
# format_bytes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "0 B"),
        (512, "512 B"),
        (1023, "1023 B"),
        (1024, "1.0 KiB"),
        (1536, "1.5 KiB"),
        (1024 * 1024, "1.0 MiB"),
        (8 * 1024**3, "8.0 GiB"),
        (12 * 1024**3, "12.0 GiB"),
        (1024**4, "1.0 TiB"),
        (5 * 1024**4, "5.0 TiB"),
    ],
)
def test_format_bytes(value, expected):
    assert resources.format_bytes(value) == expected
