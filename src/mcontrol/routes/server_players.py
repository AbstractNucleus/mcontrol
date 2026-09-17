"""Per-server Players card (slice 7 PR 2).

Renders combined whitelist + ops membership for a server, plus an
add-from-roster picker. Two checkboxes per row HTMX-swap the
underlying disk file via either RCON (when state='running') or a
mtime-checked atomic edit (when offline).

  GET  /servers/{name}/players                          → render card
  POST /servers/{name}/players                          → add from roster (whitelist-only)
  POST /servers/{name}/players/{uuid}/remove            → remove from this server
  POST /servers/{name}/players/{uuid}/whitelist         → toggle whitelist
  POST /servers/{name}/players/{uuid}/op                → toggle op

Rules:
  - Roster add is the only entry point for new identities; the picker
    only lists rows already in ``app_mcontrol.players``.
  - Op level is always vanilla default (4); no UI for non-default
    levels (those go through the slice-5 file editor).
  - Running → RCON; offline → mtime-checked file edit. RCON responses
    are surfaced verbatim in a flash message.

The RCON-vs-offline dispatch, view assembly, and name resolution live
in ``services.membership_service``: this module is thin orchestration
plus template rendering.
"""

import re
from pathlib import Path

import aiodocker
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol.domain import lifecycle_state, membership
from mcontrol.infra import db_async
from mcontrol.routes._dependencies import (
    get_docker,
    get_server_or_404,
    validate_uuid,
)
from mcontrol.services import membership_service
from mcontrol.templates import templates

router = APIRouter()

# Vanilla/Paper `list` response head: "There are 2 of a max of 20 players online: ..."
_ONLINE_RE = re.compile(
    r"There are (\d+) of a max (?:of )?(\d+) players online:?\s*(.*)"
)


async def _card(
    request: Request,
    server: dict,
    *,
    flash: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    server_dir = Path(server["dir"])
    members, malformed = membership_service.per_server_members_view(server_dir)
    return templates.TemplateResponse(
        request=request,
        name="_server_players_card.html",
        context={
            "server": server,
            "members": members,
            "malformed": malformed,
            "roster": await db_async.list_players(),
            "running": lifecycle_state.is_running(server),
            "flash": flash,
        },
        status_code=status_code,
    )


def _error(message: str) -> dict:
    return {"kind": "error", "message": message}


async def _flip_with_stale_guard(
    docker: aiodocker.Docker,
    server: dict,
    *,
    kind: str,
    uuid: str,
    name: str,
    enabled: bool,
) -> dict:
    """Route-layer wrapper around ``membership_service.apply_membership``
    that maps the offline mtime-drift exception to a 409 (RCON path
    swallows upstream errors into a flash; the offline path lets file-
    level errors propagate so HTTP can carry them)."""
    try:
        return await membership_service.apply_membership(
            docker, server, kind=kind, uuid=uuid, name=name, enabled=enabled
        )
    except membership.StaleWriteError:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{kind}.json changed on disk between read and write. Retry."
            ),
        ) from None


@router.get("/servers/{name}/players", response_class=HTMLResponse)
async def get_card(
    request: Request, server: dict = Depends(get_server_or_404)
) -> HTMLResponse:
    return await _card(request, server)


@router.get("/servers/{name}/players/online", response_class=HTMLResponse)
async def online_chip(
    request: Request,
    server: dict = Depends(get_server_or_404),
) -> HTMLResponse:
    """Head-count chip: RCON `list` via the live console socket only.

    Never opens a competing one-shot RCON client — Minecraft allows one
    connection, and a second connect on page load kills the console.
    Any miss/failure degrades to the plain live pill.
    """
    running = lifecycle_state.is_running(server)
    context: dict = {"server": server, "running": running, "ok": False}
    if running:
        from mcontrol.routes import console

        try:
            response = await console.run_on_active(
                server["name"], "list", echo=False
            )
        except (TimeoutError, Exception):
            response = None
        match = _ONLINE_RE.search(response or "")
        if match:
            names = [n.strip() for n in match.group(3).split(",") if n.strip()]
            context.update(
                ok=True,
                online=int(match.group(1)),
                max_players=int(match.group(2)),
                names=names,
            )
    return templates.TemplateResponse(
        request=request, name="_online_chip.html", context=context
    )


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
    flash = await _flip_with_stale_guard(
        docker,
        server,
        kind="whitelist",
        uuid=uuid,
        name=player["name"],
        enabled=True,
    )
    return await _card(request, server, flash=flash)


@router.post(
    "/servers/{name}/players/{uuid}/remove", response_class=HTMLResponse
)
async def remove_from_server(
    request: Request,
    server: dict = Depends(get_server_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
    uuid: str = Depends(validate_uuid),
) -> HTMLResponse:
    """Remove this player's op and whitelist memberships from one server.

    The global roster is intentionally untouched.  When both memberships
    exist, deop runs first and a failure stops the sequence so the route
    never reports a successful removal while one of its operations failed.
    """
    player_name = await membership_service.resolve_player_name(server, uuid)
    if player_name is None:
        raise HTTPException(
            status_code=404, detail="Could not resolve a name for that UUID."
        )

    members, malformed = membership_service.per_server_members_view(
        Path(server["dir"])
    )
    if malformed:
        files = ", ".join(f"{kind}.json" for kind in malformed)
        return await _card(
            request,
            server,
            flash=_error(
                f"Could not remove {player_name}: {files} failed to parse."
            ),
        )

    member = next((item for item in members if item["uuid"] == uuid), None)
    if member is None:
        return await _card(
            request,
            server,
            flash=_error(f"{player_name} is no longer on this server."),
        )

    successful_kinds: list[str] = []
    responses: list[str] = []
    for kind, present in (
        ("op", member["in_op"]),
        ("whitelist", member["in_whitelist"]),
    ):
        if not present:
            continue
        try:
            flash = await _flip_with_stale_guard(
                docker,
                server,
                kind=kind,
                uuid=uuid,
                name=player_name,
                enabled=False,
            )
        except HTTPException as exc:
            if not successful_kinds:
                raise
            return await _card(
                request,
                server,
                flash=_error(
                    "Operator access was removed, but whitelist removal "
                    f"failed: {exc.detail}"
                ),
            )
        except membership.MalformedFileError as exc:
            prefix = (
                "Operator access was removed, but " if successful_kinds else ""
            )
            return await _card(
                request,
                server,
                flash=_error(f"{prefix}{kind}.json failed to parse: {exc}"),
            )
        if flash["kind"] == "error":
            if successful_kinds:
                flash = _error(
                    "Operator access was removed, but whitelist removal "
                    f"failed: {flash['message']}"
                )
            return await _card(request, server, flash=flash)
        successful_kinds.append(kind)
        responses.append(flash["message"])

    return await _card(
        request,
        server,
        flash={
            "kind": "ok",
            "message": (
                " ".join(responses)
                if lifecycle_state.is_running(server)
                else f"Removed {player_name} from {server['name']}."
            ),
        },
    )


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
    player_name = await membership_service.resolve_player_name(server, uuid)
    if player_name is None:
        raise HTTPException(
            status_code=404, detail="Could not resolve a name for that UUID."
        )
    flash = await _flip_with_stale_guard(
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
    player_name = await membership_service.resolve_player_name(server, uuid)
    if player_name is None:
        raise HTTPException(
            status_code=404, detail="Could not resolve a name for that UUID."
        )
    flash = await _flip_with_stale_guard(
        docker, server, kind="op", uuid=uuid, name=player_name, enabled=enabled
    )
    return await _card(request, server, flash=flash)
