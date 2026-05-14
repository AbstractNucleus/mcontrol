"""Central Players page (slice 7 PR 3 + PR 4).

  GET  /players                    → roster + per-row "Whitelisted on / Op on"
                                     summary, plus the "N memberships on disk
                                     for unknown UUIDs" Import affordance.
  POST /players                    → form: name → Mojang lookup → upsert.
                                     Decision 027 outcomes:
                                       204            → "no Minecraft account with that name"
                                       5xx / timeout  → "Mojang lookup failed; try again"
                                       200, new UUID  → "Added <Name> to the roster"
                                       200, same name → "<Name> is already in the roster"
                                       200, diff name → "<Name> is already in the roster
                                                         (was: <Old>)"
  POST /players/import             → walk every server's whitelist.json + ops.json,
                                     upsert UUIDs not already in the roster.

  GET  /players/{uuid}/remove      → cascade-confirm modal (PR 4).
  POST /players/{uuid}/remove      → form: scope ∈ {roster, all}.
                                     scope=roster: hard-delete the row only.
                                     scope=all:    cascade through every server
                                                   where this UUID has a
                                                   membership, then hard-delete.

The Add / Import / Remove flows return the page partial
(``_players_main.html``) so HTMX swaps the section in place. GET
returns the full page.

Roster view assembly, the Mojang-lookup + upsert flow, the unknown-
UUID import, and the per-server cascade-remove live in
``services.membership_service``.
"""

import re

import aiodocker
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import __version__
from mcontrol.infra import db_async
from mcontrol.routes._dependencies import get_docker, get_player_or_404
from mcontrol.services import membership_service
from mcontrol.templates import templates

router = APIRouter()

# Minecraft handles are 3–16 chars from [A-Za-z0-9_]. Mojang would 204 on
# any other input, but rejecting structurally invalid names without
# burning a Mojang lookup keeps the UX faster + avoids retry noise on
# obvious typos.
_NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def _ctx(
    view: dict,
    *,
    form: dict | None = None,
    errors: dict | None = None,
    flash: dict | None = None,
) -> dict:
    return {
        "version": __version__,
        "roster": view["roster"],
        "unknown_count": view["unknown_count"],
        "form": form or {"name": ""},
        "errors": errors or {},
        "flash": flash,
    }


def _page(request: Request, ctx: dict, *, status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="players.html", context=ctx, status_code=status_code
    )


def _partial(request: Request, ctx: dict, *, status_code: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_players_main.html",
        context=ctx,
        status_code=status_code,
    )


@router.get("/players", response_class=HTMLResponse)
async def get_page(request: Request) -> HTMLResponse:
    return _page(request, _ctx(await membership_service.build_roster_view()))


@router.post("/players", response_class=HTMLResponse)
async def add_to_roster(request: Request, name: str = Form(...)) -> HTMLResponse:
    name = name.strip()
    if not _NAME_RE.match(name):
        return _partial(
            request,
            _ctx(
                await membership_service.build_roster_view(),
                form={"name": name},
                errors={
                    "name": (
                        "3–16 characters; letters, digits, and underscores only."
                    )
                },
            ),
            status_code=422,
        )

    result = await membership_service.add_player_to_roster(name)

    if result["status"] == "mojang_error":
        return _partial(
            request,
            _ctx(
                await membership_service.build_roster_view(),
                form={"name": name},
                errors={"name": "Mojang lookup failed; try again."},
            ),
            status_code=502,
        )

    if result["status"] == "not_found":
        return _partial(
            request,
            _ctx(
                await membership_service.build_roster_view(),
                form={"name": name},
                errors={"name": f"No Minecraft account with that name: {name!r}."},
            ),
            status_code=422,
        )

    return _partial(
        request,
        _ctx(await membership_service.build_roster_view(), flash=result["flash"]),
    )


@router.post("/players/import", response_class=HTMLResponse)
async def import_unknown(request: Request) -> HTMLResponse:
    n = await membership_service.import_unknown_uuids()
    flash = {
        "kind": "ok",
        "message": f"Imported {n} new player(s) from disk.",
    }
    return _partial(
        request, _ctx(await membership_service.build_roster_view(), flash=flash)
    )


# ---------------------------------------------------------------------------
# Cascade-remove modal + handler (PR 4)
# ---------------------------------------------------------------------------


@router.get("/players/{uuid}/remove", response_class=HTMLResponse)
async def remove_modal(
    request: Request, player: dict = Depends(get_player_or_404)
) -> HTMLResponse:
    memberships = await membership_service.memberships_for(player["uuid"])
    return templates.TemplateResponse(
        request=request,
        name="_player_remove_modal.html",
        context={"player": player, "memberships": memberships},
    )


@router.post("/players/{uuid}/remove", response_class=HTMLResponse)
async def remove(
    request: Request,
    player: dict = Depends(get_player_or_404),
    docker: aiodocker.Docker = Depends(get_docker),
    scope: str = Form(...),
) -> HTMLResponse:
    uuid = player["uuid"]

    if scope == "roster":
        await db_async.delete_player(uuid)
        flash = {
            "kind": "ok",
            "message": (
                f"Removed {player['name']} from the roster. "
                "On-disk memberships were not touched — they'll resurface as "
                "'unknown UUIDs' on this page until you Import or remove them."
            ),
        }
        return _partial(
            request, _ctx(await membership_service.build_roster_view(), flash=flash)
        )

    if scope == "all":
        removed, failures = await membership_service.cascade_remove_player(
            docker, player
        )
        await db_async.delete_player(uuid)
        flash = membership_service.cascade_flash(player["name"], removed, failures)
        return _partial(
            request, _ctx(await membership_service.build_roster_view(), flash=flash)
        )

    raise HTTPException(status_code=400, detail="scope must be 'roster' or 'all'")
