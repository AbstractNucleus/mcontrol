# Slice 8 — Legacy itzg → scaffold-shape migration

> Lean plan: contract + PR order. Each PR ships an end-to-end working vertical slice; merge in order. The code is the source of truth — this doc is the napkin sketch.

## Goal

Operator opens `atm10` or `monifactory` in the panel, clicks **Migrate to scaffolded shape**, confirms the pre-filled variables, and the row converges on slice-6 output: legacy `Dockerfile` + `entrypoint.sh` deleted, `docker-compose.yml` rewritten to reference `eclipse-temurin:21-jre` directly, `server/start_server.sh` re-rendered from the slice-6 template, and the row stamped `scaffolded_at = now()`. After the click the row is **indistinguishable from a slice-6 scaffold** — Variables card, Regenerate, and Delete behave identically. Decision 014's outcome lands via decision 023's mechanism.

## Scope contract

| | |
|---|---|
| Targets | `atm10`, `monifactory`. Per decision 014, `kobra_kollektivet` is excluded by operator stance. The migration UI renders on every legacy-shape row (including kobra) gated on `scaffolded_at IS NULL`; operator opts in per row. |
| Surface | Per-server detail-page card. **No CLI subcommand, no bulk affordance, no auto-run on discovery.** One operator-initiated click per row. |
| Visibility gate | Card renders when `server.scaffolded_at IS NULL`. Once stamped, the card never reappears for that row. |
| Pre-flight: state | Server must be stopped. Migrate button is disabled when `state='running'`; POST re-checks state at request time and returns 409 on race. Same shape as the Delete flow. |
| Pre-flight: RCON | None. Decision 024 puts `rcon.password` in `server.properties` as operator territory; the legacy fleet's hardcoded `RCON_PASSWORD=rconer` env var was inert under the override-entrypoint pattern, so dropping it changes nothing the operator could observe. Console route surfaces a friendly error post-migration if `enable-rcon=false` or the password is empty (already covered by slice-6 PR 0). |
| Pre-flight: kobra_kollektivet | Verified: nothing required. kobra already runs on `eclipse-temurin:21-jre`, so the base-image change in 014 is moot. Its Dockerfile + entrypoint shape works as-is; converging it on the scaffold shape is opt-in via the same Migrate button if/when the operator wants Variables card + Regenerate on it. |
| Form | Identical fields to `/servers/new`: `memory_budget_gb`, `port`, `server_jar`, `jvm_extra_args` (optional). Same validators (`memory_budget_gb >= 2`, `1024 <= port <= 65535`, `server_jar` non-empty, port not in use by any other row). |
| Pre-population | Best-effort parse of `<dir>/server/start_server.sh` (regex `-Xmx(\d+)[gG]`, regex `-jar (\S+)`, anything between as `jvm_extra_args`) and `<dir>/docker-compose.yml` (first `"<host>:25565"` mapping for `port`). `memory_budget_gb` pre-fills as `parsed_xmx + 2` so the heap stays the same after the slice-6 `-Xmx = budget − 2` derivation. Parse failures leave the field blank — operator confirms in the form regardless. |
| Migration steps (POST) | Re-check state → render templates (Jinja errors caught here, before any IO) → atomic-write `<dir>/docker-compose.yml` → atomic-write `<dir>/server/start_server.sh` (chmod 0o755) → unlink legacy `<dir>/Dockerfile`, `<dir>/entrypoint.sh`, `<dir>/.dockerignore`, `<dir>/.env` (each `missing_ok=True`) → `db.update_variables(...)` → `db.mark_scaffolded(name=...)`. |
| World data | Untouched. Bind mount at `<dir>/server/` is unchanged; the migration only rewrites the two scaffold files and removes four Docker-build files at the root. |
| RCON_PASSWORD env var in legacy compose | Dropped, alongside the rest of the legacy compose. Decision 024 — operator owns RCON in `server.properties`. |
| Idempotency | Migration is idempotent up to the DB stamp. Each file step uses `atomic_write_text` or `unlink(missing_ok=True)`; re-running after a partial success converges on the same end state. POST checks `scaffolded_at IS NULL` at entry and returns 409 if already migrated. |
| Failure mid-stream | If a file step raises after compose is written but before the DB stamp lands, files are mid-migrated. Operator re-clicks Migrate; idempotent operations re-converge. No automatic rollback — restoring the deleted Dockerfile/entrypoint is impossible without source, and the migration is intentionally one-way. |
| `image_base` column | Stays dormant. Currently read-only in `server_detail.html`; nothing writes it. A future migration can drop it alongside `rcon_password` when the cleanup is felt; outside this slice. |
| Scaffolded `container_name` | Falls out of `docker-compose.yml.j2` (`container_name: {{ name }}`). Decision 021's override column is preserved by `db.update_variables` (it doesn't touch `container_name`); operators with a non-default `container_name` keep that value across migration. |
| Path-safety | Same as slice 6: the slug regex on `name` is enforced at row level on insert (slice 3/6); the migration takes `name` from the URL and joins via `(Path(<base>).resolve() / name)` plus a `relative_to` containment check. No new payloads. |
| File ownership | Root, same as slices 4/5/6. No `chown`. |

## Routes

```
GET  /servers/{name}/migrate    → migration card partial (HTMX-fetchable; returns 404 if scaffolded_at is set)
POST /servers/{name}/migrate    → run migration, redirect 303 → /servers/{name}
```

Card is rendered inline on the detail page, gated on `scaffolded_at IS NULL`. The GET endpoint exists so the card can lazy-load its pre-populated form via `hx-get` on first render — keeps the parse off the main detail-page render path.

## Modules

```
src/mcontrol/
  migration.py            # parse_legacy_variables(server_dir) -> dict (best-effort);
                          # legacy_files(server_dir) -> list[Path];
                          # migrate(name, variables, base) -> None.
                          # Pure file IO + small regex parsing; no DB writes.
  routes/
    migrate.py            # GET form / POST run. DB writes happen here, bracketing migration.migrate(...).
```

`migration.py` reuses `scaffolding.render_compose` and `scaffolding.render_start_script` directly — the migration's "target shape" is exactly slice 6's scaffold output, and cribbing the renderers keeps the two paths impossible to drift. `routes/migrate.py` owns the two-write DB bracket (`update_variables` then `mark_scaffolded`) for symmetry with `routes/new_server.py`'s scaffold-then-stamp ordering.

## PR sequence

| # | Ships | Notes |
|---|---|---|
| 0 | `migration.py` module | Pure functions: `parse_legacy_variables(server_dir)` (regex over `start_server.sh` + minimal `docker-compose.yml` port scan, returns a dict with `None` for parse failures), `legacy_files(server_dir)` (returns the four legacy file paths that exist), `migrate(name, variables, base)` (renders templates, atomic-writes the two scaffold files, unlinks legacy files). No DB. No UI. Tests on `tmp_path` with a synthetic `atm10`-shaped fixture. |
| 1 | Migration card + GET/POST routes + decision-028 finalisation | Detail page gains a `_migrate_card.html` block above the bindings card, gated on `scaffolded_at is null`. `GET /servers/{name}/migrate` returns the form partial with pre-populated values. `POST` validates (form errors → 422 re-render), re-checks `state != 'running'` (→ 409), re-checks `scaffolded_at is null` (→ 409 "already migrated"), runs `migration.migrate(...)`, calls `db.update_variables(name=..., variables=...)`, calls `db.mark_scaffolded(name=...)`, returns `HX-Redirect: /servers/{name}`. Update home-page nav copy if the operator-facing language needs adjustment. **Decision 028 lands.** |

A two-PR slice is right-sized: PR 0 isolates the parse/migrate primitives behind pure functions for unit tests; PR 1 wires them into the detail page with the DB stamp. No middle PR — there's no third surface to bisect.

## Pre-flight

**No DB migration required.** `scaffolded_at` (slice 6 PR 2) and `variables` JSONB (slice 2) already exist on `app_mcontrol.servers`. The migration uses the same JSONB shape `routes/new_server.py` writes today — no schema delta.

## Path-safety contract

Carried over from slice 6; restated for the new endpoints:

1. `name` is taken from the URL and matched against the existing slug regex `^[a-z][a-z0-9-]{2,31}$` before any side effect. (`atm10` and `monifactory` fit; the existing legacy rows were inserted under the same constraint.)
2. Server dir derives as `(Path(<base>).resolve() / name)`; `target.relative_to(base)` enforces containment. The slug regex makes traversal payloads structurally impossible.
3. Legacy files unlinked at known fixed paths under the validated `server_dir`: `Dockerfile`, `entrypoint.sh`, `.dockerignore`, `.env`. No globbing; no operator-controlled filenames.

## Decisions register impact

This slice introduces:

- **028 — One-shot legacy-to-scaffold migration; no dual-shape framework.** The migration is per-server, opt-in, and one-way. Once `scaffolded_at` is stamped, the row is treated identically to a slice-6 scaffold for the rest of its life. No feature flag, no rollback button, no "legacy mode" path through the codebase. Adding rather than amending preserves the migration's contract (014 + 023's outcome) as a discoverable artifact in the register; the entry lands on PR 1's commit per the register's "ratified on first implementation" rule.

This slice acts on:

- **014** Migrate atm10 + monifactory to temurin — outcome (atm10 + monifactory running on temurin under mcontrol-managed config) lands here.
- **023** No-Dockerfile scaffold model — the migration's mechanism is exactly 023's "delete Dockerfile + entrypoint.sh, edit docker-compose.yml to point at eclipse-temurin:21-jre directly," with the additional cleanups (`.dockerignore`, `.env`) that 023 implies and 024 forces.
- **024** Server.properties operator-managed — migration drops the legacy `RCON_PASSWORD=rconer` compose env var; RCON config moves to `server.properties` as already documented for the rest of the fleet.
- **021** Per-server `container_name` override + discovery preserves operator edits — `db.update_variables` does not touch `container_name`, so any override survives migration. Generated compose hard-codes `container_name: {{ name }}`, matching slice-6 scaffolded rows.
- **025** Regenerate clobbers against the confirmed diff — post-migration, the Variables card + Regenerate flow takes over for any subsequent edits to the two scaffold files. Migration itself is a one-shot clobber (the legacy compose / start_server.sh are about to be replaced wholesale; a diff-preview modal here adds friction without insight, since the operator's own form values drive the rendered output).
- **026** Delete tombstones — unaffected; migrated rows delete identically to scaffolded rows.
- **020** Pin Docker image references — the only image string the migration writes is `eclipse-temurin:21-jre` baked into `scaffolding/templates/docker-compose.yml.j2`. Same pin granularity as slice 6.

## Deferred / out-of-scope

- **CLI subcommand.** UI button is sufficient for three rows; a CLI surface would duplicate the same DB + file ops behind a second entry point. Add only if the panel is ever unreachable when the migration is wanted.
- **Bulk migrate from the home page.** Two clicks on two rows is not a felt pain; bulk would mostly multiply blast radius.
- **Auto-run migration on app startup or discovery.** Decision 014 originally framed it as a "first import pass"; that framing predates 023's destructive (file-deleting) mechanism. Auto-run for a destructive op without an explicit click is the wrong default.
- **Diff preview before clobber.** The migration is wholesale replacement, not a targeted edit; there is no operator hand-tuning of the legacy compose worth preserving (decision 023 explicitly rejects keeping the Dockerfile pattern). Slice 6's Regenerate flow already covers post-migration edits via diff-preview.
- **Rollback button.** One-way migration; reverting means restoring the deleted `Dockerfile` + `entrypoint.sh` + `.dockerignore` + `.env` from the operator's own backup or git history. Decision 028's "no dual-shape framework" forecloses this.
- **`image_base` column drop.** Lives alongside the `rcon_password` column-drop (slice 6 PR 0 deferred that). One future migration cleans up both dormant columns.
- **kobra_kollektivet automatic conversion.** Decision 014 leaves kobra alone; the Migrate button shows there because `scaffolded_at IS NULL`, but the operator's stated stance is "leave it." The button's existence is harmless — it converts iff clicked.
- **Health banner integration for "this row is legacy and unmigrated."** Per decision 027 the affordances render on every server regardless of `scaffolded_at`; legacy-ness is not a degraded state. Adding a banner would imply "you should fix this," which is exactly the framing decision 014's kobra carve-out rejects.
- **Server-properties RCON setup wizard.** Decision 024 rules this out; operator manages `server.properties` directly via slice-5's editor.

## Resolved during grilling

1. **Surface — UI button vs CLI subcommand vs separate route.** Per-server detail-page card. The legacy rows are already discovered, the operator's natural workflow lands on the detail page, and a CLI subcommand would duplicate the DB+file ops behind a second entry point for no real win. Karpathy: minimum that solves the problem.
2. **Per-server vs fleet-wide button.** Per-server. Three rows; "Migrate all" is bulk machinery for a one-time op.
3. **Pre-population of form vs blank form.** Best-effort parse of `start_server.sh` and `docker-compose.yml`. Operator hasn't run atm10 / monifactory in months and may not remember exact `-Xmx` / jar filenames; pre-population is genuinely useful at zero ongoing cost. Parse failures leave fields blank — form-validation catches what slipped through.
4. **`memory_budget_gb` derivation from legacy `-Xmx`.** Pre-fill as `parsed_xmx + 2` so the heap is preserved (decision 009's 2 GB headroom). Operator can override in the form.
5. **State pre-flight — `created` only or any non-running.** Any non-running. The migration doesn't touch container state; the only requirement is "no live process holding the file shape." Same gate as Delete (decision 026).
6. **RCON pre-flight.** None. Legacy `RCON_PASSWORD=rconer` env var was inert under the override-entrypoint pattern; dropping it is observably a no-op. Decision 024 owns RCON config from here on.
7. **Diff-preview modal before clobber.** Skipped. The two scaffolded files are derived deterministically from the operator's form values; a diff would compare "their typed inputs rendered" against "legacy bytes the operator already chose to abandon." Slice-6 Regenerate covers post-migration edits.
8. **Atomic boundary — wrap entire migration in a transaction?** No. File ops can't participate in a Postgres transaction, and the natural ordering (write target files → unlink legacy → DB stamp) makes each step idempotent on retry. Final DB stamp (`mark_scaffolded`) is the canonical "this row is migrated" signal; absent it, the row is treated as legacy and the operator can re-click.
9. **kobra_kollektivet inclusion.** Excluded per decision 014's explicit carve-out, but the Migrate UI renders on it anyway (gated only on `scaffolded_at IS NULL`). Operator opts in or out per row.
10. **`image_base` column write-through on migration.** Skipped. The column is read-only in templates today and dormant; cleanup belongs with the future schema-cleanup migration that drops `rcon_password`.
