# Slice 6 — New-server scaffolding + variables

> Lean plan: contract + PR order. Each PR ships an end-to-end working vertical slice; merge in order. The code is the source of truth — this doc is the napkin sketch.

## Goal

Operator clicks "New server" in the panel, fills in name + memory budget + port + jar filename, and gets a fully scaffolded directory ready to receive uploaded jars/mods via slice 5. The detail page also gains a Variables card for editing the four runtime knobs that drive the scaffold; changes that affect rendered files trigger an explicit "Regenerate" with diff preview. Slice-4's RCON-password-in-`.env` machinery is removed in PR 0 — `server.properties` becomes the single source of truth for the RCON password.

## Scope contract

| | |
|---|---|
| New-server form fields | `name`, `memory_budget_gb`, `port`, `server_jar` (filename string), `jvm_extra_args` (optional). |
| Name validation | `^[a-z][a-z0-9-]{2,31}$`. Reject if dir already exists or DB row exists. |
| Port validation | Integer 1024–65535. Reject if any other row's `variables->>'port'` matches. Legacy compose-file ports + non-mcontrol host bindings are not checked — `compose up` failures with "address already in use" are surfaced cleanly. |
| Memory budget | Integer GB ≥ 2. Drives `-Xmx{budget − 2}g` and `mem_limit: {budget}g` per decision 009. |
| Jar | Filename string only. Slice 5 handles the actual upload after scaffold. Form has a "you'll upload the jar after scaffolding" hint. |
| Scaffold output | Two files: `<dir>/docker-compose.yml` and `<dir>/server/start_server.sh`. No Dockerfile, no entrypoint.sh, no `.env` (decision 023 + 024). |
| DB row | New rows are born with `state='scaffolding'`, then transitioned to `state='created'` after files write succeeds. `scaffolded_at = now()` is set on the same final write — its presence is the canonical "this row is mcontrol-scaffolded" signal. |
| Variables card visibility | Rendered only when `scaffolded_at is not null`. Legacy rows (atm10, monifactory, kobra_kollektivet, anything pre-slice-6) see no Variables card; operator edits their compose directly via slice-5 file browser. |
| Stale derivation | On every detail-page render: re-render templates against current variables, compare to disk bytes. `scripts_stale = (rendered_compose != disk_compose) or (rendered_start != disk_start)`. No stored bool. |
| Regenerate flow | Diff capture stamps mtimes; confirm endpoint re-stats and aborts with "Files changed — re-show diff" on drift (decision 025). Atomic-write via the slice-5 `file_writer.atomic_write_text` helper. |
| Health banner | Inline strip at the top of detail page (no modals). Issue types this slice ships: variables-incomplete, missing-scaffold-file, stuck-`scaffolding`-state. Per-affordance contextual messages where the affordance is the natural place to surface a cause. |
| Delete flow | Refuse when `state='running'` (button disabled, 409 on POST). Type-name confirm. On confirm: rename `<dir>` to `<base>/.deleted-<name>-<unix-ts>/`, then `db.delete_server(name)`. Decision 026. |
| Discovery interaction | Discovery learns to skip `entry.name.startswith(".")`, so tombstoned dirs don't resurrect. Same one-line filter handles `lost+found`, `.git`, etc. |
| RCON password source | `server/server.properties` (parsed live by the console route). No `.env`, no DB column write. Decision 024. |
| Path-safety | Same contract as slice 5 — name slug feeds a single `Path(<base>) / name` join, validated to live under `Path(<base>).resolve()`. The slug regex forbids `/`, `.`, and any path-traversal payload by construction. |
| File ownership | Root, same as slice 4 / 5. No `chown`. |

## Scaffold templates

Live in `src/mcontrol/scaffolding/templates/` — distinct from `src/mcontrol/templates/` (the panel UI's HTML) so render targets don't tangle.

`docker-compose.yml.j2`:

```yaml
services:
  {{ name }}:
    image: eclipse-temurin:21-jre
    container_name: {{ name }}
    restart: unless-stopped
    mem_limit: {{ memory_budget_gb }}g
    ports:
      - "{{ port }}:25565"
    volumes:
      - ./server:/data
    working_dir: /data
    command: ["./start_server.sh"]
    stdin_open: true
    tty: true
```

`start_server.sh.j2`:

```bash
#!/usr/bin/env bash
set -euo pipefail
exec java -Xmx{{ xmx_gb }}g {{ jvm_extra_args }} -jar {{ server_jar }} nogui
```

The scaffolding module owns `xmx_gb = memory_budget_gb - 2` and the rendering loop. Files are written via `file_writer.atomic_write_text` so the regen path uses the same atomicity contract as slice 5's editor.

## PR sequence

| # | Ships | Notes |
|---|---|---|
| 0 | RCON simplification | Delete `env_writer.py`, `passwords.py`, their tests. Simplify `routes/lifecycle.py` (drop `_ensure_env_matches_db` and the compose-up-on-env-change branch — Start/Stop/Restart now hit the Docker API directly). Rewrite `routes/console.py` to parse `rcon.password=` from `<dir>/server/server.properties` at SSE connect time. Surfaces a friendly error when `enable-rcon=false` or the file is missing. **Decision 024 lands.** No schema change required — the `app_mcontrol.servers.rcon_password` column becomes dormant and stays for now. |
| 1 | `scaffolding/` module | Pure function: `scaffold(name, vars, base) -> None`. Renders the two templates, writes them. No UI yet, no DB writes — that's PR 2. Easiest to test in isolation. **Decision 023 lands.** |
| 2 | New-server form + endpoint | Button on home page → `/servers/new` form; POST validates, follows the DB-first ordering: insert row with `state='scaffolding'` + variables, mkdir + scaffold files, update row with `state='created'` + `scaffolded_at=now()`. On any exception between the two DB writes: best-effort `rmtree(<dir>)` + `db.delete_server(name)`, re-raise as 500. Redirect on success to `/servers/{name}`. **Pre-req: scaffolded_at migration applied on bserver — see Pre-flight.** |
| 3 | Variables card + Health banner shell | Inline card on detail page, gated on `server.scaffolded_at is not null`. Read shows current variables; edit form HTMX-swaps to a write-back endpoint that updates `variables` JSONB. Stale flag derived on render. Health banner ships at the top of the detail page with three issue types: variables-incomplete (KeyError on render), missing-scaffold-file (compose or start_server.sh absent), stuck-`scaffolding` state (insert succeeded, scaffold-files step did not). Per-affordance messages on the Variables card itself when render fails. |
| 4 | Regenerate-scripts + diff preview | Button on Variables card when `scripts_stale` is true. POST endpoint renders templates, captures both files' mtimes, returns a unified diff in a modal with the mtimes as hidden form fields. Confirm endpoint re-stats both files; if either mtime drifted, returns "Files changed — re-show diff" without writing. On match, atomic-writes both files. **Decision 025 lands.** |
| 5 | Delete-server flow + tombstone + discovery filter | Delete button on detail page, `disabled` when `state='running'`, with tooltip "Stop the server before deleting." Type-name confirm modal. POST: re-checks running state (409 if running), renames `<dir>` → `<base>/.deleted-<name>-<unix-ts>/`, calls `db.delete_server(name)`. One-line filter added to `discovery.run_discovery`: `if entry.name.startswith("."): continue`. **Decision 026 lands.** |

## Pre-flight (before PR 2 deploys)

Apply on bserver per decision 015:

```sql
-- supabase-server/supabase/migrations/<timestamp>_app_mcontrol_scaffolded_at.sql
alter table app_mcontrol.servers
  add column if not exists scaffolded_at timestamptz null;
```

Additive, idempotent, doesn't touch existing rows. Until applied, PR 2's INSERT path will fail with `column "scaffolded_at" does not exist`.

## Path-safety contract

Carried over from slice 5; restated for the new endpoints:

1. Name slug is regex-validated server-side before any side effect (`^[a-z][a-z0-9-]{2,31}$`).
2. Directory join: `(Path(<base>).resolve() / name)`. Result must live under `Path(<base>).resolve()`. The slug regex forbids `/` and `.`, so this check is belt-and-suspenders rather than load-bearing.
3. Tombstone path on Delete: `Path(<base>).resolve() / f".deleted-{name}-{int(time.time())}"`. Same containment rule.

## Decisions register impact

This slice introduces:

- **023** — No-Dockerfile scaffold model (supersedes 001).
- **024** — RCON password operator-managed in `server.properties` (supersedes 010).
- **025** — Regenerate clobbers operator edits *against the confirmed diff*; mtime drift between diff and confirm aborts.
- **026** — Delete tombstones via `.deleted-<name>-<unix-ts>` rename; discovery skips `.`-prefixed directories.

This slice acts on:

- **009** Single memory-budget knob — `xmx_gb = memory_budget_gb − 2` lives in the scaffolding module.
- **012** Scaffold + file/upload UI — slice 5 closed the file/upload half; this slice closes the scaffold half.
- **013** Bespoke variable schema — Variables card is the canonical editor for the four scaffold-driving fields. `motd` and `rcon_enabled` remain in the JSONB schema but aren't surfaced in the UI; they're operator-managed in `server.properties`.
- **014** Migrate atm10 + monifactory to temurin — the migration mechanism becomes "delete Dockerfile + entrypoint.sh, edit compose to point at `eclipse-temurin:21-jre` directly" rather than "rewrite Dockerfile and rebuild." 014's outcome is unchanged; only the steps change.
- **015** DB migrations live in supabase-server — the `scaffolded_at` migration follows this rule.
- **016** FastAPI + Jinja + HTMX — Variables card and Regenerate diff modal are HTMX swaps in the established pattern.
- **020** Pin Docker image references — the `eclipse-temurin:21-jre` reference in the scaffold template is the only upstream image string this slice introduces; it's pinned-by-template-text, bumps are one-line PRs.
- **021** Per-server `container_name` override + discovery preserves operator edits — generated compose sets `container_name: {{ name }}`; the bindings UI from slice 4 keeps working unchanged on scaffolded rows.

## Deferred / out-of-scope

- **Loader installers** (Forge / NeoForge / Fabric / Paper auto-install). Decision 012 explicitly rejects these for v1.
- **Modpack import** (`.mrpack`, CurseForge zip). Same rejection.
- **Variable history / audit.** Decision 011 — no user identity, no audit columns.
- **Dry-run scaffold** (preview without writing). Form-validation catches the realistic failure modes (name conflict, port collision); a separate dry-run mode adds surface area for no real win.
- **Whitelist + ops UI** (decision 018). Lands in its own slice.
- **Health banner extension to RCON-config + server.properties diagnostics.** This slice ships only scaffold-shape integrity issues. RCON state, server.properties absence, etc. land in a future polish slice.
- **"Convert legacy server to scaffolded" affordance.** Operator can hand-rewrite a legacy server's compose into scaffold shape, but mcontrol won't offer a one-click migration this slice.
- **"Empty trash" affordance for tombstoned dirs.** Permanent purge is via shell `rm -rf` for now.
- **Server.properties write-through for `motd` / `rcon_enabled`.** These DB columns exist (decision 013) but the UI doesn't surface them. A future slice can add a server.properties merge-write if it's worth the complexity.
- **`.env` cleanup migration.** The dormant `app_mcontrol.servers.rcon_password` column stays in place; a future migration can drop it once we're confident nothing reads it.

## Resolved during grilling

1. **Image tag in compose:** moot — no per-server image, scaffold uses upstream `eclipse-temurin:21-jre` directly.
2. **Stale derivation:** derived on render, not stored. Auto-detects template-version drift on mcontrol upgrades for free.
3. **Delete-server-with-running-container:** refuse, two-step. Decision 026.
