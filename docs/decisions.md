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

## 001. Base image: `eclipse-temurin:21-jre`

**Status:** Superseded by 023 · 2026-04-26

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
