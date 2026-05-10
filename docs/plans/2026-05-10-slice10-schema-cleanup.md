# Slice 10 — Schema cleanup: drop dormant `rcon_password` + `image_base`

> Lean plan: contract + PR order. The cleanup is single-PR; this doc captures the
> sequencing contract between the mcontrol code change and the supabase-server
> migration that the operator runs by hand.

## Goal

Drop two columns that successive decisions left dormant on
`app_mcontrol.servers`:

- **`rcon_password`** — superseded by decision 024 (operator owns
  `rcon.password` in `server.properties`). Slice-6 PR 0 removed
  `env_writer.py` / `passwords.py` and the `_ensure_env_matches_db` branch in
  `routes/lifecycle.py`. Decision 024 itself notes the column "becomes dormant;
  a future migration can drop it once we're confident nothing reads it." That
  confidence has now been verified against `src/mcontrol/`.
- **`image_base`** — read-only in templates today, never written by any
  code path. Slice 8's plan explicitly defers the drop to land "alongside
  `rcon_password`" (slice 8 plan, "Deferred / out-of-scope" §10).

The mcontrol PR removes every read of either column from the running app, so
the supabase-server `ALTER TABLE … DROP COLUMN …` migration that the operator
applies by hand on bserver (decision 015) cannot 500 the panel when it runs.

## Scope contract

| | |
|---|---|
| Surface | One template line, one `_row()` test fixture parameter, three test fixture dicts. No route changes, no `db.py` changes. |
| Audit invariant | `rg "rcon_password\|image_base" src/mcontrol/` returns zero hits after this slice. Tests reflect the post-migration row shape: neither key appears in fixture dicts. |
| `db.py` | Untouched. `db.list_servers` / `db.get_server` use `select("*")`, so once the columns are gone from Postgres they stop arriving in the dict — no Python change needed. Slice-6 PR 0 already removed every writer. |
| Health-banner / variables / migration / regenerate / scaffolding flows | All unaffected. None of them ever read or wrote the dropped columns. |
| Test fixture cleanup | Drop both keys from every fixture row dict and from the `_row()` helper signature. Delete the dedicated `test_server_detail_handles_null_image_base` test — it asserts template handling for a column that no longer exists. Drop the body assertion for `eclipse-temurin:21-jre` in the happy-path detail test (the string is no longer rendered into the page). |
| Ordering precondition | mcontrol PR is **merged and deployed** before the supabase-server SQL runs. If the SQL ran first, the running app would still successfully render — but a test-run against a still-live image_base column would pass against an unrepresentative DB shape. Once the PR ships, the column is purely DB-side ballast and the operator can run the SQL on their own cadence. |
| RLS / grants / dependent objects | None expected. `app_mcontrol.servers` has no views, no generated columns, no foreign keys pointing at either column. Operator confirms with `\d+ app_mcontrol.servers` in psql before running the DROP. |
| Rollback | `ALTER TABLE app_mcontrol.servers ADD COLUMN rcon_password text;` and `ADD COLUMN image_base text;` re-create the columns as nullable. No data preserved (column drops are destructive in the supabase-server convention) — re-adding leaves NULLs in every row, which is the same shape the columns held immediately before this slice. |

## Files touched

```
src/mcontrol/
  templates/server_detail.html      EDIT — remove the "base image" dt/dd pair (one block).

tests/
  test_server_detail.py             EDIT — drop image_base param from _row(),
                                           drop rcon_password / image_base from
                                           every fixture dict, remove
                                           test_server_detail_handles_null_image_base,
                                           drop the eclipse-temurin assertion.
  test_files.py                     EDIT — drop both keys from the one fixture dict
                                           in test_server_detail_renders_files_pane.
  test_server_resources.py          EDIT — drop both keys from the one fixture dict
                                           in test_detail_page_mounts_resources_card_above_metadata.

docs/
  plans/2026-05-10-slice10-schema-cleanup.md   NEW — this document.
  decisions.md                                 EDIT — append decision 029 + status row.
```

`db.py` is intentionally not in this list. Slice-6 PR 0 is the canonical
"reads + writes removed" change for `rcon_password`; `image_base` was never
read or written at the wrapper layer (template-only). Both keys disappear
from the dicts the wrapper returns the moment Postgres stops including them
in `select("*")`.

## PR sequence

| # | Ships | Notes |
|---|---|---|
| 0 | Single PR — template + test cleanup + plan + decision 029 | One vertical: edit `server_detail.html`, edit three test files, write this plan, append decision 029. `uv run pytest -v` and `uv run ruff check .` both green. Squash-merge to main. After merge + deploy of the mcontrol container on bserver, the operator runs the supabase-server migration below. |

## Supabase-server migration spec (operator runs by hand on bserver)

Per decision 015, schema migrations live in `bserver:~/repos/supabase-server/`,
not in this repo. The operator hand-creates a migration file with the
following SQL, then applies it via `make migrate` on bserver:

```sql
-- bserver:~/repos/supabase-server/supabase/migrations/<timestamp>_app_mcontrol_drop_dormant_columns.sql

alter table app_mcontrol.servers
    drop column if exists rcon_password,
    drop column if exists image_base;
```

`drop column if exists` so re-running the migration on a partially-migrated
DB is a no-op rather than an error. Both columns are nullable text with no
constraints, no indexes, no foreign keys, no view dependencies — drop is a
single metadata change in Postgres, not a table-rewrite.

**Ordering precondition (must hold):**
1. This mcontrol PR is **merged** to main.
2. The bserver `app` container is **rebuilt and restarted** so the running
   panel comes from a binary that doesn't reference either column.
3. Only **then** does the operator run the supabase-server migration.

If the SQL runs first, the running panel would still render (no read site
exists post-step-1, but pre-step-1 the template still tries to read
`server.image_base`; supabase-py returns `None` for a missing key in a
`select("*")` payload, so the Jinja `{% if server.image_base %}` branch
silently goes to the em-dash placeholder rather than 500-ing — the
template is null-safe by construction). The ordering above is still the
right discipline: do the code change first, run the SQL second, so the DB
shape is always at least as wide as what the running app reads.

**Pre-flight on bserver before running the migration:**

```sql
\d+ app_mcontrol.servers
```

Confirm: no view definitions reference either column, no foreign keys
point at them, no triggers consume them. Both columns appear as plain
nullable `text` with no `not null` / `default` / index annotations. If
anything has accreted, halt and resolve before running the DROP.

**Verification after running the migration:**

```sql
\d+ app_mcontrol.servers
-- expected: column list contains id, name, container_name, dir, state,
-- variables, scaffolded_at, created_at, updated_at — and nothing else.

select count(*) from app_mcontrol.servers;
-- expected: row count unchanged (column drop is row-preserving).
```

Then sanity-check the running panel: load the home page, click into a
server detail page, confirm the page renders. The metadata `<dl>` no
longer contains the "base image" row; everything else (directory, last
seen, lifecycle controls, resources card, files pane, log + console panes,
players card) is unchanged.

## Decisions register impact

This slice **adds decision 029**: "Drop dormant `rcon_password` +
`image_base` columns." Status = Accepted. Records the cleanup;
references decisions 010, 015, 023, 024, 027 for the antecedents.

No prior decision is superseded. Decision 010 was already superseded by
024 in slice-6 PR 0; decision 024 itself flagged the column drop as a
future migration; slice 8's plan (which lands decision 028) explicitly
deferred `image_base` to "alongside `rcon_password`." This slice is
the closing-bracket on those notes, not a re-litigation.

## Deferred / out-of-scope

- **Any other column drop.** `app_mcontrol.servers.scaffolded_at`,
  `app_mcontrol.servers.container_name`, etc. all carry live behaviour.
  This slice is single-purpose: the two columns successive decisions
  flagged as dormant. Surveying the schema for other dormant columns is
  a future cleanup if the felt need arises.
- **Running the supabase-server SQL.** Operator hand-applies on bserver
  per decision 015. mcontrol is the wrong place to encode that step.
- **`app_mcontrol.players` schema changes.** Decision 027 is fine as-is;
  no roster columns are dormant.
- **`db.py` typing improvements.** Now that the row shape is shrinking,
  a `TypedDict` for the `servers` row would catch missing-key bugs at
  type-check time. Pre-existing absence; not this slice's job.
- **Removing the `image_base` references from historical slice plan
  docs (1, 2, 3, 4).** Plans are append-only history per the project's
  convention; rewriting them to match the post-migration schema would
  obscure the decision trail. The decisions register and this slice's
  doc carry the corrected forward-looking shape.
