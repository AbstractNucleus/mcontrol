"""Tests for routes/regenerate.py. diff preview + mtime-checked confirm.

Contract:
  - Diff captures both files' mtimes; modal carries them as hidden fields.
  - Confirm re-stats both files; mtime drift → re-show diff with 409.
  - On match, atomic-write both files via file_writer.
"""

import re
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


def _confirm_data(preview: str) -> dict[str, str]:
    fields = ("compose_mtime_ns", "start_mtime_ns", "proposal_fingerprint")
    result: dict[str, str] = {}
    for field in fields:
        match = re.search(rf'name="{field}" value="([^"]+)"', preview)
        assert match is not None
        result[field] = match.group(1)
    return result


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
    assert re.search(
        r'name="proposal_fingerprint" value="[0-9a-f]{64}"', body
    )


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
    preview = await client.get("/servers/newshire/regenerate")

    response = await client.post(
        "/servers/newshire/regenerate/confirm",
        data=_confirm_data(preview.text),
    )

    assert response.status_code == 200
    # Hand-edit clobbered.
    assert "# hand-edit" not in compose.read_text()
    # Render output landed.
    assert "container_name: newshire" in compose.read_text()
    assert "-Xmx6g" in start.read_text()
    # Response is the refreshed card, not the diff partial.
    assert "@@" not in response.text
    assert 'hx-post="/servers/newshire/lifecycle/recreate"' in response.text
    assert (Path(row["dir"]) / "server" / "server.properties").exists()


async def test_confirm_does_not_overwrite_server_properties(
    client, fake_db, tmp_path
):
    row = _row(tmp_path)
    compose, start = _scaffold(tmp_path, row)
    props = Path(row["dir"]) / "server" / "server.properties"
    original = props.read_text(encoding="utf-8")
    fake_db["rows"].append(row)
    preview = await client.get("/servers/newshire/regenerate")

    response = await client.post(
        "/servers/newshire/regenerate/confirm",
        data=_confirm_data(preview.text),
    )

    assert response.status_code == 200
    assert props.read_text(encoding="utf-8") == original


async def test_regenerate_switches_jar_to_custom_script_and_preserves_pack_files(
    client, fake_db, tmp_path
):
    row = _row(tmp_path)
    compose, start = _scaffold(tmp_path, row)
    pack_script = start.parent / "run.sh"
    pack_script.write_text("exec java @user_jvm_args.txt @libraries/args.txt\n")
    row["variables"]["custom_start_script"] = "run.sh"
    fake_db["rows"].append(row)
    preview = await client.get("/servers/newshire/regenerate")
    assert "exec bash ./run.sh" in preview.text
    response = await client.post(
        "/servers/newshire/regenerate/confirm",
        data=_confirm_data(preview.text),
    )
    assert response.status_code == 200
    assert "exec bash ./run.sh" in start.read_text()
    assert "exec java" not in start.read_text()
    assert pack_script.read_text() == "exec java @user_jvm_args.txt @libraries/args.txt\n"


async def test_confirm_returns_409_with_diff_when_compose_mtime_drifts(
    client, fake_db, tmp_path
):
    row = _row(tmp_path)
    compose, start = _scaffold(tmp_path, row)
    fake_db["rows"].append(row)

    preview = await client.get("/servers/newshire/regenerate")
    # Simulate someone else writing to the file after the diff was shown.
    compose.write_text(compose.read_text() + "\n# concurrent edit\n")

    response = await client.post(
        "/servers/newshire/regenerate/confirm",
        data=_confirm_data(preview.text),
    )

    assert response.status_code == 409
    body = response.text
    # Re-shown diff carries the drift marker + the new mtimes.
    assert "Files or settings changed" in body
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

    preview = await client.get("/servers/newshire/regenerate")
    start.unlink()  # File-not-found counts as drift.

    response = await client.post(
        "/servers/newshire/regenerate/confirm",
        data=_confirm_data(preview.text),
    )

    assert response.status_code == 409
    # The diff partial re-rendered with mtime_ns=0 for the missing file.
    assert 'name="start_mtime_ns" value="0"' in response.text


async def test_confirm_returns_404_for_unknown_server(client, fake_db):
    response = await client.post(
        "/servers/unknown/regenerate/confirm",
        data={
            "compose_mtime_ns": "0",
            "start_mtime_ns": "0",
            "proposal_fingerprint": "0" * 64,
        },
    )
    assert response.status_code == 404


async def test_confirm_refreshes_preview_when_database_variables_change(
    client, fake_db, tmp_path
):
    row = _row(tmp_path)
    compose, start = _scaffold(tmp_path, row)
    compose.write_text(compose.read_text() + "\n# hand-edit\n")
    original_start = start.read_text(encoding="utf-8")
    fake_db["rows"].append(row)
    preview = await client.get("/servers/newshire/regenerate")
    stale_data = _confirm_data(preview.text)

    row["variables"] = {**row["variables"], "port": 25576}
    response = await client.post(
        "/servers/newshire/regenerate/confirm", data=stale_data
    )

    assert response.status_code == 409
    assert "Files or settings changed" in response.text
    assert "25576:25565" in response.text
    assert "# hand-edit" in compose.read_text(encoding="utf-8")
    assert start.read_text(encoding="utf-8") == original_start

    refreshed_data = _confirm_data(response.text)
    assert refreshed_data["proposal_fingerprint"] != stale_data["proposal_fingerprint"]
    confirmed = await client.post(
        "/servers/newshire/regenerate/confirm", data=refreshed_data
    )
    assert confirmed.status_code == 200
    assert "25576:25565" in compose.read_text(encoding="utf-8")


async def test_confirm_refreshes_preview_when_container_binding_changes(
    client, fake_db, tmp_path
):
    row = _row(tmp_path)
    compose, _ = _scaffold(tmp_path, row)
    compose.write_text(compose.read_text() + "\n# keep-until-confirmed\n")
    fake_db["rows"].append(row)
    preview = await client.get("/servers/newshire/regenerate")

    row["container_name"] = "renamed-container"
    response = await client.post(
        "/servers/newshire/regenerate/confirm", data=_confirm_data(preview.text)
    )

    assert response.status_code == 409
    assert "Files or settings changed" in response.text
    assert "# keep-until-confirmed" in compose.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "invalid_variables",
    [
        {"memory_budget_gb": 8},
        {"memory_budget_gb": "large", "port": 25575, "server_jar": "paper.jar"},
    ],
)
async def test_confirm_handles_current_invalid_variables_without_writing(
    client, fake_db, tmp_path, invalid_variables
):
    row = _row(tmp_path)
    compose, start = _scaffold(tmp_path, row)
    fake_db["rows"].append(row)
    preview = await client.get("/servers/newshire/regenerate")
    originals = (compose.read_bytes(), start.read_bytes())

    row["variables"] = invalid_variables
    response = await client.post(
        "/servers/newshire/regenerate/confirm", data=_confirm_data(preview.text)
    )

    assert response.status_code == 409
    assert "Render failed" in response.text
    assert (compose.read_bytes(), start.read_bytes()) == originals


async def test_confirm_requires_preview_fingerprint(client, fake_db, tmp_path):
    row = _row(tmp_path)
    compose, start = _scaffold(tmp_path, row)
    compose.write_text(compose.read_text() + "\n# must-survive\n")
    fake_db["rows"].append(row)

    response = await client.post(
        "/servers/newshire/regenerate/confirm",
        data={
            "compose_mtime_ns": str(compose.stat().st_mtime_ns),
            "start_mtime_ns": str(start.stat().st_mtime_ns),
        },
    )

    assert response.status_code == 422
    assert "# must-survive" in compose.read_text(encoding="utf-8")


async def test_confirm_surfaces_incomplete_pair_recovery(
    client, fake_db, tmp_path, monkeypatch
):
    row = _row(tmp_path)
    compose, start = _scaffold(tmp_path, row)
    compose.write_text(compose.read_text() + "\n# old-compose\n")
    start.write_text(start.read_text() + "\n# old-start\n")
    fake_db["rows"].append(row)
    preview = await client.get("/servers/newshire/regenerate")

    real_write = scaffolding.atomic_write_text

    def fail_start_write(path, content):
        if Path(path) == start:
            raise PermissionError("start directory remains read-only")
        real_write(path, content)

    def fail_compose_restore(snapshot):
        if snapshot.path == compose:
            raise PermissionError("compose restore denied")
        raise AssertionError("unwritten start file must not be restored")

    monkeypatch.setattr(scaffolding, "atomic_write_text", fail_start_write)
    monkeypatch.setattr(scaffolding, "_restore_snapshot", fail_compose_restore)

    response = await client.post(
        "/servers/newshire/regenerate/confirm", data=_confirm_data(preview.text)
    )

    assert response.status_code == 500
    assert "automatic recovery could not finish" in response.text
    assert "Keep the server stopped" in response.text
    assert "start directory remains read-only" in response.text
    assert "compose restore denied" in response.text
    assert "# old-start" in start.read_text(encoding="utf-8")


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
