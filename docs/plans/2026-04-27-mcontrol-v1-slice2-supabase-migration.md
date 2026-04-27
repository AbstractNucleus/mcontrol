# mcontrol v1 — Slice 2: Supabase Migration for `app_mcontrol` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `app_mcontrol` schema and `app_mcontrol.servers` table in the shared Supabase Postgres on bserver, exposed via PostgREST so slice 3's Python `supabase` SDK can read/write it with the service-role key.

**Architecture:** Per decision 015, all DDL for `app_mcontrol` lives in `bserver:~/repos/supabase-server/supabase/migrations/<timestamp>_<name>.sql`, applied via `make migrate`. The migration creates a single table with the columns slices 3–7 will need (RLS enabled with no policies — service-role bypasses RLS per decision 011, anon/authenticated get nothing). PostgREST is then taught to expose the new schema by appending `app_mcontrol` to `PGRST_DB_SCHEMAS` in `docker-compose.yml` and restarting the `postgrest` container only.

**Tech Stack:** PostgreSQL 15 (via Supabase image), PostgREST, `make migrate` (wraps `scripts/migrate.sh` which hashes each migration — files are immutable once applied, so the SQL must be right the first time).

---

## Scope of this plan

This plan delivers **Slice 2 of v1 only — the database schema for `mcontrol`**. The work happens entirely in the `supabase-server` repo on bserver. **No code lands in this repo (`mcontrol`).** Slice 3 picks up immediately afterwards in this repo to consume the new schema.

## Decisions register references

This slice acts on:
- **007** Shared Supabase, schema `app_mcontrol`
- **010** RCON secrets in DB; `mcontrol` writes `.env` (the `rcon_password` column)
- **011** `SERVICE_ROLE_KEY` server-side; no app-level user (no RLS policies; RLS is enabled-but-empty so anon/authenticated get zero rows by default)
- **013** Bespoke variable schema in `servers.variables` JSONB
- **015** DB migrations live in `supabase-server`, not here

Deferred to later slices: `whitelist`/`ops` tables (slice 7 may add them; for v1 the on-disk JSON is the source of truth per decision 018, so we don't add DB tables for them in slice 2).

## Assumptions (surfaced, not buried)

1. The operator has SSH access to `bserver` via the alias `ssh bserver`. The `supabase-server` repo is at `/home/abstract/repos/supabase-server/` on bserver and the operator can `cd` there.
2. `make migrate` uses the existing `scripts/migrate.sh` flow that records each migration's SHA-256 in `public._migrations` and refuses to re-apply or modify. This means **the migration SQL must be correct the first time** — if you need to fix something, write a new migration with a later timestamp; do not edit the original after it has been applied.
3. `app_mcontrol` is a fresh schema. No prior migration touches it. (Verified by checking `supabase/migrations/` is empty apart from `.gitkeep` — confirmed via `gh api` at plan-write time.)
4. The Supabase Postgres user `service_role` already exists and bypasses RLS — this is a Supabase invariant; the migration grants it nothing extra.
5. The `authenticator` role (used by PostgREST) needs `USAGE` on the new schema for PostgREST to even attempt to introspect it; the `service_role` role needs `USAGE` + `ALL` on the table for SDK calls. We grant these explicitly. We do **not** grant anything to `anon` or `authenticated` — `mcontrol` is tailnet-only and uses the service-role key.
6. PostgREST needs `app_mcontrol` added to its `PGRST_DB_SCHEMAS` env var to expose the schema's tables via REST. Without that, the `supabase-py` SDK call `client.schema('app_mcontrol').table('servers').select(...)` will return `Schema 'app_mcontrol' does not exist or is not exposed`. The change is to `bserver:~/repos/supabase-server/docker-compose.yml`, then `docker compose up -d postgrest` to restart only that one container — the rest of the stack is unaffected.
7. The migration timestamp must be greater than every existing one (`scripts/migrate.sh` enforces lexicographic ordering). Use `date +%Y%m%d%H%M%S` on bserver to generate one at write time.
8. Slice 1's `mcontrol` deployment is already running on bserver and has `SUPABASE_URL=https://api.noelkleen.com` + `SUPABASE_SERVICE_ROLE_KEY=<...>` in its `.env`. The slice-2 migration does not touch the running `mcontrol` container; the schema simply becomes available for slice 3 to consume.

## File changes outside this repo

```
bserver:~/repos/supabase-server/
└── supabase/migrations/
    └── <timestamp>_create_app_mcontrol.sql        §2 (new)

bserver:~/repos/supabase-server/
└── docker-compose.yml                              §2 (modify: PGRST_DB_SCHEMAS)
```

This repo (`mcontrol`) is **not modified by slice 2**.

---

# Pre-flight

- [ ] **P1: SSH to bserver and `cd` to the supabase-server repo**

```bash
ssh bserver
cd ~/repos/supabase-server
```

Expected: prompt now in `~/repos/supabase-server/` on bserver.

- [ ] **P2: Verify the working tree is clean and up to date**

Run: `git status && git pull --ff-only`
Expected: `nothing to commit, working tree clean`, then `Already up to date.` (or a fast-forward summary if the remote moved). If the tree is dirty, stop and ask the operator before proceeding — `migrate.sh` will not undo a half-applied state cleanly.

- [ ] **P3: Verify the migrations directory state**

Run: `ls -la supabase/migrations/`
Expected: only `.gitkeep` (and `.` / `..`). If other migration files exist, scan their timestamps so that step 1 below picks a strictly-greater one.

- [ ] **P4: Confirm the stack is up**

Run: `docker compose ps db postgrest`
Expected: both services in state `running`. If either is down, run `docker compose up -d` first — `make migrate` requires `db` to accept connections, and the PostgREST restart in Task 5 requires `postgrest` to already exist.

- [ ] **P5: Confirm `mcontrol`'s service-role key is in place**

Run: `grep -E '^(SERVICE_ROLE_KEY|ANON_KEY)=' .env | sed 's/=.*/=<set>/'`
Expected: both lines print `<set>` (no values shown). If either is empty, slice 3 will not be able to authenticate; surface this to the operator before proceeding.

---

# Task 1: Generate the migration filename

**Files:**
- Create (next step): `supabase/migrations/<timestamp>_create_app_mcontrol.sql`

- [ ] **Step 1: Generate the timestamp on bserver**

Run: `date +%Y%m%d%H%M%S`
Expected: a 14-digit string like `20260427143055`. **Note this exact value** — every step below uses it.

(Plan-author convention for the rest of this document: replace `<TS>` with the value generated here.)

- [ ] **Step 2: Sanity-check the timestamp is greater than any existing migration**

Run: `ls supabase/migrations/*.sql 2>/dev/null | head -5`
Expected: no output (no `.sql` files yet). If any do exist, verify your `<TS>` is lexicographically larger than every filename's timestamp prefix.

---

# Task 2: Write the migration SQL

**Files:**
- Create: `supabase/migrations/<TS>_create_app_mcontrol.sql`

- [ ] **Step 1: Create the migration file**

Run (on bserver, replacing `<TS>`):

```bash
cat > supabase/migrations/<TS>_create_app_mcontrol.sql <<'SQL'
-- mcontrol — schema for the Minecraft + Docker control panel.
-- Decisions: 007 (shared Supabase, schema app_mcontrol),
-- 010 (RCON secrets in DB), 011 (SERVICE_ROLE_KEY server-side, no app-level user),
-- 013 (bespoke variable schema in servers.variables JSONB),
-- 015 (DB migrations live in supabase-server, not in mcontrol).

create schema if not exists app_mcontrol;

-- Roles:
--   service_role bypasses RLS by Supabase invariant; mcontrol uses this role.
--   authenticator is the role PostgREST connects as; it needs USAGE so PG can
--     introspect the schema for the REST API surface.
--   anon and authenticated get nothing — mcontrol is tailnet-only (decision 003)
--     and uses the service-role key (decision 011).
grant usage on schema app_mcontrol to service_role, authenticator;

create table app_mcontrol.servers (
    id              uuid primary key default gen_random_uuid(),
    name            text not null unique,
    dir             text not null,
    image_base      text,
    state           text not null default 'unknown',
    variables       jsonb not null default '{}'::jsonb,
    rcon_password   text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

comment on table  app_mcontrol.servers              is
    'One row per Minecraft server discovered under SERVER_BASE_PATH (decision 008). Source of truth for per-server config and secrets.';
comment on column app_mcontrol.servers.name         is
    'Server identifier == directory name on disk under SERVER_BASE_PATH; also the docker container name.';
comment on column app_mcontrol.servers.dir          is
    'Absolute path to the server''s directory on the host (e.g. /home/abstract/servers/minecraft/atm10).';
comment on column app_mcontrol.servers.image_base   is
    'Base image used by the per-server Dockerfile (e.g. eclipse-temurin:21-jre, decision 001). Null until first inspected.';
comment on column app_mcontrol.servers.state        is
    'Last-seen container state (created/running/restarting/exited/paused/dead/unknown). Refreshed by mcontrol''s discovery routine.';
comment on column app_mcontrol.servers.variables    is
    'Per-server runtime variables (decision 013): memory_budget_gb, motd, port, server_jar, jvm_extra_args, rcon_enabled.';
comment on column app_mcontrol.servers.rcon_password is
    'Random RCON password mcontrol generates and writes to <dir>/.env (decision 010). Source of truth lives here; the on-disk file is derived.';

-- Touch updated_at on every row update.
create or replace function app_mcontrol.touch_updated_at()
    returns trigger
    language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

create trigger servers_touch_updated_at
    before update on app_mcontrol.servers
    for each row execute function app_mcontrol.touch_updated_at();

-- Enable RLS with no policies. Effect: anon/authenticated get zero rows;
-- service_role bypasses RLS and sees everything. This is the decision-011
-- posture (no app-level user concept; SERVICE_ROLE_KEY is the only caller).
alter table app_mcontrol.servers enable row level security;

-- Explicit grants for service_role on the table (RLS bypass means it sees the
-- rows, but it still needs the privilege to operate on them). authenticator
-- gets nothing on the table itself; PostgREST switches into service_role for
-- service-role-key requests, which is what we want.
grant all on app_mcontrol.servers to service_role;
SQL
```

Expected: file written, no shell error.

- [ ] **Step 2: Inspect the file you just wrote**

Run: `cat supabase/migrations/<TS>_create_app_mcontrol.sql | head -20 && echo '...' && wc -l supabase/migrations/<TS>_create_app_mcontrol.sql`
Expected: header comment is correct, line count is in the 50–70 range. If the file is empty or truncated, the heredoc failed — re-run step 1.

- [ ] **Step 3: Lint the SQL syntactically without applying it**

Run: `docker compose exec -T db psql -U postgres -d postgres -c '\echo SYNTAX_CHECK_ONLY' < /dev/null && echo OK`
Expected: `SYNTAX_CHECK_ONLY` then `OK`. (This just verifies psql is reachable; the actual SQL is run by `make migrate` in the next task, which wraps it in a transaction so a syntax error rolls back cleanly.)

---

# Task 3: Apply the migration

**Files:**
- Modify: `public._migrations` (DB row inserted by `migrate.sh`)
- Modify: `app_mcontrol.servers` (table created)

- [ ] **Step 1: Apply the migration**

Run: `make migrate`
Expected output ends with something like:

```
APPLY  <TS>_create_app_mcontrol.sql ...
ok
1 applied, 0 skipped
```

If `migrate.sh` reports `ERROR`, the SQL ran inside a transaction that rolled back — read the error, fix the migration **only if it has not been recorded in `public._migrations`** (it won't be, because `migrate.sh` only inserts after a successful transaction), and re-run `make migrate`. Once `public._migrations` records a row for this filename, the file is immutable — you'd have to write a new migration with a later timestamp instead.

- [ ] **Step 2: Confirm the migration was recorded**

Run: `docker compose exec -T db psql -U postgres -d postgres -c "select filename, sha256, applied_at from public._migrations where filename = '<TS>_create_app_mcontrol.sql'"`
Expected: exactly one row with the matching filename and a recent `applied_at`.

---

# Task 4: Verify the schema is correct in Postgres

**Files:** none (read-only verification queries)

- [ ] **Step 1: List schemas**

Run: `docker compose exec -T db psql -U postgres -d postgres -c '\dn'`
Expected: the listing includes `app_mcontrol`.

- [ ] **Step 2: Describe the table**

Run: `docker compose exec -T db psql -U postgres -d postgres -c '\d app_mcontrol.servers'`
Expected: columns `id`, `name`, `dir`, `image_base`, `state`, `variables`, `rcon_password`, `created_at`, `updated_at`. `id` is `uuid` with default `gen_random_uuid()`. `name` is `text NOT NULL` with a unique constraint. `state` defaults to `'unknown'`. `variables` is `jsonb NOT NULL DEFAULT '{}'::jsonb`. RLS is shown as enabled (look for "Has OIDs: no" / "RLS: yes" or run the explicit check below).

- [ ] **Step 3: Verify RLS is enabled and there are zero policies**

Run: `docker compose exec -T db psql -U postgres -d postgres -c "select relrowsecurity from pg_class where oid = 'app_mcontrol.servers'::regclass"`
Expected: single row with `t` (true).

Run: `docker compose exec -T db psql -U postgres -d postgres -c "select count(*) from pg_policies where schemaname = 'app_mcontrol' and tablename = 'servers'"`
Expected: single row with `0`.

- [ ] **Step 4: Verify the trigger exists**

Run: `docker compose exec -T db psql -U postgres -d postgres -c "select tgname from pg_trigger where tgrelid = 'app_mcontrol.servers'::regclass and not tgisinternal"`
Expected: `servers_touch_updated_at`.

- [ ] **Step 5: Smoke-test insert + update from psql (as the postgres superuser)**

Run:

```bash
docker compose exec -T db psql -U postgres -d postgres <<'SQL'
insert into app_mcontrol.servers (name, dir) values ('plan-smoke-test', '/tmp/plan-smoke-test');
select name, state, variables, created_at, updated_at from app_mcontrol.servers where name = 'plan-smoke-test';
update app_mcontrol.servers set state = 'running' where name = 'plan-smoke-test';
select name, state, created_at = updated_at as ts_unchanged from app_mcontrol.servers where name = 'plan-smoke-test';
delete from app_mcontrol.servers where name = 'plan-smoke-test';
SQL
```

Expected:
- The first `select` shows `name=plan-smoke-test`, `state=unknown`, `variables={}`, and `created_at == updated_at`.
- The second `select` shows `state=running` and `ts_unchanged=f` (false), proving the trigger fired.
- The `delete` reports `DELETE 1`.

If `ts_unchanged` is `t`, the trigger is broken — investigate before continuing.

---

# Task 5: Expose `app_mcontrol` via PostgREST

**Files:**
- Modify: `bserver:~/repos/supabase-server/docker-compose.yml` (the `postgrest` service's `PGRST_DB_SCHEMAS` env var)

- [ ] **Step 1: Inspect the current value**

Run: `grep -n PGRST_DB_SCHEMAS docker-compose.yml`
Expected: a single line such as `      PGRST_DB_SCHEMAS: public,storage,graphql_public`. Note the exact spacing/indentation; the next step preserves it.

- [ ] **Step 2: Append `app_mcontrol` to the schema list**

Edit `docker-compose.yml`, changing:

```yaml
      PGRST_DB_SCHEMAS: public,storage,graphql_public
```

to:

```yaml
      PGRST_DB_SCHEMAS: public,storage,graphql_public,app_mcontrol
```

Use `sed -i` for an idempotent in-place edit (safe to re-run):

```bash
sed -i 's/^\(      PGRST_DB_SCHEMAS: public,storage,graphql_public\)$/\1,app_mcontrol/' docker-compose.yml
```

Re-run the `grep` from step 1 to confirm the line now reads `public,storage,graphql_public,app_mcontrol`.

- [ ] **Step 3: Restart only PostgREST**

Run: `docker compose up -d postgrest`
Expected: `Container supabase-rest  Started` (or `Restarted`). No other service should restart.

- [ ] **Step 4: Confirm PostgREST sees the schema**

Run:

```bash
SR_KEY=$(grep '^SERVICE_ROLE_KEY=' .env | cut -d= -f2-)
curl -fsS -H "apikey: $SR_KEY" -H "Authorization: Bearer $SR_KEY" -H "Accept-Profile: app_mcontrol" 'https://api.noelkleen.com/rest/v1/servers?select=*&limit=1'
```

Expected: `[]` (empty JSON array — table exists, no rows).

If the response is `{"code":"PGRST106","message":"The schema must be one of the following: public, storage, graphql_public"}` or similar, PostgREST didn't pick up the env-var change — re-check the docker-compose edit and re-run step 3.

- [ ] **Step 5: Confirm anon does NOT see the schema**

Run:

```bash
ANON_KEY=$(grep '^ANON_KEY=' .env | cut -d= -f2-)
curl -sS -o /dev/null -w '%{http_code}\n' -H "apikey: $ANON_KEY" -H "Authorization: Bearer $ANON_KEY" -H "Accept-Profile: app_mcontrol" 'https://api.noelkleen.com/rest/v1/servers?select=*&limit=1'
```

Expected: `200` with body `[]` is acceptable (RLS returns zero rows). A 401/403 is also acceptable. The key thing is **no rows leak** — never a populated array. (Currently the table is empty, so this is also a pre-population check; re-run after slice 3 lands and rows exist to confirm anon still gets `[]`.)

---

# Task 6: Commit and push the supabase-server changes

**Files:** all of the above, in the `supabase-server` repo only.

- [ ] **Step 1: Review the diff**

Run: `git status && git diff -- docker-compose.yml`
Expected: one new file (`supabase/migrations/<TS>_create_app_mcontrol.sql`) and one modified line in `docker-compose.yml`.

- [ ] **Step 2: Stage and commit**

Run:

```bash
git add supabase/migrations/<TS>_create_app_mcontrol.sql docker-compose.yml
git commit -m "feat(app_mcontrol): create schema + servers table; expose via PostgREST

For mcontrol slice 2. Decisions: 007, 010, 011, 013, 015.

Schema and table:
- app_mcontrol.servers — one row per Minecraft server, with dir,
  state, variables JSONB (decision 013 schema), and RCON password
  (decision 010).
- RLS enabled with no policies — service_role bypasses, anon and
  authenticated get nothing (decision 011, tailnet-only deploy).
- Trigger keeps updated_at fresh on every row update.

PostgREST:
- Added app_mcontrol to PGRST_DB_SCHEMAS so the supabase-py SDK
  can target it as schema('app_mcontrol').table('servers').

Applied via make migrate; postgrest restarted in place.
"
```

Expected: a single commit summary line and a clean exit.

- [ ] **Step 3: Push to origin**

Run: `git push origin main`
Expected: a fast-forward push. If there is an unexpected divergence, stop and reconcile with the operator — `migrate.sh` has already recorded the migration locally on bserver, so pushing must succeed eventually for any other clone of `supabase-server` to apply the same SQL.

---

## Self-review

**Spec coverage:** decisions 007, 010, 011, 013, 015 are all enacted by this slice (schema name, RCON column, RLS posture, JSONB column for variables, migration location). The decisions deferred to later slices (002, 003 are infra; 008 is filesystem; 009 / 012 / 014 / 016 / 017 / 018 belong to slices 3+) are not regressed.

**Karpathy guidelines:** the migration declares only the columns slices 3–7 will demonstrably use. No speculative tables (no `players`, no `events_log`, no `audit`); decision 018 explicitly says no DB-mirrored player list, and 011 says no audit identity. The trigger is the simplest possible `before update` function (no `if old IS DISTINCT FROM new` short-circuit — irrelevant for our throughput and the cost of being clever exceeds the cost of one extra `now()`). RLS is enabled but empty rather than disabled, because `service_role` already bypasses RLS — keeping RLS on costs nothing and matches the supabase-server convention so a future change of plan (introduce GoTrue per decision 011's escape clause) doesn't need to revisit every table.

**Verifiable success criteria:**
- `\d app_mcontrol.servers` shows the listed columns.
- Insert + update + delete from psql succeed; `updated_at` advances on update.
- `curl ... -H "Accept-Profile: app_mcontrol" /rest/v1/servers` with the service-role key returns `[]`.
- `public._migrations` contains a row for the migration filename.

**Placeholder scan:** `<TS>` is the only stand-in and it is explicitly defined in Task 1 step 1 as the output of `date +%Y%m%d%H%M%S` on bserver. No "TBD" / "implement later" / "similar to" elsewhere.

**Type consistency:** column names used here (`name`, `dir`, `state`, `variables`, `rcon_password`) match exactly what slice 3's plan consumes via the supabase-py SDK.
