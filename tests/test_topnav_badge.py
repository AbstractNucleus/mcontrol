"""Tests for the topnav tombstone count badge (slice 15, decision 035)."""

import time

import pytest
from httpx import ASGITransport, AsyncClient

from mcontrol import tombstones


def _make_tombstone(parent, original_name: str, *, age_seconds: int = 0) -> None:
    """Create a .deleted-<name>-<unix-ts>/ directory under `parent`."""
    ts = int(time.time()) - age_seconds
    d = parent / f".deleted-{original_name}-{ts}"
    d.mkdir()


# ---------- tombstones.count() ---------------------------------------------


def test_count_returns_zero_for_empty_base(tmp_path):
    assert tombstones.count(tmp_path) == 0


def test_count_returns_zero_when_base_missing(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert tombstones.count(missing) == 0


def test_count_counts_only_tombstones(tmp_path):
    # tombstones
    _make_tombstone(tmp_path, "atm10")
    _make_tombstone(tmp_path, "monifactory")
    # non-tombstones — must NOT count
    (tmp_path / "regular-server").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".deleted-incomplete").mkdir()  # no trailing -<ts>
    (tmp_path / "loose-file.txt").write_text("x")

    assert tombstones.count(tmp_path) == 2


def test_count_skips_symlinks_with_tombstone_names(tmp_path):
    real_target = tmp_path / "elsewhere"
    real_target.mkdir()
    link = tmp_path / ".deleted-atm10-1700000000"
    try:
        link.symlink_to(real_target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this filesystem")

    assert tombstones.count(tmp_path) == 0


# ---------- topnav badge render ---------------------------------------------


@pytest.fixture
def env_with_base(monkeypatch, tmp_path):
    """Override the conftest env so SERVER_BASE_PATH is a real tmp dir
    we can populate with tombstone-shaped directories."""
    monkeypatch.setenv("SUPABASE_URL", "https://api.noelkleen.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_servers(monkeypatch):
    rows: list[dict] = []
    from mcontrol import db
    monkeypatch.setattr(db, "list_servers", lambda: rows)
    return rows


@pytest.fixture
def fake_stats(monkeypatch):
    async def fake_read(_docker, container_name: str):
        return {"status": "unreachable"}
    from mcontrol import resources
    monkeypatch.setattr(resources, "read_container_stats", fake_read)


async def _fresh_client():
    """Build a fresh client AFTER the env fixture has set SERVER_BASE_PATH —
    the conftest's client fixture caches a Settings instance at app creation
    time, so we need a new app for these tests."""
    from mcontrol.main import create_app
    from tests.conftest import make_fake_docker

    app = create_app()
    # ASGITransport doesn't run lifespan, so populate app.state.docker
    # ourselves — Depends(get_docker) on every route requires it (#98).
    app.state.docker = make_fake_docker()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_topnav_omits_badge_when_no_tombstones(
    env_with_base, fake_servers, fake_stats
):
    async with await _fresh_client() as ac:
        response = await ac.get("/")

    body = response.text
    assert response.status_code == 200
    assert "topnav__badge" not in body


async def test_topnav_renders_badge_with_count(
    env_with_base, fake_servers, fake_stats
):
    _make_tombstone(env_with_base, "atm10")
    _make_tombstone(env_with_base, "monifactory")
    _make_tombstone(env_with_base, "kobra")

    async with await _fresh_client() as ac:
        response = await ac.get("/")

    body = response.text
    assert response.status_code == 200
    assert "topnav__badge" in body
    # Badge contains the count text — pull just the span to assert.
    badge_open = body.index('class="topnav__badge"')
    badge_close = body.index("</span>", badge_open)
    badge_chunk = body[badge_open:badge_close]
    # The span body is the count number; assert it's the trailing chars.
    assert badge_chunk.rstrip().endswith(">3")


async def test_topnav_badge_visible_from_non_home_pages(
    env_with_base, monkeypatch, fake_stats
):
    """Badge renders on every page that includes _topnav.html. Spot-check
    /trash, which has its own route + template path."""
    _make_tombstone(env_with_base, "atm10")

    async with await _fresh_client() as ac:
        response = await ac.get("/trash")

    body = response.text
    assert response.status_code == 200
    assert "topnav__badge" in body
