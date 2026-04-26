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
| 004 | Thin MC-aware UI over per-server compose             | Proposed | 2026-04-26 |
| 005 | Single-host scope                                    | Proposed | 2026-04-26 |
| 006 | Inherit Docker-socket access from `admin_management` | Proposed | 2026-04-26 |
| 007 | Postgres 17 as backing store                         | Proposed | 2026-04-26 |
| 008 | Bind mounts (not named volumes) for server data      | Proposed | 2026-04-26 |
| 009 | Per-server Docker `mem_limit`                        | Proposed | 2026-04-26 |
| 010 | Rotate hardcoded `RCON_PASSWORD`                     | Proposed | 2026-04-26 |
| 011 | Panel auth model                                     | Open     | 2026-04-26 |
| 012 | Modpack workflow                                     | Open     | 2026-04-26 |
| 013 | Egg JSON schema borrowing                            | Open     | 2026-04-26 |
| 014 | Convert existing itzg-based servers to temurin       | Open     | 2026-04-26 |

## 001. Base image: `eclipse-temurin:21-jre`

**Status:** Accepted · 2026-04-26

All Minecraft server containers run on `eclipse-temurin:21-jre` as the base image. The custom Dockerfile pattern (`COPY entrypoint.sh; ENTRYPOINT ["/entrypoint.sh"]`) stays — `entrypoint.sh` does `cd /data && exec ./start_server.sh` and `start_server.sh` invokes `java -Xmx... -jar <loader>.jar nogui`.

Rejected: `itzg/minecraft-server`. Its env-var contract (`TYPE=`, `EULA=TRUE`, server.properties templating) is the project's primary value, but `mcontrol` is not going to drive servers through that contract — and overriding the entrypoint to run our own `start_server.sh` (which is what the bserver setup already does for `atm10` and `monifactory`) reduces the image to a glorified JRE base. Going to temurin removes the pretence.

Trade-off: we give up itzg's auto-install, modloader detection, and modpack `TYPE` selectors, and take on the responsibility of writing each server's `start_server.sh` ourselves. Decision 012 (modpack workflow) is the consequence to think through.

## 002. UI palette: `AbstractNucleus/design`

**Status:** Accepted · 2026-04-26

The panel UI consumes design tokens and components from [`AbstractNucleus/design`](https://github.com/AbstractNucleus/design): warm paper background, rust accent, monospaced typography throughout.

Rejected: ad-hoc styling, and adopting the visual language of any forked panel (Pterodactyl, Pelican, etc.). The palette repo is the single source of truth for tokens, type, spacing, and component styles.

Trade-off: every new component must consume the palette rather than introduce its own colours/type. Cost is discipline; benefit is that visual changes ripple from one place across `mcontrol` and any sibling tools that adopt the palette.

## 003. Tailnet-only access via Cloudflare DNS-01

**Status:** Accepted · 2026-04-26

The `mcontrol` UI is reachable only from devices on the user's Tailscale tailnet. Public DNS (Cloudflare, gray cloud) resolves the hostname to the host's `100.x.y.z` tailnet IP; off-tailnet packets cannot be routed there. Caddy on the host terminates TLS using a Let's Encrypt cert obtained via the Cloudflare DNS-01 challenge — no public ingress. See [`patterns/tailnet-https-via-cloudflare.md`](patterns/tailnet-https-via-cloudflare.md) for the canonical setup.

Rejected: public ingress + app-level auth, and Tailscale Funnel. Public ingress would force a real auth story before there's a need for one (decision 011 stays Open as a result). Funnel exposes paths to the open internet, which defeats the point.

Trade-off: anyone who needs access has to be invited to the tailnet. That's the desired posture for a single-user / small-trusted-group panel; it would be the wrong call if `mcontrol` ever needs to onboard untrusted users.

## 004. Thin MC-aware UI over per-server compose

**Status:** Proposed · 2026-04-26

`mcontrol` is a thin Minecraft-aware UI layered over the existing per-server `docker-compose.yml` + custom `Dockerfile` + `start_server.sh` pattern from `bserver`. It is not a fork of Pterodactyl, Pelican, or any other panel; it does not embed Wings or a Periphery agent; it talks to the local Docker socket directly.

Rejected: forking Pterodactyl/Pelican (path-1 in the research; gets features for free but inherits a fork-maintainer burden), shipping eggs into an existing panel (path-2; locks UX into someone else's UI), integrating against Portainer as a backend (path-3; loses MC semantics), Dockge/MCSManager plugins (path-4; the surfaces don't exist or are insufficient). See [`../research/2026-04-26-minecraft-and-docker-control-panels/`](../research/2026-04-26-minecraft-and-docker-control-panels/README.md) for the full landscape.

Trade-off: we own the UI, the ops loop, and any feature parity with richer panels. We get scope-fit (single host, six servers, MC-only) and zero upstream-fork risk.

## 005. Single-host scope

**Status:** Proposed · 2026-04-26

`mcontrol` targets a single host (`bserver`). No multi-node, no agent-on-other-hosts, no remote daemon protocol.

Rejected: a Wings/Periphery-style panel + remote agent split. Useful at scale, unjustified at six servers on one box.

Trade-off: if Minecraft servers ever live on a second host, `mcontrol` will need a real architectural revisit (likely a new decision that supersedes this one) rather than an incremental extension. Accepted as a future-`mcontrol` problem; today's value comes from being uncomplicated.

## 006. Inherit Docker-socket access from `admin_management`

**Status:** Proposed · 2026-04-26

The panel container mounts `/var/run/docker.sock` and the host's Minecraft directory (`/home/abstract/servers/minecraft → /mc-servers`), the same shape `admin-dashboard` already runs in production.

Rejected: a privilege-less alternative (Docker API over TCP+TLS, rootless socket-proxy, etc.). The project is single-host and tailnet-only; the socket is already trusted to the existing dashboard, and `mcontrol` doesn't change that trust model.

Trade-off: the panel container is effectively root-equivalent on the host. Compensated by the tailnet-only access posture (decision 003) and the lack of multi-tenant ambitions.

## 007. Postgres 17 as backing store

**Status:** Proposed · 2026-04-26

`mcontrol` uses PostgreSQL 17 for persistent state, matching the database `admin_management` already runs.

Rejected: SQLite. Would simplify deploy, but breaks symmetry with the sibling project and forecloses moving load to Postgres later if needed. A second store on the same host adds little value.

Trade-off: a PG dependency on a single-host project is heavier than strictly needed. Justified by reuse of the existing operational story (backups, upgrades, monitoring).

## 008. Bind mounts (not named volumes) for server data

**Status:** Proposed · 2026-04-26

Each server's data directory lives at `/home/abstract/servers/minecraft/<name>/server/` on the host and is bind-mounted into the container at `/data`. Named Docker volumes are not used for server data.

Rejected: named volumes. They'd be opaque (`docker volume inspect` to find files), complicate host-side backups, and break the existing pattern the user already operates and reasons about.

Trade-off: bind mounts are less portable across hosts (decision 005 already says single-host, so this is fine). UID/GID alignment between container and host has to stay disciplined; misaligned ownership is the recurring failure mode.

## 009. Per-server Docker `mem_limit`

**Status:** Proposed · 2026-04-26

Every server's compose file declares an explicit `mem_limit` sized at JVM `-Xmx` plus a margin for off-heap (~1–2 GB headroom; exact margin per server). Without it, a runaway modpack JVM can starve neighbours — `monifactory` exiting 137 (OOM) on bserver is the local instance of this failure mode.

Rejected: relying on JVM `-Xmx` alone. `-Xmx` controls heap; off-heap (Metaspace, direct buffers, JIT, native libs) sits outside it, and the OOM killer treats the whole cgroup the same way.

Trade-off: hitting the cgroup limit kills the container abruptly. Still better than a noisy-neighbour blast radius across the host; Docker restart policy + explicit alerts cover the recovery loop.

## 010. Rotate hardcoded `RCON_PASSWORD`

**Status:** Proposed · 2026-04-26

The bserver pattern hard-codes `RCON_PASSWORD="rconer"` in every compose file. `mcontrol` will rotate this to a per-server random secret, sourced from an environment file that is not committed. RCON stays bound to loopback by default — the password is defence-in-depth, not the primary control.

Rejected: leaving the value as-is. Today RCON is loopback-only and the risk is low, but the hardcoded value across every server is a credential-rotation hazard the moment any port mapping changes.

Trade-off: per-server secret management adds a small amount of bookkeeping. Standard `.env` + `.gitignore` + a regenerate-on-rotate script handles it.

## 011. Panel auth model

**Status:** Open · 2026-04-26

Whether `mcontrol`'s UI requires app-level login at all, or whether tailnet membership (decision 003) is the entire auth story.

Tension: tailnet-as-auth is the simplest correct answer for a single-user panel and matches the deployment posture, but any future need to share access with someone who has a tailnet account but shouldn't reach `mcontrol` (e.g. a guest device) would need an additional layer. No decision today; revisit when the second-user case is real.

## 012. Modpack workflow

**Status:** Open · 2026-04-26

How `mcontrol` handles Forge / Fabric / NeoForge / Modrinth modpacks now that we're not using itzg's `TYPE=` selectors (decision 001).

Candidates: (a) **manual import** — user drops a server directory in place, `mcontrol` discovers it; (b) **templated `start_server.sh` per loader**, with a thin install step `mcontrol` runs once; (c) **borrow the loader-install stage from a Pterodactyl egg** (overlaps decision 013). The bserver inventory already exhibits manual-import behaviour for the existing modpack servers; it's the cheapest starting point and probably the right one for v1, but the decision is open until the first new modpack is added through `mcontrol`.

## 013. Egg JSON schema borrowing

**Status:** Open · 2026-04-26

Whether to borrow the Pterodactyl egg JSON shape — Variables (with validation), Configuration Files (parsers for properties/YAML/JSON), `{{VARIABLE_NAME}}` substitution, "done" marker — as a portable schema for `mcontrol`'s own variables and config-file templating.

Tension: eggs are a well-trodden schema with two existing ecosystems (Pterodactyl + pelican-eggs); borrowing the schema costs little and gives a possible import/export path. But shipping an egg-shaped engine when there are six servers and no other consumers is over-engineering. Likely answer is "borrow the variable + config-file shape, skip the install scripts and Docker bits" — but explicitly Open until decision 012 and the v1 server-creation flow are sketched.

## 014. Convert existing itzg-based servers to temurin

**Status:** Open · 2026-04-26

Decision 001 mandates `eclipse-temurin:21-jre` for new servers. The existing bserver inventory has `atm10` and `monifactory` on `itzg/minecraft-server:java21` (with the entrypoint overridden anyway, per the research) and `kobra_kollektivet` already on temurin.

Both itzg-based servers are non-running today (`atm10` never started, `monifactory` exited 137 OOM), so the migration cost is essentially "rebuild the image." Open until `mcontrol` is in a state to actually run them, at which point the answer is almost certainly "yes, convert" — but recording the open question rather than acting on it ahead of need.
