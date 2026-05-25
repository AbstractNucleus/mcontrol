"""Tests for routes/regenerate.py. diff preview + mtime-checked confirm.

Contract:
  - Diff captures both files' mtimes; modal carries them as hidden fields.
  - Confirm re-stats both files; mtime drift → re-show diff with 409.
  - On match, atomic-write both files via file_writer.
"""

from pathlib import Path

import pytest

from mcontrol.domain import scaffolding


@pytest.fixture
def fake_db(monkeypatch):
    state = {"rows": []}
    from mcontrol.infra import db

    def fake_get_server(name):
        for row in state["rows"]:
            if row["name"] == name:
                return row
        return None

    def fake_list_servers():
        return list(state["rows"])

    monkeypatch.setattr(db, "get_server", fake_get_server)
    monkeypatch.setattr(db, "list_servers", fake_list_servers)
    return state


def _row(tmp_path: Path, **overrides) -> dict:
    row = {
        "name": "newshire",
        "container_name": None,
        "dir": str(tmp_path / "newshire"),
        "state": "created",
        "scaffolded_at": "2026-05-06T12:00:00+00:00",
        "variables": {
            "memory_budget_gb": 8,
            "port": 25575,
            "server_jar": "paper.jar",
        },
    }
    row.update(overrides)
    return row


def _scaffold(tmp_path: Path, row: dict) -> tuple[Path, Path]:
    """Run the real scaffolding module; return (compose_path, start_path)."""
    scaffolding.scaffold(row["name"], row["variables"], tmp_path)
    return (
        Path(row["dir"]) / "docker-compose.yml",
        Path(row["dir"]) / "server" / "start_server.sh",
    )


# ---- GET /regenerate -----------------------------------------------


async def test_get_returns_diff_and_mtimes(client, fake_db, tmp_path):
    row = _row(tmp_path)
    compose, start = _scaffold(tmp_path, row)
    # Operator hand-edits make the disk diverge from rendered output.
    compose.write_text(compose.read_text() + "\n# operator hand-edit\n")
    fake_db["rows"].append(row)

    response = await client.get("/servers/newshire/regenerate")

    assert response.status_code == 200
    body = response.text
    # Unified-diff syntax + the hand-edit disappear marker.
    assert "@@" in body
    assert "operator hand-edit" in body
    # Hidden mtime fields carry the disk values for the confirm round-trip.
    expected_compose_mtime = compose.stat().st_mtime_ns
    expected_start_mtime = start.stat().st_mtime_ns
    assert f'name="compose_mtime_ns" value="{expected_compose_mtime}"' in body
    assert f'name="start_mtime_ns" value="{expected_start_mtime}"' in body


async def test_get_returns_card_when_render_fails(client, fake_db, tmp_path):
    """Variables incomplete. bail back to the card; the health banner
    on the detail page already explains the cause."""
    row = _row(tmp_path)
    _scaffold(tmp_path, row)
    row["variables"] = {"memory_budget_gb": 8}  # missing port + server_jar
    fake_db["rows"].append(row)

    response = await client.get("/servers/newshire/regenerate")

    assert response.status_code == 200
    # Card markers, not diff markers.
    body = response.text
    assert "Variables" in body
    assert "@@" not in body


async def test_get_returns_404_for_unknown_server(client, fake_db):
    response = await client.get("/servers/unknown/regenerate")
    assert response.status_code == 404


# ---- POST /regenerate/confirm --------------------------------------


async def test_confirm_writes_both_files_and_returns_card(
    client, fake_db, tmp_path
):
    row = _row(tmp_path)
    compose, start = _scaffold(tmp_path, row)
    compose.write_text(compose.read_text() + "\n# hand-edit\n")
    fake_db["rows"].append(row)

    response = await client.post(
        "/servers/newshire/regenerate/confirm",
        data={
            "compose_mtime_ns": str(compose.stat().st_mtime_ns),
            "start_mtime_ns": str(start.stat().st_mtime_ns),
        },
    )

    assert response.status_code == 200
    # Hand-edit clobbered.
    assert "# hand-edit" not in compose.read_text()
    # Render output landed.
    assert "container_name: newshire" in compose.read_text()
    assert "-Xmx6g" in start.read_text()
    # Response is the refreshed card, not the diff partial.
    assert "@@" not in response.text


async def test_confirm_returns_409_with_diff_when_compose_mtime_drifts(
    client, fake_db, tmp_path
):
    row = _row(tmp_path)
    compose, start = _scaffold(tmp_path, row)
    fake_db["rows"].append(row)

    stale_mtime = compose.stat().st_mtime_ns
    # Simulate someone else writing to the file after the diff was shown.
    compose.write_text(compose.read_text() + "\n# concurrent edit\n")

    response = await client.post(
        "/servers/newshire/regenerate/confirm",
        data={
            "compose_mtime_ns": str(stale_mtime),
            "start_mtime_ns": str(start.stat().st_mtime_ns),
        },
    )

    assert response.status_code == 409
    body = response.text
    # Re-shown diff carries the drift marker + the new mtimes.
    assert "Files changed" in body
    assert "@@" in body
    assert f'value="{compose.stat().st_mtime_ns}"' in body
    # Concurrent edit was preserved. confirm did not write.
    assert "# concurrent edit" in compose.read_text()


async def test_confirm_returns_409_when_start_script_disappears(
    client, fake_db, tmp_path
):
    row = _row(tmp_path)
    compose, start = _scaffold(tmp_path, row)
    fake_db["rows"].append(row)

    stale_start_mtime = start.stat().st_mtime_ns
    start.unlink()  # File-not-found counts as drift.

    response = await client.post(
        "/servers/newshire/regenerate/confirm",
        data={
            "compose_mtime_ns": str(compose.stat().st_mtime_ns),
            "start_mtime_ns": str(stale_start_mtime),
        },
    )

    assert response.status_code == 409
    # The diff partial re-rendered with mtime_ns=0 for the missing file.
    assert 'name="start_mtime_ns" value="0"' in response.text


async def test_confirm_returns_404_for_unknown_server(client, fake_db):
    response = await client.post(
        "/servers/unknown/regenerate/confirm",
        data={"compose_mtime_ns": "0", "start_mtime_ns": "0"},
    )
    assert response.status_code == 404


# ---- Variables card surfaces the Regenerate button when stale -------


async def test_variables_card_shows_regenerate_button_when_stale(
    client, fake_db, tmp_path
):
    """The card adds a Regenerate link when health.compute_scripts_stale
    returns True. the affordance is gated on stale, not always-shown."""
    row = _row(tmp_path)
    compose, _ = _scaffold(tmp_path, row)
    compose.write_text(compose.read_text() + "\n# drift\n")
    fake_db["rows"].append(row)

    response = await client.get("/servers/newshire/variables")

    assert response.status_code == 200
    assert 'hx-get="/servers/newshire/regenerate"' in response.text


async def test_variables_card_omits_regenerate_button_when_clean(
    client, fake_db, tmp_path
):
    row = _row(tmp_path)
    _scaffold(tmp_path, row)
    fake_db["rows"].append(row)

    response = await client.get("/servers/newshire/variables")

    assert response.status_code == 200
    assert 'hx-get="/servers/newshire/regenerate"' not in response.text
