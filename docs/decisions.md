# Decisions

Architectural and operational decisions for `mcontrol`. Each entry captures **what we decided, what we rejected, and what trade-off we're accepting**. The status table below is the index — scan it for state, then read the matching entry for substance.

## Status taxonomy

- **Accepted** — decided and acted on (or about to be).
- **Proposed** — clear leaning; will be ratified on first implementation that touches it.
- **Open** — recognised question with no current answer; entry exists so it isn't forgotten.
- **Superseded by NNN** — replaced by a later decision; the entry stays as history.

## Adding an entry

1. Pick the next free `NNN` (zero-padded, monotonic; never renumber).
2. Append a row to the status table and a section below.
3. If a new entry replaces an old one, change the old entry's status to `Superseded by NNN` rather than editing it.

## Status

| ID  | Title                                                | Status   | Date       |
| --- | ---------------------------------------------------- | -------- | ---------- |
| 001 | Base image: `eclipse-temurin:21-jre`                 | Accepted | 2026-04-26 |
| 002 | UI palette: `AbstractNucleus/design`                 | Accepted | 2026-04-26 |
| 003 | Tailnet-only access via Cloudflare DNS-01            | Accepted | 2026-04-26 |
| 004 | Thin custom panel, single-host                       | Accepted | 2026-04-26 |
| 005 | Single-host scope                                    | Accepted | 2026-04-26 |
| 006 | Direct `/var/run/docker.sock` mount                  | Accepted | 2026-04-26 |
| 007 | Shared Supabase, schema `app_mcontrol`               | Accepted | 2026-04-26 |
| 008 | Bind mounts at `~abstract/servers/minecraft/<name>/` | Accepted | 2026-04-26 |
| 009 | Single memory-budget knob; derive `-Xmx` + `mem_limit` | Accepted | 2026-04-26 |
| 010 | RCON secrets in DB; mcontrol writes `.env`           | Accepted | 2026-04-26 |
| 011 | `SERVICE_ROLE_KEY` server-side; no app-level user    | Accepted | 2026-04-26 |
| 012 | Scaffold + file/upload UI; no auto-installers        | Accepted | 2026-04-26 |
| 013 | Bespoke variable schema in `servers.variables` JSONB | Accepted | 2026-04-26 |
| 014 | Migrate `atm10` + `monifactory` to temurin           | Accepted | 2026-04-26 |
| 015 | DB migrations live in `supabase-server`, not here    | Accepted | 2026-04-26 |
| 016 | Backend stack: Python + FastAPI + Jinja + HTMX       | Accepted | 2026-04-26 |
| 017 | Backups out of scope; delegate to plugins/mods       | Accepted | 2026-04-26 |
| 018 | Whitelist + ops management                           | Accepted | 2026-04-26 |

## 001. Base image: `eclipse-temurin:21-jre`

**Status:** Accepted · 2026-04-26

All Minecraft server containers run on `eclipse-temurin:21-jre` as the base image. The custom Dockerfile pattern (`COPY entrypoint.sh; ENTRYPOINT ["/entrypoint.sh"]`) stays — `entrypoint.sh` does `cd /data && exec ./start_server.sh` and `start_server.sh` invokes `java -Xmx... -jar <loader>.jar nogui`.

Rejected: `itzg/minecraft-server`. Its env-var contract (`TYPE=`, `EULA=TRUE`, server.properties templating) is the project's primary value, but `mcontrol` is not going to drive servers through that contract — and overriding the entrypoint to run our own `start_server.sh` reduces the image to a glorified JRE base. Going to temurin removes the pretence.

Trade-off: we give up itzg's auto-install, modloader detection, and modpack `TYPE` selectors. Decision 012 (no auto-installers) accepts the consequence.

## 002. UI palette: `AbstractNucleus/design`

**Status:** Accepted · 2026-04-26

The panel UI consumes design tokens and components from [`AbstractNucleus/design`](https://github.com/AbstractNucleus/design): warm paper background, rust accent, monospaced typography throughout.

Rejected: ad-hoc styling, and adopting the visual language of any forked panel (Pterodactyl, Pelican, etc.). The palette repo is the single source of truth for tokens, type, spacing, and component styles.

Trade-off: every new component must consume the palette rather than introduce its own colours/type. Cost is discipline; benefit is that visual changes ripple from one place across `mcontrol` and any sibling tools that adopt the palette.

## 003. Tailnet-only access via Cloudflare DNS-01

**Status:** Accepted · 2026-04-26

The `mcontrol` UI is reachable only from devices on the user's Tailscale tailnet. Public DNS (Cloudflare, gray cloud) resolves the hostname to the host's `100.x.y.z` tailnet IP; off-tailnet packets cannot be routed there. Caddy on the host (or aserver nginx, depending on deployment) terminates TLS using a Let's Encrypt cert obtained via the Cloudflare DNS-01 challenge — no public ingress. See [`patterns/tailnet-https-via-cloudflare.md`](patterns/tailnet-https-via-cloudflare.md) for the canonical setup.

Rejected: public ingress + app-level auth, and Tailscale Funnel. Public ingress would force a real auth story before there's a need for one. Funnel exposes paths to the open internet, which defeats the point.

Trade-off: anyone who needs access has to be invited to the tailnet. That's the desired posture for a single-user / small-trusted-group panel; it would be the wrong call if `mcontrol` ever needs to onboard untrusted users.

## 004. Thin custom panel, single-host

**Status:** Accepted · 2026-04-26

`mcontrol` is a bespoke web app that talks directly to the local Docker socket on the host where the Minecraft servers run. It is not a fork of Pterodactyl, Pelican, or any other panel; it does not embed Wings or a Periphery agent; there is no remote-agent protocol.

Rejected: forking Pterodactyl/Pelican (path 1 in the research; gets features for free but inherits a fork-maintainer burden), shipping eggs into an existing panel (path 2; locks UX into someone else's UI), integrating against Portainer as a backend (path 3; loses MC semantics), Dockge/MCSManager plugins (path 4; the surfaces don't exist or are insufficient). See [`../research/2026-04-26-minecraft-and-docker-control-panels/`](../research/2026-04-26-minecraft-and-docker-control-panels/README.md) for the full landscape.

Trade-off: we own the UI, the ops loop, and any feature parity with richer panels. We get scope-fit (single host, ~6 servers, MC-only) and zero upstream-fork risk.

## 005. Single-host scope

**Status:** Accepted · 2026-04-26

`mcontrol` targets a single host. No multi-node, no agent-on-other-hosts, no remote daemon protocol.

Rejected: a Wings/Periphery-style panel + remote agent split. Useful at scale, unjustified at one box. Operator has explicitly stated no plans to run Minecraft servers on a second host.

Trade-off: if Minecraft servers ever do live on a second host, `mcontrol` will need a real architectural revisit (a new decision that supersedes this one) rather than an incremental extension. Accepted as a future-`mcontrol` problem; today's value comes from being uncomplicated.

## 006. Direct `/var/run/docker.sock` mount

**Status:** Accepted · 2026-04-26

The panel container mounts `/var/run/docker.sock` directly. The panel is effectively root-equivalent on the host through this socket.

Rejected: Docker socket-proxy (e.g. `tecnativa/docker-socket-proxy`), Docker daemon over TCP+TLS, rootless Docker. The threat the proxy mitigates is **inbound** compromise of the panel — and tailnet-only access (decision 003) already kills that path. The threat the proxy still catches is a compromised dependency executing malicious code from inside the panel; at single-user scale, with one engineer reading diffs, the residual risk is low.

Trade-off: a vulnerable dependency in the panel could do anything Docker can do. Mitigated by tailnet-only access, careful dependency hygiene, and "rebuild from backups" as the recovery path. If `mcontrol` ever takes external untrusted input that touches the socket path, revisit.

## 007. Shared Supabase, schema `app_mcontrol`

**Status:** Accepted · 2026-04-26

`mcontrol` uses the existing self-hosted Supabase on bserver (documented in `AbstractNucleus/supabase-server`). Persistent state lives in the `app_mcontrol` schema in shared Postgres. Migrations live in the `supabase-server` repo (decision 015), not in this repo. The app reaches Supabase via `https://api.noelkleen.com` and authenticates with the keys from `bserver:~/repos/supabase-server/.env`.

Rejected: SQLite (would simplify deploy but breaks symmetry with the established convention — every other app uses Supabase, so going off-pattern just for `mcontrol` adds operational drift), a fresh standalone Postgres (redundant — the shared instance already handles backups and upgrades).

Trade-off: `mcontrol` depends on Supabase being up to manage servers (read state, persist secrets). Acceptable: Supabase and `mcontrol` run on the same host, fail together, and recover together. The MC server containers themselves run independently of both — a Supabase outage doesn't kill running game servers, only the panel that controls them.

## 008. Bind mounts at `~abstract/servers/minecraft/<name>/`

**Status:** Accepted · 2026-04-26

Each server's data directory lives at `/home/abstract/servers/minecraft/<name>/server/` on the host and is bind-mounted into the container at `/data`. The base path (`/home/abstract/servers/minecraft/`) is configurable in mcontrol's settings; the per-server `<name>/server/` layout under it is fixed.

Rejected: named Docker volumes (opaque to host-side `rsync`/`borg`/`restic`, harder to inspect), system paths like `/srv/minecraft/` (operator preference is to keep MC servers under their home directory).

Trade-off: bind mounts at a user-home path couple to the `abstract` user account on this host. Acceptable because decision 005 commits to single-host. UID/GID alignment between container and host has to stay disciplined; misaligned ownership is the recurring failure mode.

## 009. Single memory-budget knob; derive `-Xmx` and `mem_limit`

**Status:** Accepted · 2026-04-26

Each server has a single "memory budget" setting in `mcontrol`'s UI (e.g. "12 GB"). `mcontrol` writes both `mem_limit: 12g` to the compose file and `-Xmx10g` (= budget − 2 GB headroom) to `start_server.sh`. The 2 GB default off-heap headroom covers JIT code cache, mod metadata, native libraries (Netty buffers, etc.) — typical for modpack workloads. Advanced settings expose `-Xmx` and `mem_limit` as separate overrides for edge cases.

Rejected: two independent knobs as the default UX (operator has to think about two numbers and keep them aligned), JVM-only `-Xmx` with no `mem_limit` (the `monifactory` exit-137 OOM in the bserver inventory is exactly what this prevents).

Trade-off: hitting the cgroup limit kills the container abruptly (SIGKILL), which is still better than a noisy-neighbour blast radius across the host. Default 2 GB headroom may be too aggressive for very small servers (<4 GB total) and too tight for very heavy modpacks; the override knobs handle both edges.

## 010. RCON secrets in DB; mcontrol writes `.env`

**Status:** Accepted · 2026-04-26

Each server's RCON password is stored in `app_mcontrol.servers.rcon_password` (or a dedicated `secrets` column / table). `mcontrol` generates a random secret on server creation and on rotation. When starting or recreating a server's container, `mcontrol` writes `RCON_PASSWORD=<value>` to `/home/abstract/servers/minecraft/<name>/.env` (gitignored), which docker-compose reads. Rotation is a UI button: generate new secret → write new `.env` → `docker compose up -d --force-recreate`. RCON stays bound to loopback by default — the password is defence-in-depth.

Rejected: hardcoded passwords in compose files (current bserver pattern; credential-rotation hazard the moment any port mapping changes), per-server `.env` managed by hand (fine but doesn't leverage the panel for what it's good at), Docker secrets / external vault (overkill for single-host single-user).

Trade-off: the `.env` on disk is plaintext and root-readable. Same trust posture as decision 006 (panel is root-equivalent on host); consistent with the existing model. The DB row is the source of truth; the on-disk `.env` is a derived artifact mcontrol manages.

The same pattern extends to other per-server secrets (backup-destination credentials, Modrinth/CurseForge API keys, etc.) when they appear.

## 011. `SERVICE_ROLE_KEY` server-side; no app-level user concept

**Status:** Accepted · 2026-04-26

`mcontrol` embeds Supabase's `SERVICE_ROLE_KEY` server-side and bypasses RLS. There is no login screen, no user table, no `auth.uid()` in policies. The operator-on-tailnet is the user; their identity is implicit. The Supabase `client-integration.md` doc explicitly sanctions this for tailnet-only internal tools.

Rejected: GoTrue email/password login with the shared user pool (would give a real `User` model and audit identity for free, but adds a login screen for a single-user tool where decision 003 already gates access at the network layer), Tailscale identity-aware proxy (cleaner UX but requires non-trivial nginx work and you still need `SERVICE_ROLE_KEY` underneath).

Trade-off: no audit log of "who did what" — every action is implicitly the operator. If a second user ever joins (give a friend read-only access, audit trail becomes useful), this decision needs to be superseded; the migration is "introduce GoTrue login + a `users` table + audit columns," which is a real piece of work but not architecturally surprising.

Network-layer compromises (a tailnet device gets compromised) bypass this entirely — there's no password gate. Accepted because the alternative (a password gate on a single-user panel) is friction without proportional benefit at this scale.

## 012. Scaffold + file/upload UI; no auto-installers

**Status:** Accepted · 2026-04-26

`mcontrol` creates new servers by scaffolding a directory + container shell, then exposing a file-management UI that lets the operator bring their own jars and mods. No automated Forge/NeoForge installers, no Modrinth `.mrpack` parser, no loader version resolution.

The new-server flow:
1. Operator picks name + memory budget.
2. `mcontrol` creates `/home/abstract/servers/minecraft/<name>/` with `server/` subdir.
3. `mcontrol` generates `docker-compose.yml`, `Dockerfile` (FROM `eclipse-temurin:21-jre`), `entrypoint.sh`, `start_server.sh` from templates, parameterised by the variables in decision 013.
4. `mcontrol` registers the new row in `app_mcontrol.servers`.

The runtime UI then provides:
- File browser with in-browser editor (server.properties, configs, scripts).
- Single-file upload → `server/` (server jar lands here; `start_server.sh` references it by filename).
- Multi-file upload → `server/mods/` (mods go here).
- Start / Stop / Restart controls.
- RCON-backed console.
- Live log stream.

Rejected: built-in installers for Vanilla/Paper/Fabric/Forge/NeoForge/Modrinth (genuine ongoing maintenance burden; loader installer logic is messy and changes upstream; not the v1 problem to solve), pluggable shell-script installers (closer to building Pterodactyl-lite — over-engineering for ~6 servers), manual import only (loses the "create new server" flow that existing dashboards already provide).

Trade-off: operator has to do the loader install themselves, externally. For someone comfortable running a Forge installer locally and dropping the result in, this is fine; for a non-technical user it would be too much friction (but `mcontrol` is not for non-technical users). If/when the operator wants a loader wizard, it becomes a v2 decision informed by real usage.

## 013. Bespoke variable schema in `servers.variables` JSONB

**Status:** Accepted · 2026-04-26

Per-server runtime variables live in `app_mcontrol.servers.variables` as a JSONB column. Schema is bespoke and small — only the knobs the UI actually surfaces:

- `memory_budget_gb` — single integer (drives both `-Xmx` and `mem_limit` per decision 009).
- `motd` — server message-of-the-day.
- `port` — host-side TCP port for the Minecraft server (default 25565, must be unique across servers).
- `server_jar` — filename in `server/` to launch (e.g. `paper-1.21.4.jar`, `fabric-server-mc.1.20.1-loader.0.16.5-launcher.1.0.1.jar`).
- `jvm_extra_args` — string, additional JVM flags appended to `java -Xmx... -jar` (e.g. Aikar's flags).
- `rcon_enabled` — bool; `mcontrol` always sets RCON for its own use, so this is effectively read-only-true today, but the field exists for forward flexibility.

Rejected: borrowing the Pterodactyl egg JSON shape (forward-portable, but there's no installer system that would consume the egg-side metadata — decision 012 explicitly skips that), generic-key-value with no schema (unsearchable, undocumented, easy to mistype).

Trade-off: a new variable means a schema change (Postgres migration in `supabase-server`, UI change here, generator-template change). Cost is acceptable given how rarely the variable set should change; adding three runtime knobs in the next year would be a lot.

## 014. Migrate `atm10` + `monifactory` to temurin

**Status:** Accepted · 2026-04-26

When `mcontrol` v1 runs its first import pass, it rewrites the `Dockerfile` of any server whose base image is not `eclipse-temurin:21-jre` (today: `atm10`, `monifactory`) to use temurin, then rebuilds the image. World data is not touched — it lives in the bind-mounted `server/` directory (decision 008) and is independent of the container image.

`kobra_kollektivet` is **not** affected: it is already on `eclipse-temurin:21-jre` per the bserver inventory, so the import pass leaves it alone. Even if it weren't already on temurin, the migration only swaps the base image — the bind-mounted world data would still be untouched.

Rejected: lazy migration (convert when someone clicks "start" — leaves an inconsistent fleet), keep both bases supported (carries "weird path for legacy itzg servers" complexity into v1 for no benefit), don't migrate (perpetuates the entrypoint-overriding pattern that decision 001 explicitly rejected).

Trade-off: rebuilding `atm10` and `monifactory` images takes a few minutes each. Both are non-running today (`atm10` never started, `monifactory` exited 137 OOM), so there is no live state to be careful with.

## 015. DB migrations live in `supabase-server`, not here

**Status:** Accepted · 2026-04-26

All `CREATE SCHEMA`, `CREATE TABLE`, `ALTER TABLE`, RLS policies, and grants for `app_mcontrol` live in `bserver:~/repos/supabase-server/supabase/migrations/<timestamp>_<name>.sql`. They are applied via `make migrate` on bserver, ahead of any `mcontrol` deploy that depends on them. No `CREATE TABLE` in this repo; no migration step in `mcontrol`'s container start-up or CI pipeline.

This is a convention inherited from the Supabase setup (see `AbstractNucleus/supabase-server/docs/client-integration.md`); recording it here so future-`mcontrol` doesn't accidentally violate it.

Rejected: in-app migrations (each app managing its own schema), Alembic/Prisma/etc.-style migration framework inside `mcontrol`. Both fragment the source of truth and break the "one migration history, applied in order" invariant the shared Supabase relies on.

Trade-off: schema changes require an SSH to bserver to add a migration file and run `make migrate`, separate from a code deploy. Friction is real but small and intentional — it forces schema decisions to be deliberate and reviewed against existing tables.

## 016. Backend stack: Python + FastAPI + Jinja + HTMX

**Status:** Accepted · 2026-04-26

`mcontrol`'s backend is FastAPI (Python), serving Jinja-rendered HTML enhanced with HTMX for partial swaps and form interactions. Live streams (log tail, RCON console output) are Server-Sent Events consumed via HTMX's `hx-sse` extension. The frontend consumes `tokens.css` from `AbstractNucleus/design` via a `<link>` tag — no JS framework, no bundler step. In-browser code editing for `server.properties` / config files uses Monaco or CodeMirror loaded via CDN as a single component.

Anticipated dependencies (subject to refinement during writing-plans):
- `fastapi`, `uvicorn[standard]` — web framework + ASGI server.
- `jinja2` — server-rendered templates.
- `aiodocker` — async Docker socket client.
- `supabase` — Supabase Python SDK, configured with `SERVICE_ROLE_KEY` per decision 011.
- An async RCON client (`mcrcon`, or a small bespoke `asyncio` implementation against [the protocol](https://wiki.vg/RCON)).
- HTMX (CDN or vendored) + the SSE extension.

Rejected: **TypeScript + SvelteKit** (genuinely better technical fit for highly-reactive UIs, but mcontrol's surface is mostly forms + append-only streams that HTMX handles cleanly; the context-switch cost from `admin_management`'s Python stack outweighs the wins for this app's shape). Rejected: **Next.js** (same reasoning as SvelteKit, plus WebSocket awkwardness on top). Rejected: **Phoenix LiveView** (best technical fit for "everything is live," but the Elixir ramp is unjustified at this scale). Rejected: **Go + HTMX + templ** (single-binary deploy is appealing, but Python's ecosystem alignment with `admin_management` wins).

Trade-off: shared mental model with `admin_management` is the main win; the cost is no end-to-end type safety the way SvelteKit + TypeScript would give. Pydantic + careful API contract design covers most of the gap within Python; the rest is discipline.

Implementation discipline: when moving from this decisions register to writing-plans / code, follow `/karpathy-guidelines` — surgical changes, surface assumptions, define verifiable success criteria, avoid overcomplication.

## 017. Backups out of scope; delegate to plugins/mods

**Status:** Accepted · 2026-04-26

`mcontrol` does not provide first-party backup or restore functionality. Backups are the operator's responsibility, handled by per-server backup mods and plugins — FTB Backups for Forge/NeoForge modpacks, AromaBackup, ServerUtilities, Spigot/Paper backup plugins, etc. These tools understand their host server's internals (chunk-save coordination, mod-state files, packed/unpacked save formats) far better than a generic panel-driven `borg` ever could, and they've been battle-tested per-loader for years.

In practice:
- New server: operator drops the appropriate backup mod/plugin into `mods/` or `plugins/` and configures it through its own config file — both editable via mcontrol's file UI per decision 012.
- Backups land in the mod's configured directory (typically `server/backups/`), inside the bind-mounted `server/` dir and visible in mcontrol's file browser.
- Restore: operator stops the server in mcontrol, swaps files via the file browser (or shell), starts the server.

Rejected: mcontrol-driven `borg` with "Backup now" / "Restore" buttons (the UX would be nicer, but the value-add over a per-server backup mod is small, and the RCON-flush dance — `save-all flush; save-off; ...; save-on` — is something each backup mod handles correctly for its loader). Rejected: host-side cron + `borg` as the canonical answer (works fine if the operator wants it, but it isn't `mcontrol`'s concern).

Trade-off: no panel-level "Backup now / Restore" affordance. If that ever becomes a felt need, a future decision can supersede this — most likely framed as a thin orchestrator over the chosen mod's commands rather than a parallel backup system. The bind-mount layout (decision 008) leaves host-side `borg`/`restic` available for operators who want belt-and-suspenders disaster recovery on top of in-server backups.

## 018. Whitelist + ops management

**Status:** Accepted · 2026-04-26

`mcontrol` exposes whitelist and operator (op) management as first-class per-server UI features:

- **Whitelist UI** — list whitelisted players, add/remove, toggle enforcement (`white-list` in `server.properties`).
- **Ops UI** — list operators with their op level (1–4) and `bypassesPlayerLimit` flag, add/remove, change level.

The server's `whitelist.json` and `ops.json` (in the bind-mounted `server/` directory) are the on-disk source of truth. `mcontrol` reads them to render UI state and writes through three mechanics, picked by context:

1. **RCON when the server is running** — `mcontrol` sends `whitelist add <name>`, `whitelist remove <name>`, `whitelist on/off`, `op <name>`, `deop <name>` via the existing RCON connection. Changes apply live, no restart needed.
2. **Direct file edit when the server is offline** — `mcontrol` edits `whitelist.json` / `ops.json` on disk; change takes effect on next start. UI clearly surfaces this state ("Server is offline — change will apply on next start").
3. **Direct file edit + `whitelist reload` for granular op levels** — vanilla `/op` always assigns level 4. To set level 1–3, `mcontrol` edits `ops.json` directly and triggers the server to re-read (`whitelist reload` over RCON, or restart). UI surfaces level as a dropdown.

No mirror table in `app_mcontrol.players` for v1. Rejected: DB-mirrored player lists with cross-server propagation ("add Alice to all my servers' whitelists" as a single click — defer until that's a felt pain). Rejected: pure-RCON without file-edit fallback (locks all whitelist/ops changes behind a running server, which is the wrong UX when the server is being prepared offline).

Trade-off: split-mechanic (RCON when running, file edits when offline, file-edits + reload for op levels) is more code than picking one path, but it's the right behaviour for all three states. The complexity lives in one well-bounded module (`whitelist_ops` / `permissions`) rather than leaking across the panel.
