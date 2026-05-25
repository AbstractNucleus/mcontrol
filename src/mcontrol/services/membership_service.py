"""Membership service: whitelist / ops flips, cascade-remove, roster view.

Disk files are the source of truth for per-server membership; the DB
roster holds identities only. Running servers route writes through RCON;
stopped servers go through ``membership.*`` direct file edits. This
module owns the routing rule and the cross-server scan used by the
central Players page.

Flash messages return as ``{"kind": "ok"|"error"|"info", "message": str}``
dicts. primitive enough that the route layer can hand them straight
to the template without an adapter.
"""

from pathlib import Path
from typing import Any

import aiodocker

from mcontrol import mojang, server_props
from mcontrol.domain import membership
from mcontrol.infra import db_async, server_rcon

_RCON_VERB = {
    ("whitelist", True): "whitelist add",
    ("whitelist", False): "whitelist remove",
    ("op", True): "op",
    ("op", False): "deop",
}


def _ok(message: str) -> dict[str, str]:
    return {"kind": "ok", "message": message}


def _error(message: str) -> dict[str, str]:
    return {"kind": "error", "message": message}


def _info(message: str) -> dict[str, str]:
    return {"kind": "info", "message": message}


# ---------------------------------------------------------------------------
# Flip a single membership: route to RCON or offline file edit
# ---------------------------------------------------------------------------


async def _apply_running(
    docker: aiodocker.Docker,
    server: dict,
    *,
    kind: str,
    name: str,
    enabled: bool,
) -> dict[str, str]:
    cmd = f"{_RCON_VERB[(kind, enabled)]} {name}"
    try:
        response = await server_rcon.run_command(docker, server, cmd)
    except server_rcon.RconUnavailable as exc:
        return _error(str(exc))
    return _ok(response.strip() or f"{cmd}: ok")


def _apply_offline(
    server: dict, *, kind: str, uuid: str, name: str, enabled: bool
) -> dict[str, str]:
    """Direct file edit. Raises :class:`membership.StaleWriteError` on
    drift so the route can map it to a 409. the running path swallows
    upstream errors into a flash, the offline path lets file-level
    errors propagate."""
    server_dir = Path(server["dir"])
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
    if not wrote:
        return _ok(f"{name} was already {'in' if enabled else 'out of'} the {kind}.")
    verb = "added to" if enabled else "removed from"
    return _ok(f"{name} {verb} the {kind} (offline file edit).")


async def apply_membership(
    docker: aiodocker.Docker,
    server: dict,
    *,
    kind: str,
    uuid: str,
    name: str,
    enabled: bool,
) -> dict[str, str]:
    """Route to RCON (state='running') or offline file edit.

    Returns the flash dict. ``StaleWriteError`` from the offline path is
    intentionally not caught here. the route maps it to 409.
    """
    if server.get("state") == "running":
        return await _apply_running(
            docker, server, kind=kind, name=name, enabled=enabled
        )
    return _apply_offline(server, kind=kind, uuid=uuid, name=name, enabled=enabled)


async def resolve_player_name(server: dict, uuid: str) -> str | None:
    """Best-effort player-name lookup for an RCON command.

    Roster takes precedence. Falls back to whichever name
    appears in the on-disk files (handles the pre-Import case where a
    UUID is on a server but isn't in the roster yet). Returns ``None``
    when no source has a name. the route maps that to 404.
    """
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
    return None


# ---------------------------------------------------------------------------
# Roster: central Players page view + add/import flows
# ---------------------------------------------------------------------------


def _whitelist_disabled_by_server(servers: list[dict]) -> dict[str, bool]:
    """Read each server's ``server.properties`` and return ``{name: True}``
    for servers where ``white-list=false``."""
    out: dict[str, bool] = {}
    for server in servers:
        props = server_props.read_properties(
            Path(server["dir"]) / "server" / "server.properties"
        )
        out[server["name"]] = props.get("white-list", "true").strip().lower() == "false"
    return out


async def build_roster_view() -> dict[str, Any]:
    """Roster + per-row "whitelisted on / op on" summary + unknown count."""
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


async def memberships_for(uuid: str) -> list[dict[str, Any]]:
    """Pre-scan every server for memberships matching ``uuid``."""
    server_rows = await db_async.list_servers()
    return [m for m in membership.scan_memberships(server_rows) if m["uuid"] == uuid]


async def add_player_to_roster(name: str) -> dict[str, Any]:
    """Mojang lookup → upsert. Returns a small result dict the route
    layer translates into HTTP responses.

    Result shape: ``{"status": "ok"|"not_found"|"mojang_error", "flash": dict}``.
    On "ok" the upsert ran; on the others the caller renders the form
    with the error.
    """
    try:
        result = await mojang.lookup_by_name(name)
    except mojang.MojangError:
        return {"status": "mojang_error", "flash": None}

    if result is None:
        return {"status": "not_found", "flash": None}

    upsert = await db_async.upsert_player_from_mojang(
        uuid=result["uuid"], name=result["name"]
    )
    if upsert["created"]:
        flash = _ok(f"Added {result['name']} to the roster.")
    elif upsert["previous_name"] == result["name"]:
        flash = _info(f"{result['name']} is already in the roster.")
    else:
        flash = _info(
            f"{result['name']} is already in the roster "
            f"(was: {upsert['previous_name']})."
        )
    return {"status": "ok", "flash": flash}


async def import_unknown_uuids() -> int:
    """Walk every server's whitelist + ops, upsert UUIDs not yet in the
    roster (first-encountered name wins). Returns the
    number of new rows inserted."""
    server_rows = await db_async.list_servers()
    memberships = membership.scan_memberships(server_rows)

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

    return len(new_rows)


# ---------------------------------------------------------------------------
# Cascade remove (scope=all on /players/{uuid}/remove)
# ---------------------------------------------------------------------------


async def cascade_remove_player(
    docker: aiodocker.Docker, player: dict
) -> tuple[list[str], list[dict[str, str]]]:
    """Run a per-server remove for every server where this UUID has a
    membership. Returns ``(removed_from, failures)``.

      ``removed_from``  list of ``"<server_name> (<kind>)"`` strings.
      ``failures``      list of ``{server_name, kind, reason}`` dicts.

    Best-effort: a failure on one leg doesn't abort the rest. The caller
    composes the flash and hard-deletes the roster row regardless of
    failures.
    """
    uuid = player["uuid"]
    name = player["name"]

    server_rows = await db_async.list_servers()
    server_by_name = {s["name"]: s for s in server_rows}
    memberships = [
        m for m in membership.scan_memberships(server_rows) if m["uuid"] == uuid
    ]

    removed: list[str] = []
    failures: list[dict[str, str]] = []

    for record in memberships:
        kind = record["kind"]
        server = server_by_name.get(record["server_name"])
        if server is None:
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
                    "reason": "file changed mid-write; retry",
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


def cascade_flash(
    player_name: str, removed: list[str], failures: list[dict[str, str]]
) -> dict[str, str]:
    """Build the flash message for a scope=all remove."""
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


# ---------------------------------------------------------------------------
# Per-server players card view
# ---------------------------------------------------------------------------


def per_server_members_view(server_dir: Path) -> tuple[list[dict], list[str]]:
    """Build the combined whitelist+ops view for the per-server card.

    Returns ``(members, malformed_kinds)`` where ``members`` is a list
    of ``{uuid, name, in_whitelist, in_op}`` sorted by name (case-
    insensitive) and ``malformed_kinds`` is a subset of
    ``["whitelist", "ops"]`` for files that failed to parse."""
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
