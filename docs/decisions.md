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
| 001 | Base image: `eclipse-temurin:21-jre`                 | Superseded by 023 | 2026-04-26 |
| 002 | UI palette: `AbstractNucleus/design`                 | Accepted | 2026-04-26 |
| 003 | Tailnet-only access via Cloudflare DNS-01            | Accepted | 2026-04-26 |
| 004 | Thin custom panel, single-host                       | Accepted | 2026-04-26 |
| 005 | Single-host scope                                    | Accepted | 2026-04-26 |
| 006 | Direct `/var/run/docker.sock` mount                  | Accepted | 2026-04-26 |
| 007 | Shared Supabase, schema `app_mcontrol`               | Accepted | 2026-04-26 |
| 008 | Bind mounts at `~abstract/servers/minecraft/<name>/` | Accepted | 2026-04-26 |
| 009 | Single memory-budget knob; derive `-Xmx` + `mem_limit` | Accepted | 2026-04-26 |
| 010 | RCON secrets in DB; mcontrol writes `.env`           | Superseded by 024 | 2026-04-26 |
| 011 | `SERVICE_ROLE_KEY` server-side; no app-level user    | Accepted | 2026-04-26 |
| 012 | Scaffold + file/upload UI; no auto-installers        | Accepted | 2026-04-26 |
| 013 | Bespoke variable schema in `servers.variables` JSONB | Accepted | 2026-04-26 |
| 014 | Migrate `atm10` + `monifactory` to temurin           | Accepted | 2026-04-26 |
| 015 | DB migrations live in `supabase-server`, not here    | Accepted | 2026-04-26 |
| 016 | Backend stack: Python + FastAPI + Jinja + HTMX       | Accepted | 2026-04-26 |
| 017 | Backups out of scope; delegate to plugins/mods       | Accepted | 2026-04-26 |
| 018 | Whitelist + ops management                           | Superseded by 027 | 2026-04-26 |
| 019 | TLS termination at aserver-nginx, not in-repo Caddy  | Accepted | 2026-04-27 |
| 020 | Pin Docker image references; no floating tags        | Accepted | 2026-04-27 |
| 021 | Per-server `container_name` override + discovery preserves operator edits | Accepted | 2026-04-29 |
| 022 | Panel host-bind in base compose, parameterised       | Accepted | 2026-05-02 |
| 023 | No-Dockerfile scaffold model                         | Accepted | 2026-05-05 |
| 024 | RCON password operator-managed in `server.properties` | Accepted | 2026-05-05 |
| 025 | Regenerate clobbers against the confirmed diff; mtime drift aborts | Accepted | 2026-05-05 |
| 026 | Delete tombstones; discovery skips `.`-prefixed dirs | Accepted | 2026-05-05 |
| 027 | DB-backed player roster; disk-only per-server membership | Accepted | 2026-05-08 |
| 028 | One-shot legacy-to-scaffold migration; no dual-shape framework | Accepted | 2026-05-09 |
| 029 | Drop dormant `rcon_password` + `image_base` columns          | Accepted | 2026-05-10 |
| 030 | Deep `/healthz`: per-subsystem probe with 503-on-degraded    | Accepted | 2026-05-10 |
| 031 | Empty-trash affordance: tombstone purge with 7-day default   | Accepted | 2026-05-10 |
| 032 | Claude-flavoured theme; semantic tokens; tri-state dark/light | Accepted | 2026-05-10 |
| 033 | Lifecycle buttons: state-aware disable + accent on next-action  | Accepted | 2026-05-11 |

## 001. Base image: `eclipse-temurin:21-jre`

**Status:** Superseded by 023 · 2026-04-26

All Minecraft server containers run on `eclipse-temurin:21-jre` as the base image. The custom Dockerfile pattern (`COPY entrypoint.sh; ENTRYPOINT ["/entrypoint.sh"]`) stays — `entrypoint.sh` does `cd /data && exec ./start_server.sh` and `start_server.sh` invokes `java -Xmx... -jar <loader>.jar nogui`.

Rejected: `itzg/minecraft-server`. Its env-var contract (`TYPE=`, `EULA=TRUE`, server.properties templating) is the project's primary value, but `mcontrol` is not going to drive servers through that contract — and overriding the entrypoint to run our own `start_server.sh` reduces the image to a glorified JRE base. Going to temurin removes the pretence.

Trade-off: we give up itzg's auto-install, modloader detection, and modpack `TYPE` selectors. Decision 012 (no auto-installers) accepts the consequence.

## 002. UI palette: `AbstractNucleus/design`

**Status:** Superseded by 032 · 2026-04-26

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

**Status:** Superseded by 024 · 2026-04-26

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

## 019. TLS termination at aserver-nginx, not in-repo Caddy

**Status:** Accepted · 2026-04-27

Production `mcontrol` is fronted by aserver's nginx (`/etc/nginx/sites-available/mcontrol.conf`), which terminates TLS using a Let's Encrypt cert renewed via certbot's Cloudflare DNS-01 plugin and reverse-proxies over the tailnet to bserver's LAN-bound app port. The tracked `docker-compose.yml` runs only the `app` service; the per-host LAN bind (`<bserver-lan-ip>:<port>:8000`) lives in bserver's gitignored `docker-compose.override.yml`. The in-repo Caddy service and `Caddyfile` are removed; the bundled-Caddy pattern was a slice-1 expedient that didn't match how the panel actually deploys.

This decision pins down the "or aserver nginx, depending on deployment" hedge in decision 003. The tailnet posture from 003 is preserved verbatim — gray-cloud Cloudflare DNS to bserver's tailnet IP, no public ingress, DNS-01 cert. Only the terminator changes: nginx instead of Caddy.

Rejected:
- **Replace Caddy with an nginx service inside the repo's compose.** Self-contained, but duplicates the work aserver-nginx already does, and certbot DNS-01 inside a per-app container is more setup than terminating once at the edge for the whole fleet.
- **Keep Caddy alongside aserver-nginx.** Two TLS terminators in series is a footgun; the inner one's cert dance becomes either redundant or actively harmful (which IP does the cert advertise — the bserver tailnet IP, or aserver's?). Pick one terminator per hostname.
- **Funnel-style public access in lieu of nginx-on-aserver.** Public ingress conflicts with decision 003's tailnet-only posture.

Trade-off: a fresh clone of this repo cannot bring up a TLS-fronted instance with `docker compose up -d` alone — the operator either runs it behind their own existing terminator (nginx, Caddy, traefik, whatever they already have) or accepts plain HTTP on a LAN port for local use. The conceptual pattern in `docs/patterns/tailnet-https-via-cloudflare.md` still applies; only the terminator and DNS-01 client differ from the doc's Caddy-flavoured examples.

Operationally: when slice 1's Caddyfile was authored, aserver-nginx was already terminating `mcontrol.noelkleen.com` via certbot — the in-repo Caddy was never the runtime path. This entry just records reality.

## 020. Pin Docker image references; no floating tags

**Status:** Accepted · 2026-04-27

Every Docker image reference in this repo (Dockerfile `FROM`/`COPY --from=`, compose `image:`, future Bake or Compose-build args) is pinned to a specific patch-level tag (e.g. `python:3.12-slim`, `ghcr.io/astral-sh/uv:0.11.7`). Floating tags — `latest`, `:0.5`, `:3.12` without `-slim`/distro suffix, `:edge` — are not used. Bumps are deliberate, single-line PRs that name what changed.

Rationale: a floating tag drifts under a stable branch — a rebuild months later picks up upstream's latest, which can introduce regressions invisible in the diff. Pinning makes the image a function of the SHA, and a build always reproduces. This decision is the policy; the implementation is to apply pins immediately and not leave a "we'll pin it later" backlog.

Slice-1 originally pulled `ghcr.io/astral-sh/uv:0.5` (channel pointer) and `slothcroissant/caddy-cloudflaredns:latest`. Both floated. The Caddy reference is removed entirely by decision 019; the `uv` reference is bumped to `ghcr.io/astral-sh/uv:0.11.7` which matches the dev environment and the latest stable as of this entry.

Rejected:
- **Pin to channel tags only (`:0.11`).** Less precise than a patch pin and still floats within the channel — a 0.11.x release can break things between rebuilds.
- **Pin to image digests (`@sha256:...`).** Maximally reproducible but visually opaque and painful to bump manually. The patch-level tag is the pragmatic middle: deterministic in normal use, with an audit trail (the version string is human-readable and matches upstream release notes).
- **Allow `:latest` for rapid-iteration projects.** mcontrol is single-host long-running, not a fast-cycle service — the cost of a silent regression outweighs the convenience of always-newest.

Trade-off: bumping image versions is now a manual chore. Mitigated by the fact that there are very few image references in this repo (one base image, one builder image), and Renovate / Dependabot can be turned on for automated PRs against pinned tags later if that chore becomes annoying.

## 021. Per-server `container_name` override + discovery preserves operator edits

**Status:** Accepted · 2026-04-29

`app_mcontrol.servers` gains a nullable `container_name text` column. When non-null, lifecycle / logs / RCON code resolves the docker container name via `db.container_name_for(row)` — that helper returns the override when set, otherwise falls back to `servers.name`. Discovery's behaviour is split: new directories get `db.insert_server(name, dir, state)`, and existing rows get `db.update_server_state(name, state)` only — `dir` and `container_name` are **never** overwritten by a discovery scan. State lookup uses the override (so a re-pointed row still shows the correct container's state).

Rejected: storing `container_name` inside `servers.variables` JSONB (a row-level binding is not a runtime variable per decision 013, and JSONB columns are awkward to query). Rejected: writing through `dir` and `container_name` from discovery on every scan (silently undoes operator overrides — exactly the failure mode this decision is preventing). Rejected: deferring the override to a later slice (the underlying contract — discovery does not clobber — has to be true the moment any operator edits a row, and that capability lands this slice with the bindings UI).

Trade-off: discovery becomes two writes (a `get_server` followed by either `insert_server` or `update_server_state`) instead of a single `upsert_server`. At fleet sizes well under 100 servers this overhead is irrelevant, and the alternative — losing operator edits — is the kind of bug that erodes trust in the panel. The `dir` column starts populated on first INSERT only; subsequent scans never touch it, so an operator who repoints `dir` to a different host path will see that override survive every restart of the panel.

This decision pins the contract that future slices (file browser, scaffolding) inherit: any new operator-editable column on `servers` follows the same insert-on-new / state-only-on-existing rule. Discovery's job is to track presence + state, not to be the source of truth for any field an operator can edit.

## 022. Panel host-bind in base compose, parameterised

**Status:** Accepted · 2026-05-02

The panel's host-bind for HTTP (`<host-ip>:8003 -> container:8000`) lives in the tracked `docker-compose.yml`, parameterised by `${BSERVER_HOST_BIND_IP:-127.0.0.1}`. A fresh clone with no `.env` brings up an instance bound to `127.0.0.1:8003`, safe for local dev. bserver sets `BSERVER_HOST_BIND_IP` in its `.env` to the tailnet IP (currently `100.124.22.82`, per decision 003), making the bind survive LAN-side DHCP changes — which is what broke `mcontrol.noelkleen.com` on 2026-04-30 when bserver's LAN IP shifted (see `docs/fix-aserver-vhost-stale-upstream.md`).

This refines decision 019 — the per-host LAN bind no longer lives in a gitignored override file. The override pattern is fine in principle but it hides production state: the local repo had `expose: ["8000"]` while bserver had a hand-edited `docker-compose.override.yml` hard-coding `192.168.26.233:8003:8000`, and the divergence is exactly what made the DHCP-shift incident hard to diagnose.

The variable name `BSERVER_HOST_BIND_IP` is the corrected form of `BSERVER_LAN_IP`, the inherited misnomer from supabase-server's 2026-04-30 recovery — post-decision-003 that variable holds a tailnet IP, not a LAN IP.

Rejected:
- **Keep the override file, but commit it to the repo.** Removes the gitignore divergence but leaves two compose files to reason about for one bind line. Single source of truth wins.
- **Move the bind to a `docker-compose.bserver.yml`, invoked with `-f`.** Same one-line concern in a different file, plus changes the deploy command shape (`docker compose -f ... -f ... up -d` vs just `docker compose up -d`).
- **Bind on `0.0.0.0` and rely on host firewall.** Conflicts with decision 003's tailnet-only posture; one misconfigured firewall and the panel is on the public LAN.

Trade-off: a `docker compose up -d` on bserver without `BSERVER_HOST_BIND_IP` set in `.env` will bind to `127.0.0.1:8003`, invisible to aserver-nginx — the failure mode is "panel runs but vhost gives 502," same as the bug this decision fixes. The named env var and `.env.example` comment are the mitigations; an explicit `${BSERVER_HOST_BIND_IP:?must be set in production}` was rejected because it'd block local-dev `docker compose up -d` for anyone who hasn't copied `.env.example`.

## 023. No-Dockerfile scaffold model

**Status:** Accepted · 2026-05-05

Servers scaffolded by mcontrol have **no per-server Dockerfile, no entrypoint.sh, and no `.dockerignore`**. The generated `<dir>/docker-compose.yml` references `eclipse-temurin:21-jre` directly via `image:`, bind-mounts `<dir>/server/` to `/data` inside the container, sets `working_dir: /data`, and runs `command: ["./start_server.sh"]`. `start_server.sh` lives at `<dir>/server/start_server.sh` — inside the bind-mount, alongside the operator's jars, mods, configs, and world data. There is nothing for `docker build` to produce; `docker compose up` does a `docker pull` of the upstream image (cached fleet-wide after first pull) and runs the container.

This supersedes decision 001. The Dockerfile pattern (`COPY entrypoint.sh; ENTRYPOINT ["/entrypoint.sh"]`) inherited from the legacy fleet was justified there as preserving operational continuity, but with bind-mounts (decision 008) carrying everything operator-edited, the Dockerfile layer adds no value: there is nothing to bake into the image that isn't already on the host filesystem. Removing it eliminates per-server image builds entirely (build time literally zero), removes the build-context-size footgun where a multi-GB world directory gets re-shipped to the daemon on every rebuild, and collapses the regenerate flow from four files to two.

Rejected: **thin Dockerfile + `.dockerignore`** (the original slice 6 plan). Builds would be fast (~1 s, tiny context with `server/` excluded), but the layer adds nothing the bind-mount doesn't already cover, and decision 012 explicitly rules out baking per-server customisation into images. Three scaffold files (Dockerfile + entrypoint + .dockerignore) for no functional gain. Rejected: **per-server local-build images with `:latest` tag**, then with **`:scaffold-<timestamp>` tags** — both became moot once the Dockerfile itself was removed.

The pin policy in decision 020 applies cleanly: `eclipse-temurin:21-jre` is the only upstream reference the scaffold introduces, lives in one fixed string in `src/mcontrol/scaffolding/templates/docker-compose.yml.j2`, and bumps are one-line PRs. Tightening to a fully-resolved tag (e.g. `21.0.5_11-jre`) is a future option; the channel-pointer form matches the existing fleet's pin granularity for now.

Decision 014's mechanism updates accordingly: the legacy migration becomes "delete `Dockerfile` + `entrypoint.sh`, edit `docker-compose.yml` to point at `eclipse-temurin:21-jre` directly" rather than "rewrite Dockerfile and rebuild." 014's outcome (atm10 + monifactory running on temurin under mcontrol-managed config) is unchanged; only the steps change.

Trade-off: the scaffolded server depends on the upstream Eclipse Temurin image being pullable at start time. A registry outage delays start of any not-yet-cached server. Acceptable: the same risk applies to slice 1's `python:3.12-slim` and `ghcr.io/astral-sh/uv:0.11.7` references, and the cache means it's a one-time-per-version concern.

## 024. RCON password operator-managed in `server.properties`

**Status:** Accepted · 2026-05-05

The RCON password lives **only in `<dir>/server/server.properties`**, managed by the operator the same way `motd`, `view-distance`, `difficulty`, and every other Minecraft server property is managed. mcontrol does not generate it, write it, store it, or sync it. The RCON console route (slice 4) parses `rcon.password=` out of `server.properties` at SSE connect time to authenticate; if `enable-rcon=false` or the line is empty or the file is missing, the console surfaces a friendly error and lifecycle / logs / files keep working unchanged.

This supersedes decision 010. 010's premise — "DB is the source of truth, mcontrol writes `.env`, operator clicks Rotate" — required either env-var interpolation that vanilla MC doesn't do, or a `start_server.sh` `sed`-substitution sync, or an operator-paste step. Each option leaked complexity into a slice that didn't need to own RCON-password lifecycle. Operator-managed in `server.properties` makes the contract identical to every other server property: edit the file via the slice-5 editor, restart, done.

Slice-6 PR 0 closes 010's machinery: deletes `env_writer.py`, `passwords.py`, their tests, and the `_ensure_env_matches_db` branch in `routes/lifecycle.py`. Lifecycle's Start/Stop/Restart now hit the Docker API directly (no compose-up-on-env-change branch). The `app_mcontrol.servers.rcon_password` column becomes dormant; a future migration can drop it once we're confident nothing reads it.

Rejected: **`start_server.sh` sed-substitutes the `rcon.password` line on launch**. Targeted, idempotent, would have made decision 010's rotation flow auto-sync. But it conflicts with the cleaner stance that *server.properties is operator territory*, full stop — even one mcontrol-owned line erodes that invariant and creates rotation paths that depend on container restart timing. Rejected: **prompt the operator for the password in the panel when opening the console**. Adds friction for a value the operator already has on disk.

Trade-off: when the operator wants RCON, they enable it in `server.properties` (set `enable-rcon=true`, `rcon.port=25575`, pick a `rcon.password=`), restart, and open the console. Rotation = edit `server.properties`, restart. mcontrol provides no rotation button. The simplification is worth the lost button: rotation was a single-user nicety on an interface that isn't exposed off-tailnet anyway (decision 003). Disabling RCON entirely now genuinely "doesn't break anything else" — lifecycle, logs, file browser, scaffolding, variables, regenerate, delete all keep working without RCON.

## 025. Regenerate clobbers against the confirmed diff; mtime drift aborts

**Status:** Accepted · 2026-05-05

The Variables-card "Regenerate" flow (slice 6 PR 4) writes new `<dir>/docker-compose.yml` and `<dir>/server/start_server.sh` from templates, **clobbering operator hand-edits** to those two files. The diff preview is the operator's checkpoint: they see the unified diff between rendered template and disk, click Confirm, and the write proceeds. There is no merge logic.

Concurrency contract: the diff endpoint captures both files' mtimes alongside the rendered output; the modal carries them as hidden form fields; the confirm endpoint re-stats both files before writing and aborts with "Files changed since diff was shown — [Re-show diff] [Cancel]" if either mtime drifted. File-not-found is treated the same as drift. This preserves the "diff is the checkpoint" property: the operator can only clobber what they actually saw in the diff, even if a slice-5 editor save or upload landed in the gap between Regenerate-click and Confirm-click. Atomic-write uses the same `file_writer.atomic_write_text` helper as slice 5 so partial writes are impossible.

Rejected: **merge logic** for the two files. Both are short, structurally simple, and operator hand-edits are rare enough that diff-and-clobber is honest. Maintaining a key-by-key merge for compose YAML is real complexity for marginal benefit. Rejected: **clobber unconditionally on confirm**, ignoring concurrent edits. The diff would be stale and the operator's "yes, clobber" decision would apply to bytes they hadn't seen — defeats the checkpoint property. Rejected: **block all writes from any other route while a Regenerate is staged**. Cross-route locking for a single-user panel is a sledgehammer; mtime checks already give the operator a clean retry.

Slice-7 and beyond inherit the contract: any future "regenerate" affordance on operator-editable files (server.properties templating, plugin configs, etc.) follows the same diff-preview + mtime-check + clobber pattern. The merge-logic exit ramp stays closed by default.

Trade-off: a regenerate that races against a separate file-browser save round-trips the operator (re-show diff, re-confirm). At single-user fleet sizes this is theoretical — the operator is the only writer, and they're not racing themselves. The protection is real for the future-bug case where mcontrol acquires a background writer (auto-update, scheduled backups, etc.) that touches scaffold-shape files.

## 026. Delete tombstones; discovery skips `.`-prefixed dirs

**Status:** Accepted · 2026-05-05

Deleting a server through the panel **renames** `<base>/<name>/` to `<base>/.deleted-<name>-<unix-ts>/` and deletes the corresponding `app_mcontrol.servers` row. Files are not removed by mcontrol; permanent purge is a host-side `rm -rf` (or a future "Empty trash" affordance). Discovery (decision 021's contract) gains a single new filter: `if entry.name.startswith("."): continue` — so tombstoned directories are invisible to scans, as are `.git`, `lost+found`, and any other operator-introduced non-server dir under `<base>`.

The Delete button is **disabled when `state='running'`**, with a tooltip directing the operator to Stop first. The POST endpoint re-checks state at request time (returns 409 if running) — protecting against the operator starting the server in another tab between page render and confirm-click. The delete flow is type-name-confirm to match the destructive-op friction of slice-5's recursive-delete dialogue.

Rejected: **always wipe** (`rmtree(<dir>)` on confirm). Sharper edge for a destructive op on potentially gigabytes of world data; recovery would mean restoring from backup (decision 017 — backups are operator-managed via mods, not mcontrol). Tombstone is reversible by `mv .deleted-foo-* foo` from the host shell. Rejected: **cascade-stop** (Delete button stops the container automatically). Mixes two destructive operations into one click and hides the lifecycle effect; the running server might be mid-autosave when the cascade fires. Rejected: **soft-delete column on the row** (`deleted_at timestamptz`). Adds schema surface area for a state the disk-rename already encodes; discovery would still need to filter, and the column adds an "is this row really deleted" question to every read path. The disk tombstone is the source of truth.

Discovery's `.`-prefix filter is a robustness win independent of Delete: it preempts the failure mode where an operator drops `.git/`, `lost+found/`, or any other utility directory into `<base>` and discovery treats it as a server. Existing fleet members (atm10, monifactory, kobra_kollektivet) all use slug-shaped names, so the filter has no impact on legacy rows.

Trade-off: tombstoned directories accumulate on disk indefinitely until the operator manually purges. At single-host scale with rare deletes, the cost is small; the recovery path (rename back) is genuinely useful when an operator clicks Delete by mistake. A future "Empty trash" affordance can sweep tombstones older than N days when the cost stops being theoretical.

## 027. DB-backed player roster; disk-only per-server membership

**Status:** Accepted · 2026-05-08

`mcontrol` ships whitelist + ops management as a unified Players page plus per-server affordances. The model:

- A new table `app_mcontrol.players(uuid uuid pk, name text not null, added_at timestamptz not null default now())` holds the operator-trusted **roster** — one row per Minecraft identity. UUID is the key; `name` is the human-friendly handle and is refreshed on the Mojang lookup path or on Import.
- Per-server membership lives **only on disk**, in each server's `whitelist.json` and `ops.json`. mcontrol does not mirror membership into the database. The central Players page renders by reading every server's two files at request time and joining UUIDs against `players`.
- Adding to the roster is a synchronous Mojang lookup (`GET https://api.mojang.com/users/profiles/minecraft/{name}`). 204 → form error. 5xx/timeout → form error. 200 → upsert by UUID, refresh `name` if it differs.
- Adding a roster member to a server's whitelist or ops happens on the per-server detail page, picker-only — there is no free-type-name on per-server pages.
- Writes use the established split: RCON when running (`/whitelist add/remove`, `/op`/`/deop`); atomic JSON read-modify-write with mtime stale-write check when offline (slice 5/6 pattern). Output is vanilla-shaped: 2-space indent, list of objects, trailing newline, insertion order on round-trip.
- Removing from the roster opens a cascade-confirm modal: "Roster only" leaves disk untouched; "Remove from all servers" runs the per-server remove for each membership before deleting the `players` row. Pre-scan for the modal is the same render-time read we already do for the matrix.
- An Import button on the Players page walks every server's two files, upserts unknown UUIDs into `players` (taking the JSON's `name` at face value — those entries were authored by the Minecraft server itself from authoritative Mojang data on first join). The page top surfaces "N memberships on disk for unknown UUIDs" as an affordance pointing at this button when the count is non-zero.
- No level dropdown for ops; vanilla `/op` always grants level 4 and `ops.json` cannot be hot-reloaded for non-default levels without restart. Granular levels remain a slice-5-file-browser task.
- No `white-list` / `enforce-whitelist` toggle in the UI — `server.properties` stays operator-managed (decision 024). The central page surfaces a small "whitelist disabled on this server" indicator when `white-list=false` so the failure mode is legible.
- No legacy gating. The whitelist/ops affordances render on every server regardless of `scaffolded_at` state — `whitelist.json` and `ops.json` exist for all server kinds, and the disk-as-truth model doesn't depend on scaffold templates.

This supersedes **decision 018**, which sketched the same scope but rejected DB-mirrored player lists ("defer until that's a felt pain") and promised a level dropdown, `bypassesPlayerLimit` flag, and toggle UI that this decision drops. The felt pain has now been articulated: the operator wants to type a name once and reuse the identity across servers without re-typing on each per-server flow. The original rejection rationale stands for **per-server membership** — that part stays disk-only — but a roster table is a different concept and is added.

Rejected:
- **Mirror per-server membership in DB** (`whitelisted_on(player_uuid, server_name)` etc.). At ~6 servers and ~tens of players, the file scan is faster than the round-trip to Postgres, and slice 5's file editor can mutate `whitelist.json` directly — which means any DB mirror must reconcile drift on every render. The DB would become a cache of disk state, which is the wrong direction; disk-as-truth eliminates the failure mode.
- **Soft-delete from roster.** `players` rows are hard-deleted; the cascade modal handles the consequence question explicitly. A soft-delete column would add schema surface area for a state the cascade decision already resolves.
- **Auto-cascade on roster delete.** Single click that pretends to be simple while removing players from N servers is exactly the footgun a confirm modal exists to prevent.
- **Per-server level dropdown for ops.** Vanilla doesn't reload `ops.json` without restart; surfacing a dropdown that promises levels but requires a restart for any non-default value would either lie about the UX or import a restart-and-apply flow that no other slice-7 affordance needs.
- **Online-mode-and-offline-mode support.** The fleet runs online-mode-only and there's no signal of an offline-mode server appearing. Mojang lookup is a hard dependency for adds; a future slice can add offline-UUID derivation if it ever matters.

Trade-off: roster-add depends on Mojang reachability — operator can't register new players when Mojang is down. Acceptable: rare, transient, and the failure surfaces cleanly. Render-time disk reads on every Players page hit cost ~6 file opens at single-host scale; acceptable. The cascade modal is more code than a one-button delete, but it's the difference between a panel that surprises the operator and one that doesn't. The roster table itself is one-column-shy of trivial; bumping its schema later (e.g. adding a `notes` column for "this is Bob's friend, OK to op") is a small migration whenever the need is felt.

## 028. One-shot legacy-to-scaffold migration; no dual-shape framework

**Status:** Accepted · 2026-05-09

The legacy itzg-shaped servers (`atm10`, `monifactory`; `kobra_kollektivet` excluded by operator stance per decision 014) are converted to the slice-6 scaffold shape **per server, on operator click, one-way**. The detail page surfaces a "Legacy server — Migrate to scaffolded shape" card whenever `scaffolded_at IS NULL`. The form is pre-populated by a best-effort regex parse of the legacy `server/start_server.sh` and `docker-compose.yml`; the operator confirms the values and clicks Migrate. POST renders both scaffold templates, atomic-writes `<dir>/docker-compose.yml` + `<dir>/server/start_server.sh` (chmod 0o755), unlinks `<dir>/Dockerfile` + `<dir>/entrypoint.sh` + `<dir>/.dockerignore` + `<dir>/.env` (each `missing_ok=True`), then writes `variables` JSONB and stamps `scaffolded_at = now()`. Once stamped, the row is treated identically to a slice-6 scaffolded row for the rest of its life — Variables card, Regenerate, and Delete behave the same; the migration card never reappears.

The migration runs **only when state ≠ 'running'**: the button is disabled when running, the POST endpoint re-checks state at request time and returns 409 on race, mirroring the Delete flow's pre-flight (decision 026). RCON has no pre-flight — decision 024 puts `rcon.password` in `server.properties` as operator territory, and the legacy fleet's hardcoded `RCON_PASSWORD=rconer` env var was inert under the override-entrypoint pattern.

This decision lands the **outcome** of decision 014 (atm10 + monifactory running on temurin under mcontrol-managed config) via the **mechanism** of decision 023 (no-Dockerfile scaffold model). 014 is unchanged in intent; 023's scaffold layout is the migration target shape; 024's RCON posture forces the `.env` cleanup that goes alongside.

Rejected:
- **Dual-shape support — keep "legacy mode" as a parallel code path.** A feature flag or `if not scaffolded_at` branch through every lifecycle/regenerate/variables surface multiplies code by 2× for an operator stance that is "convert all three rows once and never look back" (decision 014's framing). The convergence is the point.
- **Auto-run migration on app startup or discovery.** Decision 014 originally framed it as a "first import pass"; that framing predates 023's destructive (file-deleting) mechanism. Auto-run for a destructive op without an explicit click is the wrong default.
- **Bulk migrate from the home page.** Two clicks on two rows is not a felt pain; bulk would mostly multiply blast radius.
- **CLI subcommand.** The detail page is the natural workflow surface; a CLI would duplicate the same DB + file ops behind a second entry point. Add only if the panel is ever unreachable when the migration is wanted.
- **Diff preview before clobber.** The migration is wholesale replacement, not a targeted edit; the rendered output is deterministic from the operator's form values and the legacy bytes are about to be replaced wholesale. Slice-6's Regenerate flow (decision 025) covers any post-migration edits via the diff-and-clobber checkpoint.
- **Rollback button.** One-way. Reverting means restoring the deleted `Dockerfile` + `entrypoint.sh` + `.dockerignore` + `.env` from the operator's own backup or git history; that's outside the panel's responsibility.
- **Migration transaction wrapping the whole flow.** File ops can't participate in a Postgres transaction. The natural ordering — render templates → atomic-write target files → unlink legacy → DB stamp — makes each step idempotent on retry, and the final `mark_scaffolded` call is the canonical "this row is migrated" signal.

Trade-off: a row whose file ops succeeded but whose `mark_scaffolded` call failed sits in a temporarily-mixed state on disk (legacy files gone, scaffold files written) but is still flagged legacy in the DB. The card stays visible; the operator re-clicks Migrate and the idempotent flow re-converges on the same end state. Accepted because the alternative — an automatic rollback that recreates `Dockerfile` + `entrypoint.sh` from the panel — is impossible without source bytes the panel never stored.

This entry forecloses the dual-shape exit ramp once and for all: future slices that touch lifecycle, scaffolding, regenerate, or files do **not** branch on `scaffolded_at`. After this slice lands, every row in the fleet is either pre-migration (no-op until clicked) or post-migration (slice-6-shape, period).

## 029. Drop dormant `rcon_password` + `image_base` columns

**Status:** Accepted · 2026-05-10

`app_mcontrol.servers.rcon_password` and `app_mcontrol.servers.image_base` are dropped from the schema. Both columns are dormant in the running app: nothing in `src/mcontrol/` reads or writes either one after this slice lands. The cleanup is the closing-bracket on two earlier "future migration" notes — decision 024's "the column becomes dormant; a future migration can drop it once we're confident nothing reads it" for `rcon_password`, and slice 8's plan-doc deferral for `image_base` ("Lives alongside the `rcon_password` column-drop … one future migration cleans up both dormant columns").

The cleanup ships as two coordinated changes in the slice-10 PR sequence:

1. **mcontrol PR (this repo, slice 10).** Removes the one remaining read site (`<dt>base image</dt>` block in `server_detail.html`), drops both keys from every test fixture, deletes the now-meaningless `test_server_detail_handles_null_image_base` test, and drops the `eclipse-temurin:21-jre` body assertion in the happy-path detail test that the template line was producing. `db.py` is untouched — slice-6 PR 0 already removed every writer, and `select("*")` stops returning the keys the moment Postgres drops the columns.
2. **supabase-server migration (separate repo, decision 015).** Operator hand-creates a migration file with `alter table app_mcontrol.servers drop column if exists rcon_password, drop column if exists image_base;` and applies it via `make migrate` on bserver. Decision 015 keeps schema migrations out of this repo; this entry records the SQL spec but the file lives in `bserver:~/repos/supabase-server/supabase/migrations/`.

**Ordering precondition.** mcontrol PR is merged and the bserver `app` container is rebuilt + restarted **before** the supabase-server migration runs. The template was null-safe (`{% if server.image_base %}` falls through to em-dash placeholder when the key is missing), so running the SQL first wouldn't 500 the panel — but the discipline "code change first, schema change second" keeps the DB shape always at least as wide as what the running app reads, which is the right invariant for the convention regardless of any single column's null-safety.

Rejected:
- **Drop the columns in this repo's code as a one-shot.** Decision 015 is unambiguous: schema lives in `supabase-server`, not here. Encoding the DROP in mcontrol would split the source of truth.
- **Leave the columns in place indefinitely.** They would accumulate ambiguity for every future reader of the schema — "is this column wired up or not?" — which is exactly the cost the dormant-flagging in 024 / slice 8 was paying down. Closing the bracket now keeps that debt small.
- **Drop more columns at the same time.** Surveyed `app_mcontrol.servers` for other dormant columns; every other column carries live behaviour (`scaffolded_at` gates the slice-6 vs slice-8 paths, `container_name` is decision 021's override, `variables` JSONB is decision 013, etc.). Single-purpose slice; surveying for further dormants is a future cleanup if the felt need ever arises.
- **Add a `TypedDict` for the row shape now that it's smaller.** Pre-existing absence of typed row dicts is unrelated to this cleanup; bundling the change would expand the diff for no immediate benefit.

Trade-off: drop is destructive — re-adding the columns later would leave NULLs in every row (no data preserved). Acceptable: nothing currently uses either column, so there is no data to preserve. If a future slice ever wants RCON password storage in the DB again, that slice introduces its own decision; the mechanism would not be "restore from backup," it would be "design the column from scratch."

Historical slice plan docs (slices 1, 2, 3, 4) still reference the dropped columns. Plans are append-only history per the project's convention; rewriting them to match the post-migration schema would obscure the decision trail. The decisions register and slice 10's plan-doc carry the corrected forward-looking shape.

## 031. Empty-trash affordance: tombstone purge with 7-day default

**Status:** Accepted · 2026-05-10

mcontrol gains a `/trash` page that lists every `<base>/.deleted-<name>-<unix-ts>/` tombstone with parsed original-name, age, and bytes-on-disk; surfaces an **Empty trash** button that purges every tombstone older than 7 days; and surfaces a per-row **Delete now** button that purges a single tombstone immediately. Both actions go through type-name confirm modals — `EMPTY` (uppercase literal) for the bulk action, the parsed original server name for the per-row action. Closes the deferred trade-off line in decision 026 ("tombstoned directories accumulate on disk indefinitely until the operator manually purges … a future 'Empty trash' affordance can sweep tombstones older than N days when the cost stops being theoretical").

Threshold = **7 days**, hard-coded in `src/mcontrol/tombstones.py` as `_DEFAULT_PURGE_AGE_DAYS = 7`. Not exposed in the UI this slice. Decision 026's trade-off names "older than N days" but doesn't pick N; 7 is short enough that an operator who deletes by mistake notices within the recovery window (a typical week's working pattern), long enough that an Empty-trash run after a planned cleanup actually frees the bytes. A configurable threshold (per-environment ENV var, settings field) is a follow-up if the felt need ever arises.

Path-safety lives in `tombstones.purge_one(base, dir_name)`:
1. `dir_name` must `re.fullmatch` the regex `^\.deleted-[a-z][a-z0-9-]{2,31}-\d+$`. URL-decoded payloads like `..` / `../foo` / `foo/bar` / `foo%00bar` fail the regex (hyphen + dot + slash + null are outside `[a-z0-9-]`) and never reach the filesystem.
2. `target.parent` must equal `base.resolve()`. Defends against the theoretical "regex passed but `Path` resolution still landed us elsewhere" case.
3. `target` must be a real directory, not a symlink — guards against an operator who dropped a symlink with a tombstone-shaped name into `<base>`.

Discovery's dot-prefix filter from decision 026 keeps doing its job — `/trash` bypasses discovery and reads `<base>` directly with `os.scandir`. The two read sides never overlap: discovery skips dot-prefixed entries; `/trash` only sees them.

Bytes-on-disk reuses `resources.read_disk_usage` (slice 9) — the recursive `os.scandir` walk with `follow_symlinks=False` is exactly the right primitive, already tested. Forking a near-identical walk in `tombstones.py` would be the "200 lines that could be 50" anti-pattern.

Top-nav: a new partial `templates/_topnav.html` carries Servers / Players / Trash links, included from `templates/trash.html` and `templates/_players_main.html`. `templates/home.html` is intentionally left alone this slice — PR #39 was concurrently editing it; the swap of `home-header__actions` for the topnav partial is a one-line follow-up after #39 lands. Single-operator panel; the asymmetry (home keeps its inline nav block until then) is acceptable.

Rejected:
- **Configurable threshold UI.** The `7` lives in code only. If the felt need is "different defaults per environment," that's a future decision (ENV var or settings field). The build-and-deploy cost of bumping `_DEFAULT_PURGE_AGE_DAYS = 7` to a different number is one line + a test bump.
- **Restore button.** Slice-6 delete copy says "recover by renaming the tombstone back from a shell"; that recovery path stays. A panel-side Restore would import a new flow (DB row re-creation, dir-name collision, `container_name` override repointing) for a rare case the shell already handles.
- **Automatic purge on a schedule.** No cron, no startup-time sweep. Decision 026's trade-off is explicit: tombstones are deliberately recoverable by default; auto-purge would silently destroy that reversibility. The Empty-trash button is the operator's deliberate moment.
- **Bulk select / multi-row delete.** Empty-trash is the bulk affordance (sweeps all ≥ 7 d), Delete-now is the single-row affordance. A free-form multi-select adds modal complexity for the felt-need-of-zero case.
- **HTMX inline-delete vs full-page redirect.** Plain redirect (`HX-Redirect: /trash` on POST) is the simplest pattern that's correct: one DOM tree, one source of truth (the GET handler), no partial-state assertions in tests. The cost is a flicker on each delete; for a page that gets visited a few times a year, it's free.
- **Tombstone count badge on the home page.** "(3)" next to the Trash link would be nice but punted to a follow-up. Single-operator scale, the Trash link itself is the affordance.
- **Replacing `home.html`'s inline nav with the new partial.** Off-limits this slice — PR #39 was editing home.html.

Trade-off: a tombstone whose name fails the regex (an operator manually renamed something to a `.deleted-…` shape that doesn't validate) is invisible to `/trash` and survives Empty-trash sweeps indefinitely. Acceptable: operator-renamed dirs are operator territory; the shell is the right tool for cleaning them up. A best-effort failure during `purge_older_than` (e.g. `rmtree` raises mid-walk because of an open file handle) is recorded as the loop moving past it; the remaining sweep continues, and the next page load surfaces what's still there. The 7-day cutoff means a same-day mistaken-delete is always recoverable from the tombstone; a long-tail of stale tombstones from an unattended panel is what the bulk button cleans up.

This entry forecloses 026's "future affordance" line. Future slices that surface deleted-server-related affordances (e.g. a tombstone-count badge, a per-tombstone Restore button, a configurable threshold) would be additive on top of this contract, not a re-litigation.

## 030. Deep `/healthz`: per-subsystem probe with 503-on-degraded

**Status:** Accepted · 2026-05-10

`GET /healthz` is the panel's readiness URL — a single endpoint that exercises every subsystem the panel needs to function: Supabase reachability (a head-only `select` against `app_mcontrol.servers`), Docker socket reachability (`aiodocker.system.ping()`), and the bind-mount base path being a writable directory (`is_dir()` plus a `.healthz-<pid>-<rand>` touch + unlink). The three probes run concurrently via `asyncio.gather(..., return_exceptions=True)` behind a 250 ms per-probe `asyncio.wait_for`. Response is JSON in a single envelope shape — `{ "status": "ok" | "degraded", "checks": {...}, "elapsed_ms": int }` — with HTTP **200** when every probe is `"ok"` and HTTP **503** when any one is `"fail"`.

The status-code split is the contract that matters. Decision 019 puts an upstream nginx terminator on aserver in front of the panel; nginx's `proxy_next_upstream` / `health_check` directives decide upstream-up vs upstream-down based on HTTP status. A 200-with-`status: degraded` body would force nginx (and any future monitoring) to parse JSON to know if the panel is up — defeating the point of the readiness URL. Returning real 503 keeps the consumer-side check trivial: `if status == 200: route to upstream; else: don't`. Wiring the nginx config is operator's hand on aserver, not in this repo.

No auth gate — decision 003's tailnet-only access is the gate, and an HTTP gate would block nginx's probe without buying anything the network layer doesn't already give. No caching — staleness defeats the readiness purpose; if 250 ms × 1 probe (concurrent) ever becomes felt latency, that's a future deferred-cache slice with a query-param escape hatch, not a today problem. The endpoint always returns JSON in the same envelope shape regardless of status code, so `nginx`'s probe and the operator's `curl` see identical structure.

The `detail` field in each subsystem's record is `f"{type(exc).__name__}: {exc}"[:200]` — class name plus the exception's message, length-capped, never `repr(exc)`. The `Settings` object holds `SUPABASE_SERVICE_ROLE_KEY`, and a third-party library exception's `repr` could inline arbitrary attribute values; using `str(exc)` (the message slot) keeps secret-leak surface minimal. Tests pin this contract by raising an exception whose `repr` would include the key and asserting the detail string is built from `str(exc)` not `repr(exc)`. The pin documents the contract: callers must keep secrets out of the message itself; healthz's job is the no-traceback / capped-length defence-in-depth, not scrubbing arbitrary message contents.

Module split: `src/mcontrol/healthz.py` owns the probes and the envelope; `src/mcontrol/main.py`'s route is a one-liner that calls `healthz.build_report()` and returns a `JSONResponse(status_code=...)`. Distinct from `src/mcontrol/health.py` (per-server scaffold-integrity for the detail-page banner) — different question, different consumer, different module. Future contributors reading the import list shouldn't have to guess which `health*` is which.

Rejected:
- **Single-line liveness endpoint (the previous shape).** A 200-always endpoint that doesn't actually probe anything will report up while the Docker socket is unreachable or the bind-mount is read-only — exactly the failure modes nginx and the operator need to detect. Worse than useless once a real reverse proxy depends on it.
- **Split into `/livez` + `/readyz` (Kubernetes-style probe pair).** Useful when a load-balancer can yank an instance from rotation independently of restarting it; not the deployment shape here. Single-host, single-operator, one URL with a per-subsystem breakdown is enough for both nginx and `curl`. If the panel ever runs behind a k8s-style probe pair, that's a future decision.
- **200-with-`status: degraded` instead of 503.** Forces every consumer to parse the body to know if the panel is up. Real 503 keeps nginx's check trivial.
- **Sequential probes.** Three independent reads; serial would be ~750 ms worst-case for no reason. `asyncio.gather` keeps worst-case endpoint latency at ~250 ms (one probe).
- **Per-subsystem caching with a short TTL.** Staleness in a readiness signal is exactly the bug. If the 250 ms × 1 cost ever becomes felt, the right surface is a query-param escape hatch (`/healthz?cache=5s`) on a future slice, not making today's caller eat staleness by default.
- **Configurable per-probe timeouts.** 250 ms is hard-coded across all three. If one subsystem ever needs a longer cap, refactor then; the current shape is the simplest thing that's correct.
- **HTTP auth gate.** Decision 003 — network layer is the gate; an auth gate would block nginx's probe.
- **Prometheus exposition format.** Out-of-scope; if metrics scraping is wanted, a separate `/metrics` route is the right surface. Overloading `/healthz` mixes two concerns.
- **Probing every server's container in addition to the daemon.** The endpoint answers "is the panel itself up?" — per-server health is `mcontrol.health`'s job (detail-page banner) and the home-page memory column (slice 10). Conflating them would make `/healthz` 503 whenever any single server's container is unreachable, which is the wrong granularity for a panel-readiness URL.
- **Folding the logic into `main.py`.** `main.py` is the wiring shell; logic lives in modules so it's testable in isolation without `httpx.ASGITransport` ceremony.

Trade-off: every `/healthz` hit costs three concurrent probes against three subsystems. At nginx's typical health-check interval (~5–30 s) this is irrelevant; if a future monitoring tool ever scrapes at 1 s cadence, the deferred-cache exit ramp above is the answer. The 250 ms timeout is a single human-perceptible blink; under normal conditions the endpoint returns in well under 100 ms. The endpoint's correctness contract — "200 iff the panel can actually serve" — is what justifies paying that cost on every request.

## 032. Claude-flavoured theme; semantic tokens; tri-state dark/light

**Status:** Accepted · 2026-05-10

The panel adopts a Claude-flavoured theme: warm-cream `#FAF9F5` page surface in light mode, near-black `#141413` page surface in dark mode, terracotta `#D97757` accent used sparingly, Inter Tight humanist sans for body/UI, mono kept for code/log/RCON. The CSS contract is a two-layer token system: a primitive layer and a semantic layer (`--bg-page`, `--bg-surface`, `--bg-sunken`, `--fg-primary`, `--fg-secondary`, `--fg-muted`, `--accent`, `--success`, `--warning`, `--danger`, `--border-soft`, `--border-medium`, `--border-strong`, `--ring`, etc.). Components consume the semantic layer only; every hex sits in `tokens.css`. Theme switching is a tri-state operator pref (system / light / dark) persisted to `localStorage` and applied via a `data-theme` attribute on `<html>`. A small inline `<head>` script bootstraps the attribute before stylesheets evaluate to prevent flash-of-wrong-theme; an `@media (prefers-color-scheme: dark)` block is the JS-off fallback. The toggle is a segmented sun/moon/monitor control in the page-chrome top-right.

This supersedes **decision 002**. 002 pinned the panel to `AbstractNucleus/design`'s shared tokens — warm paper, rust accent, monospaced throughout — for sibling-tool consistency. The trade-off was real: visual changes ripple from one place across `mcontrol` and any sibling tools that adopt the palette. The supersession is a deliberate stance reversal: cohesion-with-siblings was a hypothetical benefit (no other tool has actually adopted the AbstractNucleus tokens), and the cost — a uniformly-mono panel reading as "ops-tool-from-2008" rather than "panel from someone who builds on Claude" — became the felt cost. The new goal is a polished, identifiably-Anthropic single-app surface; sibling-tool consistency is no longer a constraint.

`scripts/sync_design.sh` and the AbstractNucleus token-source pointer are removed. The new `tokens.css` is a hand-authored file in this repo, owned here, bumped by PRs against this repo. If a sibling tool ever wants to consume the new tokens, the right mechanism is to copy the relevant subset into that tool — not to point both at a third-party source. Single source of truth per app; theming is a per-app concern.

Type stack: `Inter Tight` for body and UI with a humanist-sans system fallback chain (`-apple-system`, `BlinkMacSystemFont`, `"Segoe UI"`, `system-ui`, `sans-serif`); `ui-monospace` family for code, RCON output, log streams, tabular numerals, and identifier-shaped values like server names + container IDs. No serif accent — claude.ai's chat surface is sans throughout; a serif headline would feel marketing-flavoured against a control panel. Self-host or CDN are both acceptable; the stack falls through to the OS font cleanly when neither is present, so first paint is correct without a network round-trip.

Surface coverage contract: every rendered element has a deliberate token assignment. The audit identified two pages (`/players`, `/trash`) and several partials (`_players_main.html`, `_player_remove_modal.html`, `_server_players_card.html`, `_trash_*.html`) where CSS classes existed in markup but had no matching rules in `app.css` — those pages rendered as bare unstyled HTML. Slice 12 closes the gap: every class referenced by a template has a rule. New empty-state designs land for home / players / trash / per-server-detail panes that previously fell back to a `<p>` of plain prose. Custom 404 and 500 templates land alongside.

Tri-state toggle UX rationale: binary toggle is simpler (~10 fewer LOC) but loses the operator who switches between light-OS-by-day and dark-OS-by-night, who would have to manually flip the panel each time. Tri-state default = "system" matches `prefers-color-scheme`; the operator only ever has to interact with the control if they want to override. Persistence is per-browser via `localStorage`, not per-account; the operator-as-implicit-user contract from decision 011 means there is no user account to attach a server-side preference to. Per-device override is the right granularity.

Focus-ring posture: rings are a near-black-or-near-white at 70% opacity, two-pixel solid outline with two-pixel offset. The brand orange is identity, not structure — focus rings stay neutral and pick up surface tint via translucency. This matches Anthropic's published pattern in the MCP-apps design guidelines.

Rejected:

- **Layer a Claude theme on top of the existing AbstractNucleus tokens via overrides.** Considered for one round. The primitives below the semantic layer would carry two parallel realities — the AbstractNucleus rust + paper, and the Claude clay + cream — with no consumer of the originals. The double-bookkeeping cost is real, and a future reader has to know which is the live reality. Replace cleanly.
- **Keep `scripts/sync_design.sh` pointed at a different source.** No upstream now exists for the new theme; pointing it at a stub would be ceremony with no value. Removed.
- **Single binary light/dark toggle.** Fewer lines of code; loses the system-default UX. The third state is one extra icon and one extra branch.
- **`prefers-color-scheme` only (no operator override).** Forces the operator to flip the OS theme to flip the panel. Wrong for a power tool.
- **Cookie-based theme persistence.** Couples the per-browser theme choice to the request lifecycle; conflates operator preference with session state. `localStorage` + inline `<head>` script is the modern static-site pattern (used by MDN, Tailwind docs, GitHub docs, every Astro/Next theme template) and is what the panel uses.
- **Server-rendered theme attribute (no client-side script).** Would require a cookie or header round-trip on first visit and re-render on every toggle. The inline script is one IIFE in the head, runs before stylesheets, and the toggle handler is a tiny client-only file.
- **A serif-accented marketing flavour (Tiempos / Source Serif).** Reads as anthropic.com, not as claude.ai. The panel is closer in spirit to the chat surface than to the marketing site; sans throughout is more honest.
- **A bundler / Tailwind / shadcn-ui to manage the token system.** Decision 016 forecloses bundlers. A handwritten `tokens.css` + handwritten `app.css` is the existing posture; the slice's job is to swap the contents, not the build shape.
- **Adding a build step to compile `tokens.css` from a JSON token source.** Same shape as the bundler rejection above. The CSS file is the source.
- **Brand orange as the focus-ring colour.** Visually appealing but not the Anthropic pattern; rings need to work on every surface (including buttons that already use orange as their fill), and a translucent neutral works there cleanly while a saturated orange ring on an orange button is a contrast disaster. Reserved orange for identity / CTA only.
- **An "auto-dismiss every flash after 4s via setTimeout."** Modern CSS animation with `forwards` does the same with one rule and no JS lifecycle. Adopted the CSS form.

Trade-off: the panel's visual language drifts from any future sibling tool's. If a `bcontrol` or `cservices` ever appears in this fleet and wants visual coherence with `mcontrol`, the path is "copy the relevant subset of `mcontrol/static/tokens.css` into that tool" rather than "point both at a third-party design repo." The cost is "a token bump in one tool doesn't auto-propagate"; the benefit is "neither tool's visual identity is hostage to a repo neither owns." At single-operator scale and one-app horizon, this is the right side of the trade.

The contract this entry pins for future slices: any new component / partial gets a deliberate styling pass (no class-without-rule). New tokens, if needed, get added to the semantic layer in `tokens.css` — components consume the semantic name, never the primitive. The two-mode contract (light + dark with explicit override) is invariant; new colour decisions land in both modes simultaneously.

## 033. Lifecycle buttons: state-aware disable + accent on next-action

**Status:** Accepted · 2026-05-11

The three lifecycle buttons on `/servers/<name>` (Start / Stop / Restart) render with `disabled` and `--accent` (`.btn--primary`) reflecting the server's current state. The mapping is a pure function in `mcontrol/lifecycle_state.py`:

| State (`server.state`) | Start | Stop | Restart | Accent |
|---|---|---|---|---|
| `created`, `exited`, `dead` | enabled | disabled | disabled | Start |
| `running`, `paused` | disabled | enabled | enabled | Stop |
| `restarting`, `scaffolding` | disabled | disabled | disabled | — |
| unrecognised / `unknown` / `None` | enabled | enabled | enabled | — |

After a lifecycle action (Start / Stop / Restart) lands, the route handler returns a single HTML body carrying two HTMX swap targets: the state pill (primary swap to `#state-pill` via `outerHTML`, unchanged shape from earlier slices) and the lifecycle-buttons wrapper marked `hx-swap-oob="true"`. HTMX swaps both, so the three buttons re-render in lock-step with the freshly-updated state without a page reload. The partial is `templates/_lifecycle_buttons.html`; the initial render comes from `server.py` passing `lifecycle=lifecycle_state.view(state)` into context, and the OOB renders come from `lifecycle.py`'s `_pill_and_buttons` helper rendering both partials and concatenating their HTML.

This closes the deferred follow-up from slice 12 / decision 032. The slice 12 plan kept all three buttons unconditionally enabled and applied no accent, with a deliberate "lifecycle-aware accent is a follow-up" note. Decision 033 is that follow-up.

Rejected:

- **Disable on the client via a `state`-attribute selector.** Would mean shipping a small JS file that mutates `disabled` on the buttons whenever the state pill changes. The OOB swap is one HTTP response, no extra script, and stays consistent with the rest of the panel's HTMX-driven posture (decision 016).
- **Re-render the entire `server_detail.html` after every lifecycle action.** Would clobber transient client state (open `<details>`, scroll position, in-flight resources/players polls). The two-target swap is the minimum surface that needs updating.
- **A dedicated `unpause` route for paused containers.** `paused` is rare; the operator's recovery path is Restart (which kill+restarts the container) or Stop. Adding a fourth route would be its own slice. Treat `paused` like `running` for now.
- **Accent on Restart when running.** Considered. Stop is the only button whose action is uniquely meaningful for a running server — Restart is "stop then start," a strict superset. Pinning the accent on the smallest unambiguous action is the consistent rule.
- **Disable in `scaffolding` quietly without a banner.** The health banner already explains "stuck scaffolding" when relevant (decision 030); disabling the lifecycle buttons in `scaffolding` is the matching no-mixed-signals posture.
- **Polling the buttons on a timer like the resources card.** The state pill is also not polled — it updates only on operator action. Same posture for the buttons: post-action OOB swap is the only update channel.

Trade-off: if the actual container state diverges from `server.state` in the DB (e.g. the container was started or stopped via `docker` CLI outside mcontrol), the buttons reflect the stale DB state until discovery re-runs at next app boot. Same trade-off the state pill already accepts (decision 021 / discovery-at-startup). A "rescan" affordance is parked in the slice 3 follow-up; if it ever lands, the buttons pick up the fresh state for free via the same partial.

