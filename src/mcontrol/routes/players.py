"""Central Players page (slice 7 PR 3).

  GET  /players          → roster + per-row "Whitelisted on / Op on" summary,
                           plus the "N memberships on disk for unknown UUIDs"
                           Import affordance.
  POST /players          → form: name → Mojang lookup → upsert players row.
                           Decision 027 outcomes:
                             204            → "no Minecraft account with that name"
                             5xx / timeout  → "Mojang lookup failed; try again"
                             200, new UUID  → "Added <Name> to the roster"
                             200, same name → "<Name> is already in the roster"
                             200, diff name → "<Name> is already in the roster (was: <Old>)"
  POST /players/import   → walk every server's whitelist.json + ops.json,
                           upsert UUIDs not already in the roster. Returns
                           the count newly inserted as a flash.

The Add and Import flows return the page partial (``_players_main.html``)
so HTMX swaps the section in place. GET returns the full page.
"""

import re
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from mcontrol import __version__, db, membership, mojang, server_props
from mcontrol.templates import templates

router = APIRouter()

# Minecraft handles are 3–16 chars from [A-Za-z0-9_]. Mojang would 204 on
# any other input, but rejecting structurally invalid names without
# burning a Mojang lookup keeps the UX faster + avoids retry noise on
# obvious typos.
_NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def _whitelist_disabled_by_server(servers: list[dict]) -> dict[str, bool]:
    """Read each server's ``server.properties`` and return ``{name: True}``
    for servers where ``white-list=false``. Vanilla default is true, so a
    missing file or absent key counts as enabled (no annotation)."""
    out: dict[str, bool] = {}
    for server in servers:
        props = server_props.read_properties(
            Path(server["dir"]) / "server" / "server.properties"
        )
        out[server["name"]] = props.get("white-list", "true").strip().lower() == "false"
    return out


def _build_view() -> dict:
    roster = db.list_players()
    server_rows = db.list_servers()
    memberships = membership.scan_memberships(server_rows)
    whitelist_disabled_for = _whitelist_disabled_by_server(server_rows)

    by_uuid: dict[str, dict] = {
        p["uuid"]: {
            **p,
            "whitelist_servers": [],
            "op_servers": [],
        }
        for p in roster
    }
    unknown_uuids: set[str] = set()

    for record in memberships:
        if record["uuid"] not in by_uuid:
            unknown_uuids.add(record["uuid"])
            continue
        if record["kind"] == "whitelist":
            by_uuid[record["uuid"]]["whitelist_servers"].append(
                {
                    "name": record["server_name"],
                    "whitelist_disabled": whitelist_disabled_for.get(
                        record["server_name"], False
                    ),
                }
            )
        else:
            by_uuid[record["uuid"]]["op_servers"].append(record["server_name"])

    return {
        "roster": list(by_uuid.values()),
        "unknown_count": len(unknown_uuids),
    }


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
    return _page(request, _ctx(_build_view()))


@router.post("/players", response_class=HTMLResponse)
async def add_to_roster(request: Request, name: str = Form(...)) -> HTMLResponse:
    name = name.strip()
    if not _NAME_RE.match(name):
        return _partial(
            request,
            _ctx(
                _build_view(),
                form={"name": name},
                errors={
                    "name": (
                        "3–16 characters; letters, digits, and underscores only."
                    )
                },
            ),
            status_code=422,
        )

    try:
        result = await mojang.lookup_by_name(name)
    except mojang.MojangError:
        return _partial(
            request,
            _ctx(
                _build_view(),
                form={"name": name},
                errors={"name": "Mojang lookup failed; try again."},
            ),
            status_code=502,
        )

    if result is None:
        return _partial(
            request,
            _ctx(
                _build_view(),
                form={"name": name},
                errors={"name": f"No Minecraft account with that name: {name!r}."},
            ),
            status_code=422,
        )

    upsert = db.upsert_player_from_mojang(uuid=result["uuid"], name=result["name"])
    if upsert["created"]:
        flash = {"kind": "ok", "message": f"Added {result['name']} to the roster."}
    elif upsert["previous_name"] == result["name"]:
        flash = {
            "kind": "info",
            "message": f"{result['name']} is already in the roster.",
        }
    else:
        flash = {
            "kind": "info",
            "message": (
                f"{result['name']} is already in the roster "
                f"(was: {upsert['previous_name']})."
            ),
        }

    return _partial(request, _ctx(_build_view(), flash=flash))


@router.post("/players/import", response_class=HTMLResponse)
async def import_unknown(request: Request) -> HTMLResponse:
    server_rows = db.list_servers()
    memberships = membership.scan_memberships(server_rows)

    # Per decision 027, Import takes the JSON's name at face value — those
    # entries were authored by vanilla MC from authoritative Mojang data on
    # first join. First-encountered name wins for a given UUID.
    new_rows: list[dict[str, str]] = []
    seen_new: set[str] = set()
    for record in memberships:
        uuid = record["uuid"]
        if uuid in seen_new:
            continue
        if db.get_player(uuid) is not None:
            continue
        seen_new.add(uuid)
        new_rows.append({"uuid": uuid, "name": record["name"]})

    if new_rows:
        db.insert_players_bulk(new_rows)

    flash = {
        "kind": "ok",
        "message": f"Imported {len(new_rows)} new player(s) from disk.",
    }
    return _partial(request, _ctx(_build_view(), flash=flash))
