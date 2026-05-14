"""Per-server Players card (slice 7 PR 2).

Renders combined whitelist + ops membership for a server, plus an
add-from-roster picker. Two checkboxes per row HTMX-swap the
underlying disk file via either RCON (when state='running') or a
mtime-checked atomic edit (when offline).

  GET  /servers/{name}/players                          → render card
  POST /servers/{name}/players                          → add from roster (whitelist-only)
  POST /servers/{name}/players/{uuid}/whitelist         → toggle whitelist
  POST /servers/{name}/players/{uuid}/op                → toggle op

Decision 027:
  - Roster add is the only entry point for new identities; the picker
    only lists rows already in ``app_mcontrol.players``.
  - Op level is always vanilla default (4); no UI for non-default
    levels (those go through the slice-5 file editor).
  - Running → RCON; offline → mtime-checked file edit. RCON responses
    are surfaced verbatim in a flash message.
"""

from pathlib import Path

import aiodocker
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import db_async, membership, server_rcon
from mcontrol.routes._dependencies import (
    get_docker,
    get_server_or_404,
    validate_uuid,
)
from mcontrol.templates import templates

router = APIRouter()


def _members_view(server_dir: Path) -> tuple[list[dict], list[str]]:
    """Build the combined whitelist+ops view for the card.

    Returns ``(members, malformed_kinds)`` where ``members`` is a list
    of ``{uuid, name, in_whitelist, in_op}`` and ``malformed_kinds`` is
    a subset of ``["whitelist", "ops"]`` for files that failed to
    parse — the card surfaces those inline so the operator knows why a
    section is empty even though the per-server health banner already
    flagged the file (slice 7 PR 2 also extends ``health.py``)."""
    malformed: list[str] = []
    by_uuid: dict[str, dict] = {}

    try:
        wl_entries, _ = membership.read_whitelist(server_dir)
    except membership.MalformedFileError:
        wl_entries = []
        malformed.append("whitelist")
    for entry in wl_entries:
        uuid = entry.get("uuid")
        name = entry.get("name")
        if not uuid or not name:
            continue
        by_uuid[uuid] = {
            "uuid": uuid,
            "name": name,
            "in_whitelist": True,
            "in_op": False,
        }

    try:
        ops_entries, _ = membership.read_ops(server_dir)
    except membership.MalformedFileError:
        ops_entries = []
        malformed.append("ops")
    for entry in ops_entries:
        uuid = entry.get("uuid")
        name = entry.get("name")
        if not uuid or not name:
            continue
        if uuid in by_uuid:
            by_uuid[uuid]["in_op"] = True
        else:
            by_uuid[uuid] = {
                "uuid": uuid,
                "name": name,
                "in_whitelist": False,
                "in_op": True,
            }

    members = sorted(by_uuid.values(), key=lambda m: m["name"].lower())
    return members, malformed


async def _card(
    request: Request,
    server: dict,
    *,
    flash: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    server_dir = Path(server["dir"])
    members, malformed = _members_view(server_dir)
    return templates.TemplateResponse(
        request=request,
        name="_server_players_card.html",
        context={
            "server": server,
            "members": members,
            "malformed": malformed,
            "roster": await db_async.list_players(),
            "running": server.get("state") == "running",
            "flash": flash,
        },
        status_code=status_code,
    )


def _ok(message: str) -> dict:
    return {"kind": "ok", "message": message}


def _error(message: str) -> dict:
    return {"kind": "error", "message": message}


_RCON_VERB = {
    ("whitelist", True): "whitelist add",
    ("whitelist", False): "whitelist remove",
    ("op", True): "op",
    ("op", False): "deop",
}


async def _apply_running(
    docker: aiodocker.Docker,
    server: dict,
    *,
    kind: str,
    name: str,
    enabled: bool,
) -> dict:
    cmd = f"{_RCON_VERB[(kind, enabled)]} {name}"
    try:
        response = await server_rcon.run_command(docker, server, cmd)
    except server_rcon.RconUnavailable as exc:
        return _error(str(exc))
    return _ok(response.strip() or f"{cmd}: ok")


def _apply_offline(
    server: dict, *, kind: str, uuid: str, name: str, enabled: bool
) -> dict:
    server_dir = Path(server["dir"])
    try:
        if kind == "whitelist":
            wrote = (
                membership.add_whitelist_entry(server_dir, uuid=uuid, name=name)
                if enabled
                else membership.remove_whitelist_entry(server_dir, uuid=uuid)
            )
        else:
            wrote = (
                membership.add_op_entry(server_dir, uuid=uuid, name=name)
                if enabled
                else membership.remove_op_entry(server_dir, uuid=uuid)
            )
    except membership.StaleWriteError:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{kind}.json changed on disk between read and write — retry."
            ),
        ) from None
    if not wrote:
        return _ok(f"{name} was already {'in' if enabled else 'out of'} the {kind}.")
    verb = "added to" if enabled else "removed from"
    return _ok(f"{name} {verb} the {kind} (offline file edit).")


async def _flip(
    docker: aiodocker.Docker,
    server: dict,
    *,
    kind: str,
    uuid: str,
    name: str,
    enabled: bool,
) -> dict:
    if server.get("state") == "running":
        return await _apply_running(
            docker, server, kind=kind, name=name, enabled=enabled
        )
    return _apply_offline(server, kind=kind, uuid=uuid, name=name, enabled=enabled)


@router.get("/servers/{name}/players", response_class=HTMLResponse)
async def get_card(
    request: Request, server: dict = Depends(get_server_or_404)
) -> HTMLResponse:
    return await _card(request, server)


@router.post("/servers/{name}/players", response_class=HTMLResponse)
async def add_from_roster(
    request: Request,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
    roster_uuid: str = Form(...),
) -> HTMLResponse:
    uuid = validate_uuid(roster_uuid)
    player = await db_async.get_player(uuid)
    if player is None:
        return await _card(
            request,
            server,
            flash=_error("That UUID is not in the roster."),
            status_code=422,
        )
    flash = await _flip(
        docker,
        server,
        kind="whitelist",
        uuid=uuid,
        name=player["name"],
        enabled=True,
    )
    return await _card(request, server, flash=flash)


@router.post(
    "/servers/{name}/players/{uuid}/whitelist", response_class=HTMLResponse
)
async def toggle_whitelist(
    request: Request,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
    uuid: str = Depends(validate_uuid),
    enabled: bool = Form(False),
) -> HTMLResponse:
    player_name = await _resolve_player_name(server, uuid)
    flash = await _flip(
        docker,
        server,
        kind="whitelist",
        uuid=uuid,
        name=player_name,
        enabled=enabled,
    )
    return await _card(request, server, flash=flash)


@router.post("/servers/{name}/players/{uuid}/op", response_class=HTMLResponse)
async def toggle_op(
    request: Request,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
    uuid: str = Depends(validate_uuid),
    enabled: bool = Form(False),
) -> HTMLResponse:
    player_name = await _resolve_player_name(server, uuid)
    flash = await _flip(
        docker, server, kind="op", uuid=uuid, name=player_name, enabled=enabled
    )
    return await _card(request, server, flash=flash)


async def _resolve_player_name(server: dict, uuid: str) -> str:
    """Best-effort player-name lookup for an RCON command.

    Roster takes precedence (decision 027 — roster row is the
    operator-trusted source). Falls back to whichever name appears in
    the on-disk files (handles the case where a UUID is on a server
    but isn't in the roster yet — Import is the canonical fix, but
    toggling should still work)."""
    player = await db_async.get_player(uuid)
    if player is not None:
        return player["name"]
    server_dir = Path(server["dir"])
    for reader in (membership.read_whitelist, membership.read_ops):
        try:
            entries, _ = reader(server_dir)
        except membership.MalformedFileError:
            continue
        for entry in entries:
            if entry.get("uuid") == uuid and entry.get("name"):
                return entry["name"]
    raise HTTPException(
        status_code=404,
        detail="Could not resolve a name for that UUID.",
    )
