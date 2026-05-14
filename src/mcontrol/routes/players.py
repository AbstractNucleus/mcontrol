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
"""

import re
from pathlib import Path

import aiodocker
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import __version__, db_async, membership, mojang, server_props, server_rcon
from mcontrol.routes._dependencies import get_docker, get_player_or_404
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


async def _build_view() -> dict:
    roster = await db_async.list_players()
    server_rows = await db_async.list_servers()
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
    return _page(request, _ctx(await _build_view()))


@router.post("/players", response_class=HTMLResponse)
async def add_to_roster(request: Request, name: str = Form(...)) -> HTMLResponse:
    name = name.strip()
    if not _NAME_RE.match(name):
        return _partial(
            request,
            _ctx(
                await _build_view(),
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
                await _build_view(),
                form={"name": name},
                errors={"name": "Mojang lookup failed; try again."},
            ),
            status_code=502,
        )

    if result is None:
        return _partial(
            request,
            _ctx(
                await _build_view(),
                form={"name": name},
                errors={"name": f"No Minecraft account with that name: {name!r}."},
            ),
            status_code=422,
        )

    upsert = await db_async.upsert_player_from_mojang(uuid=result["uuid"], name=result["name"])
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

    return _partial(request, _ctx(await _build_view(), flash=flash))


@router.post("/players/import", response_class=HTMLResponse)
async def import_unknown(request: Request) -> HTMLResponse:
    server_rows = await db_async.list_servers()
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
        if await db_async.get_player(uuid) is not None:
            continue
        seen_new.add(uuid)
        new_rows.append({"uuid": uuid, "name": record["name"]})

    if new_rows:
        await db_async.insert_players_bulk(new_rows)

    flash = {
        "kind": "ok",
        "message": f"Imported {len(new_rows)} new player(s) from disk.",
    }
    return _partial(request, _ctx(await _build_view(), flash=flash))


# ---------------------------------------------------------------------------
# Cascade-remove modal + handler (PR 4)
# ---------------------------------------------------------------------------


async def _memberships_for(uuid: str) -> list[dict]:
    """Pre-scan every server for memberships matching ``uuid``."""
    server_rows = await db_async.list_servers()
    return [m for m in membership.scan_memberships(server_rows) if m["uuid"] == uuid]


@router.get("/players/{uuid}/remove", response_class=HTMLResponse)
async def remove_modal(
    request: Request, player: dict = Depends(get_player_or_404)
) -> HTMLResponse:
    memberships = await _memberships_for(player["uuid"])
    return templates.TemplateResponse(
        request=request,
        name="_player_remove_modal.html",
        context={"player": player, "memberships": memberships},
    )


async def _cascade_remove(
    docker: aiodocker.Docker, player: dict
) -> tuple[list[str], list[dict]]:
    """Run a per-server remove for every server where this UUID has a
    membership. Returns ``(removed_from, failures)`` where:

      ``removed_from`` is a list of ``"<server_name> (<kind>)"`` strings.
      ``failures``     is a list of ``{server_name, kind, reason}`` dicts.

    Best-effort: a failure on one leg doesn't abort the rest. The flash
    message surfaces both lists so the operator can see exactly what
    state ended up on disk.
    """
    uuid = player["uuid"]
    name = player["name"]

    server_rows = await db_async.list_servers()
    server_by_name = {s["name"]: s for s in server_rows}
    memberships = [
        m for m in membership.scan_memberships(server_rows) if m["uuid"] == uuid
    ]

    removed: list[str] = []
    failures: list[dict] = []

    for record in memberships:
        kind = record["kind"]
        server = server_by_name.get(record["server_name"])
        if server is None:
            # Server was deleted between scan and act — skip rather than
            # raise, surface as a failure so the operator can investigate.
            failures.append(
                {
                    "server_name": record["server_name"],
                    "kind": kind,
                    "reason": "server row vanished mid-cascade",
                }
            )
            continue
        try:
            if server.get("state") == "running":
                cmd = (
                    f"whitelist remove {name}"
                    if kind == "whitelist"
                    else f"deop {name}"
                )
                await server_rcon.run_command(docker, server, cmd)
            else:
                server_dir = Path(server["dir"])
                if kind == "whitelist":
                    membership.remove_whitelist_entry(server_dir, uuid=uuid)
                else:
                    membership.remove_op_entry(server_dir, uuid=uuid)
            removed.append(f"{record['server_name']} ({kind})")
        except server_rcon.RconUnavailable as exc:
            failures.append(
                {"server_name": record["server_name"], "kind": kind, "reason": str(exc)}
            )
        except membership.StaleWriteError:
            failures.append(
                {
                    "server_name": record["server_name"],
                    "kind": kind,
                    "reason": "file changed mid-write — retry",
                }
            )
        except membership.MalformedFileError as exc:
            failures.append(
                {
                    "server_name": record["server_name"],
                    "kind": kind,
                    "reason": f"file failed to parse: {exc}",
                }
            )

    return removed, failures


def _cascade_flash(player_name: str, removed: list[str], failures: list[dict]) -> dict:
    """Build the flash message for a scope=all remove. Format follows
    decision 027 / the slice-7 plan: 'removed from A, B; remove from X
    failed: <reason>'."""
    parts: list[str] = []
    if removed:
        parts.append(f"Removed {player_name} from {', '.join(removed)}.")
    if failures:
        for f in failures:
            parts.append(
                f"Remove {player_name} from {f['server_name']} ({f['kind']}) "
                f"failed: {f['reason']}."
            )
    if not parts:
        parts.append(f"{player_name} had no memberships on disk.")
    return {"kind": "error" if failures else "ok", "message": " ".join(parts)}


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
        return _partial(request, _ctx(await _build_view(), flash=flash))

    if scope == "all":
        removed, failures = await _cascade_remove(docker, player)
        await db_async.delete_player(uuid)
        flash = _cascade_flash(player["name"], removed, failures)
        return _partial(request, _ctx(await _build_view(), flash=flash))

    raise HTTPException(status_code=400, detail="scope must be 'roster' or 'all'")
