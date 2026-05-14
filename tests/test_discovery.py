from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mcontrol.domain import discovery


@pytest.fixture
def db_calls(monkeypatch):
    """Capture every db call discovery makes — order matters for the assertions."""
    calls: list[tuple[str, dict]] = []

    _existing_rows: dict[str, dict | None] = {}

    def fake_get_server(name):
        # Default: row does not exist. Tests override per-name by setting
        # discovery._existing_rows on the fixture before calling.
        return _existing_rows.get(name)

    def fake_insert_server(**kwargs):
        calls.append(("insert", kwargs))

    def fake_update_server_state(**kwargs):
        calls.append(("update_state", kwargs))

    monkeypatch.setattr(discovery.db, "get_server", fake_get_server)
    monkeypatch.setattr(discovery.db, "insert_server", fake_insert_server)
    monkeypatch.setattr(discovery.db, "update_server_state", fake_update_server_state)

    return {"calls": calls, "existing": _existing_rows}


def _make_dirs(base: Path, names: list[str]) -> None:
    for n in names:
        (base / n).mkdir(parents=True, exist_ok=True)


async def test_run_discovery_skips_when_base_path_missing(tmp_path, db_calls, monkeypatch):
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(object(),tmp_path / "does-not-exist")

    assert count == 0
    assert db_calls["calls"] == []


async def test_run_discovery_inserts_new_dirs(tmp_path, db_calls, monkeypatch):
    _make_dirs(tmp_path, ["atm10", "monifactory"])
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={"atm10": "running"}),
    )

    count = await discovery.run_discovery(object(),tmp_path)

    assert count == 2
    inserts = [c for c in db_calls["calls"] if c[0] == "insert"]
    updates = [c for c in db_calls["calls"] if c[0] == "update_state"]
    assert {i[1]["name"] for i in inserts} == {"atm10", "monifactory"}
    assert updates == []
    assert next(i for i in inserts if i[1]["name"] == "atm10")[1] == {
        "name": "atm10",
        "dir": str(tmp_path / "atm10"),
        "state": "running",
    }


async def test_run_discovery_updates_state_only_for_existing_rows(tmp_path, db_calls, monkeypatch):
    _make_dirs(tmp_path, ["atm10"])
    db_calls["existing"]["atm10"] = {
        "name": "atm10",
        "dir": "/operator/edited/path/atm10",
        "container_name": "atm10-prod",
        "state": "exited",
    }
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={"atm10-prod": "running"}),
    )

    count = await discovery.run_discovery(object(),tmp_path)

    assert count == 1
    inserts = [c for c in db_calls["calls"] if c[0] == "insert"]
    updates = [c for c in db_calls["calls"] if c[0] == "update_state"]
    # No insert — operator-edited row is preserved.
    assert inserts == []
    # Only state is refreshed; dir and container_name untouched.
    assert updates == [("update_state", {"name": "atm10", "state": "running"})]


async def test_run_discovery_falls_back_to_unknown_when_docker_silent(
    tmp_path, db_calls, monkeypatch
):
    _make_dirs(tmp_path, ["atm10"])
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(object(),tmp_path)

    assert count == 1
    inserts = [c for c in db_calls["calls"] if c[0] == "insert"]
    assert inserts[0][1]["state"] == "unknown"


async def test_run_discovery_ignores_non_directories(tmp_path, db_calls, monkeypatch):
    _make_dirs(tmp_path, ["atm10"])
    (tmp_path / "stray-file.txt").write_text("ignore me")
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(object(),tmp_path)

    assert count == 1


async def test_run_discovery_processes_dirs_in_sorted_order(tmp_path, db_calls, monkeypatch):
    _make_dirs(tmp_path, ["zeta", "alpha", "mu"])
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    await discovery.run_discovery(object(),tmp_path)

    seen = [c[1]["name"] for c in db_calls["calls"]]
    assert seen == ["alpha", "mu", "zeta"]


async def test_run_discovery_skips_dot_prefixed_directories(
    tmp_path, db_calls, monkeypatch
):
    """Decision 026: tombstoned dirs (.deleted-foo-...), .git, and other
    dot-prefixed utility dirs must not appear as servers."""
    _make_dirs(
        tmp_path,
        ["atm10", ".deleted-monifactory-1735689600", ".git", ".cache"],
    )
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(object(),tmp_path)

    assert count == 1
    seen = [c[1]["name"] for c in db_calls["calls"]]
    assert seen == ["atm10"]


async def test_run_discovery_state_lookup_uses_container_name_override(
    tmp_path, db_calls, monkeypatch
):
    """When a row has container_name override, state is looked up under that name."""
    _make_dirs(tmp_path, ["atm10"])
    db_calls["existing"]["atm10"] = {
        "name": "atm10",
        "container_name": "atm10-prod",
        "dir": str(tmp_path / "atm10"),
        "state": "exited",
    }
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        # The override "atm10-prod" is what's running; the row's name "atm10"
        # is not a real container.
        AsyncMock(return_value={"atm10-prod": "running"}),
    )

    await discovery.run_discovery(object(),tmp_path)

    updates = [c for c in db_calls["calls"] if c[0] == "update_state"]
    assert updates == [("update_state", {"name": "atm10", "state": "running"})]
