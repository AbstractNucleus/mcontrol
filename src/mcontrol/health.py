"""Per-server scaffold-integrity checks for the detail-page health banner.

Three issue types ship in slice 6 PR 3:

  - stuck-scaffolding   — row stuck in state='scaffolding'; PR 2's
                          insert succeeded but the scaffold-files
                          step did not.
  - missing-scaffold-file — compose or start_server.sh absent on disk.
  - variables-incomplete — rendering the templates against the row's
                           variables JSONB raises (KeyError or
                           jinja2.UndefinedError).

Computed on every detail-page render, never stored. PR 4 (Regenerate)
also calls compute_scripts_stale to gate its button.
"""

from pathlib import Path
from typing import Any

from jinja2 import UndefinedError

from mcontrol import scaffolding


def _compose_path(server: dict[str, Any]) -> Path:
    return Path(server["dir"]) / "docker-compose.yml"


def _start_path(server: dict[str, Any]) -> Path:
    return Path(server["dir"]) / "server" / "start_server.sh"


def variables_render_error(server: dict[str, Any]) -> str | None:
    """Return a human-readable cause string if rendering fails, or None."""
    variables = server.get("variables") or {}
    try:
        scaffolding.render_compose(server["name"], variables)
        scaffolding.render_start_script(variables)
    except KeyError as e:
        return f"missing variable: {e.args[0]!r}"
    except UndefinedError as e:
        return str(e)
    return None


def compute_issues(server: dict[str, Any]) -> list[dict[str, str]]:
    """Return a list of {code, message} dicts for the health banner.

    Empty for legacy (non-scaffolded) rows — those are operator-managed
    via the slice-5 file browser and have no scaffold contract to check.
    """
    if server.get("scaffolded_at") is None:
        return []

    if server.get("state") == "scaffolding":
        return [
            {
                "code": "stuck-scaffolding",
                "message": (
                    "Server insert succeeded but the scaffold-files step did "
                    "not. Delete the row and try again."
                ),
            }
        ]

    issues: list[dict[str, str]] = []

    if not _compose_path(server).exists():
        issues.append(
            {
                "code": "missing-scaffold-file",
                "message": "docker-compose.yml is missing — re-create from the Variables card.",
            }
        )
    if not _start_path(server).exists():
        issues.append(
            {
                "code": "missing-scaffold-file",
                "message": "server/start_server.sh is missing — re-create from the Variables card.",
            }
        )

    cause = variables_render_error(server)
    if cause is not None:
        issues.append(
            {
                "code": "variables-incomplete",
                "message": f"Variables incomplete ({cause}) — fix in the Variables card.",
            }
        )

    return issues


def compute_scripts_stale(server: dict[str, Any]) -> bool | None:
    """Return True iff disk bytes of either scaffold file diverge from
    the rendered output. None when the comparison is meaningless
    (variables don't render, or a file is missing) — those failures
    surface separately in compute_issues."""
    if server.get("scaffolded_at") is None:
        return None
    variables = server.get("variables") or {}
    try:
        rendered_compose = scaffolding.render_compose(server["name"], variables)
        rendered_start = scaffolding.render_start_script(variables)
    except (KeyError, UndefinedError):
        return None

    compose_path = _compose_path(server)
    start_path = _start_path(server)
    if not compose_path.exists() or not start_path.exists():
        return None

    return (
        compose_path.read_text(encoding="utf-8") != rendered_compose
        or start_path.read_text(encoding="utf-8") != rendered_start
    )
