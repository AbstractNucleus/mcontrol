# Slice 7 — Whitelist + ops UI

> Lean plan: contract + PR order. Each PR ships an end-to-end working vertical slice; merge in order. The code is the source of truth — this doc is the napkin sketch.

## Goal

Operator gets a unified Players page with a DB-backed roster and a clear cross-server view, plus a per-server affordance for managing that server's whitelist + ops. Adding a player is a one-time act anchored on a Mojang-resolved UUID; per-server membership is entirely disk-driven, written through RCON when the server is running and through atomic JSON edits when it's offline. Decision 018 is superseded by decision 027.

## Scope contract

| | |
|---|---|
| Roster | Single table `app_mcontrol.players(uuid pk, name not null, added_at default now())`. No per-role flags. |
| Online-mode only | Mojang lookup (`GET https://api.mojang.com/users/profiles/minecraft/{name}`) is a hard dependency for roster-add. Offline-mode servers are out of scope this slice. |
| Per-server membership source of truth | Disk: each server's `<dir>/server/whitelist.json` and `<dir>/server/ops.json`. mcontrol never mirrors membership into the DB. |
| Add-to-roster failure modes | 204 → form error "no Minecraft account with that name". 5xx/timeout → form error "Mojang lookup failed; try again". 200 with UUID already in `players` → upsert; refresh `name` if it differs; surface "Already in roster (was: <old>)". |
| Import button | Walks every server's two files, upserts unknown UUIDs into `players`, takes `name` from the JSON entry. One DB transaction. Returns count of newly-inserted rows. |
| Per-server detail page UI | Combined "Players on this server" list, two checkboxes per row (whitelist, op), one add-from-roster picker that defaults to whitelist-only on add. |
| Central Players page UI | Roster list with per-row read-only summary ("Whitelisted on: …", "Op on: …"). Top-of-page affordance "N memberships on disk for unknown UUIDs — Import" when count > 0. Per-row "Remove from roster" cascades through a confirm modal. |
| Cascade-remove modal | Pre-scans disk for current memberships. Two buttons: **Roster only** (hard-delete `players` row, disk untouched) or **Remove from all servers** (run per-server remove for each membership, then hard-delete). |
| Write mechanics, running | RCON: `/whitelist add <name>`, `/whitelist remove <name>`, `/op <name>`, `/deop <name>`. Surface vanilla's literal response in a flash message. |
| Write mechanics, offline | `file_writer.atomic_write_text` with mtime stale-write check. Read JSON, mutate, serialize, write. Vanilla shape: 2-space indent, list of objects, trailing newline, insertion order. |
| Whitelist toggle | No UI. Operator manages `white-list` / `enforce-whitelist` via slice 5 file editor. Central page renders a small "whitelist disabled" indicator per server column when `white-list=false`. |
| Op level | Always vanilla default (level 4). No level dropdown, no `bypassesPlayerLimit` UI. Decision 027. |
| Legacy gating | None. Affordances render on every server regardless of `scaffolded_at`. `atm10`, `monifactory`, `kobra_kollektivet` get full UI day one. |
| Mtime stale-write check | Same shape as slice 5/6: stat file → load → mutate → atomic write with mtime guard → 409 + "file changed, retry" on drift. |
| RCON 4096-byte limit | Moot. Reads come from disk; writes (`add`/`remove`/`op`/`deop`) have small responses. |
| Health banner additions | Per-server: `whitelist.json` malformed; `ops.json` malformed. Central page: "N memberships on disk for unknown UUIDs" affordance (separate from the per-server banner). |
| Path-safety | `<dir>/server/whitelist.json` and `<dir>/server/ops.json` are derived by `(Path(<base>).resolve() / name / "server" / filename)`. Slug regex from slice 6 still gates `name`. |

## Data shape

`whitelist.json`:

```json
[
  {"uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5", "name": "Notch"}
]
```

`ops.json`:

```json
[
  {"uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5", "name": "Notch", "level": 4, "bypassesPlayerLimit": false}
]
```

The slice writes `level: 4` and `bypassesPlayerLimit: false` for new ops entries; existing entries with non-default values are preserved on round-trip (read existing, mutate the targeted entry, write all back).

## Routes

```
GET    /players                                 → central Players page
POST   /players                                 → form: name → Mojang lookup → upsert players row
POST   /players/import                          → scan all servers' two files, upsert unknown UUIDs
GET    /players/{uuid}/remove                   → cascade-confirm modal (HTMX swap)
POST   /players/{uuid}/remove                   → form: scope ∈ {roster, all} → execute, redirect to /players

GET    /servers/{name}/players                  → render per-server card (HTMX-fetchable)
POST   /servers/{name}/players                  → form: roster_uuid → add (whitelist by default)
POST   /servers/{name}/players/{uuid}/whitelist → form: enabled (bool) → flip whitelist membership
POST   /servers/{name}/players/{uuid}/op        → form: enabled (bool) → flip op membership
```

The per-server card is rendered inline on the existing detail page; the routes above let HTMX swap individual rows on checkbox flip without a full page reload.

## Modules

```
src/mcontrol/
  mojang.py            # async client. lookup_by_name(name) -> {uuid, name} | None | raises MojangError.
  rosters.py           # high-level player roster ops (Mojang lookup → upsert; cascade-remove planner).
  membership.py        # per-server whitelist/ops file ops. read_whitelist(dir), write_whitelist(dir, entries, mtime), …
  routes/
    players.py         # central Players page + roster mutations.
    server_players.py  # per-server card + membership mutations.
```

`membership.py` owns the JSON shape contract (vanilla-style serialize, mtime check, atomic write), and is the only writer of `whitelist.json` / `ops.json` in the codebase. `rosters.py` glues together the roster-side queries and the cascade-remove planner.

## PR sequence

| # | Ships | Notes |
|---|---|---|
| 0 | `players` table + Mojang client | Pre-flight migration applied on bserver (see Pre-flight). `db.py` gains `insert_player`, `get_player`, `delete_player`, `list_players`, `upsert_player_from_mojang`. New `mojang.py` with `lookup_by_name(name)` over `httpx.AsyncClient`. Tests stub the HTTP call. No UI yet. |
| 1 | `membership.py` module | Pure functions: read/write `whitelist.json` and `ops.json`, with mtime stale-write guard. Vanilla-shape serialize. Insertion-order preserve on round-trip. Includes a small "scan all server files for UUIDs" helper used by Import (PR 3) and the cascade pre-scan (PR 4). Tests on tmp_path. |
| 2 | Per-server card + add/flip routes | New card on the server detail page rendered from `membership.py`'s reads. Add-from-roster picker (defaults to whitelist-only). Two checkboxes per row HTMX-swap to `/whitelist` and `/op` endpoints. Running server → RCON; offline → mtime-checked file edit. Surface vanilla responses verbatim on RCON path; 409 on mtime drift. Health banner gains "whitelist.json malformed" and "ops.json malformed" issue types. |
| 3 | Central Players page + Import | `/players` renders the roster + per-row summary ("Whitelisted on: …", "Op on: …"). `POST /players` does the Mojang lookup + upsert. `POST /players/import` walks every server, upserts new UUIDs. Top-of-page affordance shows the unknown-UUIDs count (link to `POST /players/import`). Small per-server-column indicator for `white-list=false`. |
| 4 | Cascade-remove modal + decision-027 finalisation | `GET /players/{uuid}/remove` returns an HTMX modal with the pre-scanned membership list and two confirm buttons. `POST` with `scope=roster` deletes the row only; `scope=all` runs per-server remove (RCON or mtime-checked file edit) for each membership, then deletes. Failure on any cascade leg surfaces partial-completion clearly: "removed from atm10, monifactory; remove from kobra_kollektivet failed: <reason>." Update home-page nav to surface "Players" link. Final decision-027 review pass. |

## Pre-flight (before PR 0 deploys)

Apply on bserver per decision 015:

```sql
-- supabase-server/supabase/migrations/<timestamp>_app_mcontrol_players.sql
create table if not exists app_mcontrol.players (
  uuid uuid primary key,
  name text not null,
  added_at timestamptz not null default now()
);
```

Additive, idempotent. Until applied, PR 0's queries fail with `relation "app_mcontrol.players" does not exist`.

## Path-safety contract

Carried over from slice 5 / 6; restated for the new write sites:

1. `name` (server name) gates entry into all per-server membership routes via the existing slug regex.
2. Whitelist/ops paths derive as `(Path(<base>).resolve() / name / "server" / "whitelist.json")` (and `ops.json`); both must live under `Path(<base>).resolve()`. The slug regex makes traversal payloads structurally impossible.
3. UUIDs from the URL (`/players/{uuid}/...`, `/servers/{name}/players/{uuid}/...`) are validated as `uuid.UUID(value)` before hitting the DB or disk.

## Decisions register impact

This slice introduces:

- **027** — DB-backed player roster, disk-only per-server membership, online-mode-only Mojang lookup, no level dropdown, no toggle UI, cascade-confirm removal. Supersedes **018**.

This slice acts on:

- **011** No app-level user identity — applies; the `players` table is about Minecraft identities, not panel users. No audit columns.
- **015** DB migrations live in supabase-server — the `players` migration follows this rule.
- **016** FastAPI + Jinja + HTMX — Players page, per-server card, and cascade modal are HTMX swaps in the established pattern.
- **024** Server.properties operator-managed — slice 7 reads `white-list` to render the per-server indicator on the central page; never writes server.properties.

## Deferred / out-of-scope

- **Offline-mode server support.** Mojang is a hard dependency for adds.
- **Op levels 1–3 and `bypassesPlayerLimit`.** Operator manages via slice 5 file browser + restart.
- **Whitelist on/off toggle UI.** Operator manages via slice 5 file browser.
- **Bulk operations from the central page.** "Add Alice to all servers" / "Remove Alice from all servers" — defer until felt-need (the cascade-remove modal already covers the destructive-bulk case).
- **Mojang re-resolve button on per-row.** When vanilla returns "Player does not exist" on RCON `whitelist add` (rare stale-name after a Mojang rename), operator's recovery is "remove from roster, re-add by name." A dedicated re-resolve button is a small follow-up if the failure mode is felt.
- **Caching Mojang responses.** No cache. Single-operator use, <100 lookups/year, Mojang's rate limits are generous.
- **Soft-delete on `players`.** Hard delete only; cascade modal makes the consequence explicit.
- **Player detail page.** All cross-server visibility lives in the per-row summary on the central page.
- **Search/filter on the central page.** Defer until the roster grows past trivial.
- **"Empty trash" / clean-up of dangling on-disk UUIDs.** Operator removes via slice 5 file editor when needed.

## Resolved during grilling

1. **Online vs offline mode:** online-mode-only. Operator confirmed all servers run with `online-mode=true`.
2. **Op level dropdown:** dropped. Vanilla can't hot-reload `ops.json`, and "always 4" matches the operator's actual usage. Granular levels are a file-browser task.
3. **Whitelist enforcement toggle:** dropped. Decision 024's operator-managed posture wins; the central page's small "whitelist disabled" indicator covers the legibility gap.
4. **Per-server membership in DB:** rejected. Disk is the only source of truth. The "schemas for servers" instinct resolved to render-time disk reads.
5. **Roster shape:** identity-only (`uuid`, `name`, `added_at`). No role flags — ops and whitelist share the page.
6. **Cascade on roster removal:** confirm modal with two buttons. Single-button delete hides the consequence; soft-delete adds a flag this slice doesn't otherwise need.
7. **Mtime stale-write check on offline edits:** yes. Reuses slice 5/6 pattern.
8. **Default for per-server picker add:** whitelist-only. Promoting to op is a deliberate second tick.
9. **Disk write format:** vanilla-shape (2-space indent, list of objects, trailing newline, insertion-order on round-trip). Operator formatting wouldn't survive a player join anyway.
10. **Legacy server gating:** none. Whitelist/ops affordances apply identically to scaffolded and legacy rows.
