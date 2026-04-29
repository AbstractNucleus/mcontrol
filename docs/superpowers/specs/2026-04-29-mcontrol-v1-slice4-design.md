# mcontrol v1 — Slice 4 Design: Lifecycle + Log SSE + RCON Console

**Status:** Approved · 2026-04-29
**Predecessor:** Slice 3 (server discovery + read-only list) — landed at `2d899ef`
**Successor plan:** `docs/plans/2026-04-29-mcontrol-v1-slice4-lifecycle-logs-rcon.md` (to be written next via `superpowers:writing-plans`)

## Goal

Make `/servers/{name}` actually controllable: HTMX-driven Start / Stop / Restart, an SSE-streamed `docker logs` pane, and an RCON console (SSE for output + POST for command submission). Add a small "Bindings" affordance so the operator can repoint a row's docker container name and on-disk directory without re-running discovery.

This slice closes the gap between "I can see the five servers" (slice 3) and "I can actually run them from the panel."

## Decisions register references

This slice acts on:

- **006** Direct `/var/run/docker.sock` mount — widens to `:rw` so we can `start`/`stop`/`restart`/`exec`/`network connect`.
- **008** Bind mounts at `~abstract/servers/minecraft/<name>/` — widens `SERVER_BASE_PATH` to `:rw` so we can write `<dir>/.env`.
- **010** RCON secrets in DB; mcontrol writes `.env` — first slice to actually act on this. Lazy generation on first Start/Restart.
- **011** `SERVICE_ROLE_KEY` server-side; no app-level user — unchanged.
- **013** Bespoke variable schema in `servers.variables` JSONB — unchanged this slice.
- **016** Backend stack: FastAPI + Jinja + HTMX — HTMX gets its first real workout here.
- **020** Pin Docker image references — applies to the Docker CLI we're adding to the mcontrol image.

This slice introduces a new entry:

- **021** Per-server `container_name` override + discovery preserves operator edits — codifies the binding-override contract so future slices can't accidentally clobber operator-edited fields.

Deferred to later slices: 012, 014, 015, 017, 018.

## Open questions resolved during brainstorming

| Question | Decision | Rationale |
|---|---|---|
| RCON client: `mcrcon` package vs bespoke async | Bespoke async (~80 LOC in `rcon.py`) | Tiny protocol, async-native fits SSE without `asyncio.to_thread`, no dep |
| RCON connectivity from the panel container | Attach mcontrol to the MC's docker network on demand | Per-server compose files stay untouched. MC's RCON binds `0.0.0.0` by default, so it's reachable across the docker bridge once attached |
| RCON network-attach lifetime | Hold attachment for the lifetime of the SSE console stream; detach on disconnect | Console is rarely opened then closed; per-call attach/detach buys nothing visible |
| Lifecycle action UX | Blocking POST → returns the new state pill via HTMX swap | `docker stop`'s 10s grace is acceptable; SSE state subscription is more wire than benefit |
| "Recreate" path (when `.env` changed) | Shell out to `docker compose -f <dir>/docker-compose.yml up -d --force-recreate` | Compose file is the source of truth for container shape; reimplementing in aiodocker means parsing compose. Costs ~50 MB image bloat for the Docker CLI + compose plugin |
| Stop / restart-of-existing | aiodocker (`container.stop()`, `.restart()`) | No env or image change; cheaper path |
| Log SSE backlog | `docker logs --tail 200 --follow` | Enough to see the latest startup banner without flooding the pane |
| RCON password generation | Lazy on first Start/Restart that needs it | No "rotate" button this slice — YAGNI |
| Mount changes | `SERVER_BASE_PATH` `:ro`→`:rw`, `/var/run/docker.sock` `:ro`→`:rw` | Per the slice-1 stub for slice 4 |
| Bindings UI scope | Ship the inline edit affordance this slice (Option α) | Operator's safety valve against drift; ~30 lines of HTMX |

## Architecture

### Module layout

```
src/mcontrol/
  templates.py            NEW   — single Jinja2Templates(...) instance attached to app.state.templates
  rcon.py                 NEW   — async RCON client (length-prefixed Source RCON protocol)
  docker_client.py        EXTEND— start/stop/restart/logs_stream/exec_stream/attach_to_network
  compose_runner.py       NEW   — thin async wrapper over `docker compose -f <dir>/docker-compose.yml up -d --force-recreate`
  env_writer.py           NEW   — write/read RCON_PASSWORD=... atomically into <dir>/.env
  passwords.py            NEW   — secrets.token_urlsafe(24) + DB persistence
  discovery.py            MODIFY— stop clobbering operator-edited dir/container_name
  db.py                   EXTEND— update_server_state, insert_server, set_rcon_password, update_bindings
  routes/
    lifecycle.py          NEW   — POST /servers/{name}/lifecycle/{start,stop,restart}
    logs.py               NEW   — GET /servers/{name}/logs (SSE)
    console.py            NEW   — GET /servers/{name}/rcon (SSE) + POST /servers/{name}/rcon
    bindings.py           NEW   — POST /servers/{name}/bindings (HTMX form submit)
    server.py             MODIFY— wire lifecycle / logs / console / bindings into the detail page
    home.py               MODIFY— consume the shared templates instance
  templates/
    server_detail.html    MODIFY— add lifecycle buttons, log pane, console pane, bindings card
    _state_pill.html      NEW   — partial returned by lifecycle POSTs
    _bindings_form.html   NEW   — partial for the bindings edit card
    _bindings_card.html   NEW   — read-only bindings display, swapped to form on Edit click
  static/
    app.css               MODIFY— layout for log/console panes, button row, bindings card (token-only, no hex)
```

### Data flow

**Lifecycle (Start example):**

```
Browser → POST /servers/atm10/lifecycle/start
  └─→ routes.lifecycle.start
        ├─ db.get_server("atm10")
        ├─ if rcon_password missing:
        │     pwd = passwords.generate()
        │     db.set_rcon_password("atm10", pwd)
        ├─ env_writer.write(<dir>/.env, RCON_PASSWORD=<pwd>)
        ├─ if .env changed: compose_runner.up_force_recreate(<dir>)
        │   else:           docker_client.start(container_name)
        ├─ db.update_server_state("atm10", "running")
        └─ return _state_pill.html partial → HTMX swaps #state-pill
```

**Log SSE:**

```
Browser → EventSource /servers/atm10/logs
  └─→ routes.logs.stream
        ├─ container = aiodocker.containers.get(container_name)
        ├─ async for line in container.log(stdout=True, stderr=True, tail=200, follow=True):
        │     yield f"data: {line}\n\n"
        └─ on disconnect: stop streaming, no lingering goroutines
```

**RCON console:**

```
Browser → EventSource /servers/atm10/rcon
  └─→ routes.console.stream
        ├─ network = docker_client.find_network(container_name)
        ├─ network.connect(self_id)              ← attach mcontrol on connect
        ├─ rcon = await rcon.connect(container_name, 25575, password)
        ├─ async for output in rcon.stream():
        │     yield f"data: {output}\n\n"
        └─ on disconnect: rcon.close(), network.disconnect(self_id)

Browser → POST /servers/atm10/rcon (body: command="say hello")
  └─→ routes.console.submit
        ├─ rcon = router-level cached connection for this server
        └─ await rcon.send(command)             ← output flows back through the SSE stream
```

### Discovery cleanup (slice-3 follow-up, folded in)

Replace the existing clobbering upsert with a "create-if-absent, otherwise refresh state only" shape so operator-edited `dir` and `container_name` survive scans:

```python
existing = db.get_server(name)
if existing:
    db.update_server_state(name, state)        # writes only `state`
else:
    db.insert_server(name=name, dir=str(entry), state=state)
```

Plus the two other slice-3 follow-ups, both touching files slice 4 already edits:

- Drop the N+1 `c.show()` in `docker_client.container_states_by_name` — `containers.list()` returns Status on each summary.
- Add a second test for the inner-branch failure: constructor succeeds, `.list()` raises.

### Schema change

Lives in `supabase-server/supabase/migrations/<timestamp>_app_mcontrol_container_name.sql` per decision 015. Slice 4 cannot deploy until this migration is applied on bserver.

```sql
alter table app_mcontrol.servers
    add column if not exists container_name text;
-- nullable; falls back to `name` when null. No backfill needed.
```

The migration is small and idempotent. It does not touch existing rows; existing reads continue to work because all consumers fall back to `name` when `container_name` is null.

### Bindings UI

```
┌─ Bindings ─────────────────────────────────────────┐
│  container name:  atm10                  [Edit]    │
│  directory:       /home/abstract/servers/...       │
└────────────────────────────────────────────────────┘
```

Click Edit → HTMX swap to the inline form:

```
┌─ Bindings ─────────────────────────────────────────┐
│  container name:  [atm10           ]                │
│  directory:       [/home/abstract/...]              │
│            [Save]   [Cancel]                        │
└────────────────────────────────────────────────────┘
```

Save POSTs to `/servers/{name}/bindings` and returns the read-only card partial. Cancel issues an HTMX request that returns the read-only card unchanged.

## Dependencies

Runtime (`pyproject.toml`):

- Existing: `fastapi`, `uvicorn[standard]`, `jinja2`, `pydantic`, `pydantic-settings`, `supabase`, `aiodocker`.
- No new Python deps. RCON is bespoke; everything else uses what's already there.

Image (`Dockerfile`):

- New: Docker CLI + the compose v2 plugin. Use the official Docker apt repository, pinned to a specific patch (e.g. `docker-ce-cli=5:27.4.0-1~debian.12~bookworm` and `docker-compose-plugin=2.31.0-1~debian.12~bookworm`) per decision 020. Pin choice is finalised in the implementation plan.

Compose (`docker-compose.yml`):

- Mount changes: `SERVER_BASE_PATH:${SERVER_BASE_PATH}:rw` and `/var/run/docker.sock:/var/run/docker.sock:rw`. Tracked compose remains the `app`-only service; bserver's gitignored override stays as-is.

## Failure modes + handling

| Failure | Behaviour | Surface to user |
|---|---|---|
| Container does not exist (binding stale) | Lifecycle POST 502s with a clear error fragment | Inline error card next to the buttons; suggests editing bindings |
| `compose up -d --force-recreate` fails (e.g. malformed compose) | Capture stderr, surface in the error fragment | Same inline error card |
| Docker socket unreachable | All lifecycle paths 503 | Banner suggesting "panel can't reach docker — check the host" |
| RCON connect fails (wrong password, port unreachable) | SSE stream emits one error event then closes | Console pane shows the error; user can retry |
| Network attach fails | RCON SSE returns 502 immediately | Console pane shows the error; offers a retry button |
| `.env` write fails (permissions / disk full) | Lifecycle POST 500s with the OSError's message | Inline error card |
| RCON password missing in DB during console open | Surface "password not yet generated — start the server first" | Console pane is disabled until the user starts the server, which generates the password |

No retries, no exponential backoff, no circuit breaker. Single-user tailnet; user-driven retry is fine.

## Testing approach

- **Unit tests for each new module.** `rcon.py` against a fake server using `asyncio.start_server`. `compose_runner.py` against a mocked `asyncio.create_subprocess_exec`. `env_writer.py` against `tmp_path`. `passwords.py` against `secrets.token_urlsafe`.
- **Route tests** mock `db`, `docker_client`, `rcon`, `compose_runner`. The slice-3 pattern of `monkeypatch.setattr(module, attr, fake)` continues to work.
- **No live-Docker tests in CI.** The Docker socket isn't available; everything goes through the wrappers.
- **One end-to-end "happy path"** that walks Start → Logs → RCON command → Stop using fakes. Catches integration regressions slice-to-slice.
- **`tests/test_no_hardcoded_styles.py` stays green.** Every new CSS rule uses `var(--*)` only.
- **Live-deploy smoke test** post-merge on bserver: open `/servers/atm10`, click Start, watch the log SSE produce the startup banner, send `say hi` over RCON, click Stop. Documented in the PR's test plan.

## Karpathy guidelines applied

- **No new Python dep for RCON.** Bespoke 80-line implementation; smaller surface than wrapping `mcrcon` in `to_thread`.
- **No "rotate password" button this slice.** Lazy generation only; rotation lands when there's a felt need.
- **No state-subscription SSE.** Blocking lifecycle POST is enough until proven slow.
- **No connection pool for RCON.** Hold the SSE-lifetime connection; nothing more.
- **No retries / backoff.** Single-user; user-driven retry is fine.
- **Bindings UI is two fields and one form**, not a settings framework.
- **Discovery cleanup is surgical** — replaces one upsert with two narrower writes; doesn't refactor discovery's structure.
- **`compose_runner` is a 30-line subprocess wrapper**, not a compose-file parser.
- **Image bloat is acknowledged**, not glossed over (~50 MB for Docker CLI + compose plugin); the alternative (parse compose ourselves) is judged worse.

## Verifiable success criteria

- `uv run pytest -v` passes locally and in CI.
- `uv run ruff check .` passes.
- `tests/test_no_hardcoded_styles.py` stays green.
- After deploy on bserver:
  - Click Start on a stopped server → state pill turns to `running` within 30 s.
  - Log pane streams the startup banner within 5 s of opening.
  - RCON console accepts `list` and returns the player count.
  - Click Stop → state pill turns to `exited` within 15 s.
  - Edit the bindings on a row → discovery's next run preserves the edit.

## Out of scope (explicitly)

- Auto-restart on crash / supervision policy (decision-territory if it ever matters).
- Bulk lifecycle ("Stop all").
- Whitelist + ops UI (slice 7).
- File browser + uploads (slice 5).
- New-server scaffolding flow (slice 6).
- itzg → temurin migration for `atm10` + `monifactory` (slice 8).
- A "rotate RCON password" button — defer until felt.
- Live-state subscription SSE — defer until blocking lifecycle is measurably slow.

## Self-review

- **Placeholders:** none. Every section is concrete; the only `<…>` substitutions are the migration timestamp and the Docker CLI pin (both finalised in the implementation plan, not now).
- **Internal consistency:** the architecture diagram, the module layout, and the data-flow sketches all use the same module names. Decision-register references match the existing register.
- **Scope:** appropriate for a single implementation plan. Lifecycle, logs, RCON, bindings, and the slice-3 follow-ups are all small and share files.
- **Ambiguity:** the only thing not nailed down is the exact Docker CLI / compose plugin patch versions; the implementation plan picks them with the rest of the dep work.
