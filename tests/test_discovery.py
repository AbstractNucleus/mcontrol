from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mcontrol import discovery


@pytest.fixture
def upserts(monkeypatch):
    calls: list[dict] = []

    def fake_upsert_server(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(discovery.db, "upsert_server", fake_upsert_server)
    return calls


def _make_dirs(base: Path, names: list[str]) -> None:
    for n in names:
        (base / n).mkdir(parents=True, exist_ok=True)


async def test_run_discovery_skips_when_base_path_missing(tmp_path, upserts, monkeypatch):
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(tmp_path / "does-not-exist")

    assert count == 0
    assert upserts == []


async def test_run_discovery_returns_zero_when_no_subdirs(tmp_path, upserts, monkeypatch):
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(tmp_path)

    assert count == 0
    assert upserts == []


async def test_run_discovery_upserts_one_row_per_subdir(tmp_path, upserts, monkeypatch):
    _make_dirs(tmp_path, ["atm10", "monifactory", "kobra_kollektivet"])
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={"atm10": "running", "monifactory": "exited"}),
    )

    count = await discovery.run_discovery(tmp_path)

    assert count == 3
    by_name = {u["name"]: u for u in upserts}
    assert by_name["atm10"] == {
        "name": "atm10",
        "dir": str(tmp_path / "atm10"),
        "state": "running",
    }
    assert by_name["monifactory"]["state"] == "exited"
    assert by_name["kobra_kollektivet"]["state"] == "unknown"


async def test_run_discovery_ignores_non_directories(tmp_path, upserts, monkeypatch):
    _make_dirs(tmp_path, ["atm10"])
    (tmp_path / "stray-file.txt").write_text("ignore me")
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(tmp_path)

    assert count == 1
    assert [u["name"] for u in upserts] == ["atm10"]


async def test_run_discovery_processes_dirs_in_sorted_order(tmp_path, upserts, monkeypatch):
    _make_dirs(tmp_path, ["zeta", "alpha", "mu"])
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    await discovery.run_discovery(tmp_path)

    assert [u["name"] for u in upserts] == ["alpha", "mu", "zeta"]
