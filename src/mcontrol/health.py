"""Per-server scaffold-integrity checks for the detail-page health banner.

Issue types:

  - stuck-scaffolding     — row stuck in state='scaffolding'; PR 2's
                            insert succeeded but the scaffold-files
                            step did not. (Slice 6 PR 3.)
  - missing-scaffold-file — compose or start_server.sh absent on disk.
                            (Slice 6 PR 3.)
  - variables-incomplete  — rendering the templates against the row's
                            variables JSONB raises (KeyError or
                            jinja2.UndefinedError). (Slice 6 PR 3.)
  - whitelist-malformed   — server/whitelist.json is not valid
                            list-of-objects JSON. (Slice 7 PR 2 — runs
                            on legacy rows too, since whitelist/ops are
                            disk-only and apply regardless of scaffold
                            state per decision 027.)
  - ops-malformed         — server/ops.json is not valid list-of-objects
                            JSON. (Slice 7 PR 2.)
  - rcon-password-stale   — on-disk rcon.password differs from the value
                            mcontrol last authenticated with. Means the
                            running JVM still holds the old password and
                            new RCON connections will fail until the
                            container restarts. (Issue 119.)

Computed on every detail-page render, never stored. PR 4 (Regenerate)
also calls compute_scripts_stale to gate its button.
"""

from pathlib import Path
from typing import Any

from jinja2 import UndefinedError

from mcontrol import membership, scaffolding, server_rcon


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


def _membership_issues(server: dict[str, Any]) -> list[dict[str, str]]:
    """Membership-file checks. Run on every server (legacy + scaffolded);
    decision 027 makes the whitelist/ops affordances apply uniformly."""
    issues: list[dict[str, str]] = []
    server_dir = Path(server["dir"])
    try:
        membership.read_whitelist(server_dir)
    except membership.MalformedFileError as exc:
        issues.append(
            {
                "code": "whitelist-malformed",
                "message": (
                    f"server/whitelist.json failed to parse ({exc}). Fix it via "
                    "the Files panel before adding or removing players."
                ),
            }
        )
    try:
        membership.read_ops(server_dir)
    except membership.MalformedFileError as exc:
        issues.append(
            {
                "code": "ops-malformed",
                "message": (
                    f"server/ops.json failed to parse ({exc}). Fix it via the "
                    "Files panel before adding or removing ops."
                ),
            }
        )
    return issues


def compute_issues(server: dict[str, Any]) -> list[dict[str, str]]:
    """Return a list of {code, message} dicts for the health banner."""
    issues: list[dict[str, str]] = list(_membership_issues(server))

    if server_rcon.stale_password_detected(server):
        issues.append(
            {
                "code": "rcon-password-stale",
                "message": (
                    "RCON password changed on disk but server is still running "
                    "with the old value — restart required."
                ),
            }
        )

    if server.get("scaffolded_at") is None:
        return issues

    if server.get("state") == "scaffolding":
        issues.append(
            {
                "code": "stuck-scaffolding",
                "message": (
                    "Server insert succeeded but the scaffold-files step did "
                    "not. Delete the row and try again."
                ),
            }
        )
        return issues

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
