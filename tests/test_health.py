"""Unit tests for src/mcontrol/health.py.

The module reads disk and renders templates against a server row;
tests use tmp_path to drive both sides without mocking.
"""

from pathlib import Path

from mcontrol import health, scaffolding


def _scaffolded_row(tmp_path: Path, **overrides) -> dict:
    row = {
        "name": "newshire",
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


def _scaffold_files(tmp_path: Path, row: dict) -> None:
    """Run the real scaffolding module against the row's variables so
    the on-disk bytes match the rendered output."""
    scaffolding.scaffold(row["name"], row["variables"], tmp_path)


# ---- compute_issues ------------------------------------------------


def test_compute_issues_returns_empty_for_legacy_row(tmp_path):
    row = _scaffolded_row(tmp_path, scaffolded_at=None)
    assert health.compute_issues(row) == []


def test_compute_issues_returns_stuck_when_state_is_scaffolding(tmp_path):
    row = _scaffolded_row(tmp_path, state="scaffolding")
    issues = health.compute_issues(row)

    assert len(issues) == 1
    assert issues[0]["code"] == "stuck-scaffolding"


def test_compute_issues_flags_missing_compose(tmp_path):
    row = _scaffolded_row(tmp_path)
    _scaffold_files(tmp_path, row)
    (Path(row["dir"]) / "docker-compose.yml").unlink()

    issues = health.compute_issues(row)
    codes = [i["code"] for i in issues]
    assert "missing-scaffold-file" in codes
    assert any("docker-compose.yml" in i["message"] for i in issues)


def test_compute_issues_flags_missing_start_script(tmp_path):
    row = _scaffolded_row(tmp_path)
    _scaffold_files(tmp_path, row)
    (Path(row["dir"]) / "server" / "start_server.sh").unlink()

    issues = health.compute_issues(row)
    codes = [i["code"] for i in issues]
    assert "missing-scaffold-file" in codes
    assert any("start_server.sh" in i["message"] for i in issues)


def test_compute_issues_flags_variables_incomplete(tmp_path):
    row = _scaffolded_row(tmp_path)
    _scaffold_files(tmp_path, row)
    # Render will KeyError on the missing port / server_jar.
    row["variables"] = {"memory_budget_gb": 8}

    issues = health.compute_issues(row)
    codes = [i["code"] for i in issues]
    assert "variables-incomplete" in codes


def test_compute_issues_returns_empty_when_healthy(tmp_path):
    row = _scaffolded_row(tmp_path)
    _scaffold_files(tmp_path, row)
    assert health.compute_issues(row) == []


# ---- compute_scripts_stale -----------------------------------------


def test_compute_scripts_stale_returns_false_when_disk_matches_render(tmp_path):
    row = _scaffolded_row(tmp_path)
    _scaffold_files(tmp_path, row)
    assert health.compute_scripts_stale(row) is False


def test_compute_scripts_stale_returns_true_when_compose_drifts(tmp_path):
    row = _scaffolded_row(tmp_path)
    _scaffold_files(tmp_path, row)
    compose = Path(row["dir"]) / "docker-compose.yml"
    compose.write_text(compose.read_text() + "\n# operator hand-edit\n")

    assert health.compute_scripts_stale(row) is True


def test_compute_scripts_stale_returns_true_when_start_script_drifts(tmp_path):
    row = _scaffolded_row(tmp_path)
    _scaffold_files(tmp_path, row)
    start = Path(row["dir"]) / "server" / "start_server.sh"
    start.write_text("#!/usr/bin/env bash\necho 'tampered'\n")

    assert health.compute_scripts_stale(row) is True


def test_compute_scripts_stale_returns_none_for_legacy_row(tmp_path):
    row = _scaffolded_row(tmp_path, scaffolded_at=None)
    assert health.compute_scripts_stale(row) is None


def test_compute_scripts_stale_returns_none_when_render_fails(tmp_path):
    row = _scaffolded_row(tmp_path)
    _scaffold_files(tmp_path, row)
    row["variables"] = {"memory_budget_gb": 8}  # missing port / server_jar
    assert health.compute_scripts_stale(row) is None


def test_compute_scripts_stale_returns_none_when_a_file_is_missing(tmp_path):
    row = _scaffolded_row(tmp_path)
    _scaffold_files(tmp_path, row)
    (Path(row["dir"]) / "docker-compose.yml").unlink()
    assert health.compute_scripts_stale(row) is None
