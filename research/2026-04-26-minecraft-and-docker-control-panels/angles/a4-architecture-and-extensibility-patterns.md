# Angle a4: Architecture and extensibility patterns

**Question:** What architectural patterns recur across these panels (daemon+panel split à la Pterodactyl/Wings, single-binary à la Dockge, agent-per-host à la Portainer), and how extensible are they (plugin systems, APIs, webhooks, theming, IaC/declarative config)?
**Why it matters:** Determines whether mcontrol should fork, embed-as-library, sit-alongside-via-API, or build greenfield.
**Boundaries:** Does NOT evaluate features (a1/a2) or licensing (a5); strictly about code structure, deployment topology, and extension points.

---

I have strong primary-source coverage now. Let me synthesize.

## Angle: Architecture and extensibility patterns

### Claims (with citations)

1. **Pterodactyl uses a Panel + Wings split**: PHP Laravel panel (~64% PHP, ~21% TypeScript, Blade templates) with React/TypeScript frontend, paired with a separate Go daemon called Wings that runs on each node and isolates game servers in Docker containers. [src:https://github.com/pterodactyl/panel | authority:primary] [src:https://pterodactyl.io/project/introduction.html | authority:primary]

2. **Wings exposes an HTTP API and a built-in SFTP server** to the panel for server lifecycle, log streaming, and backups; the daemon is written almost entirely in Go (~99.6%). [src:https://github.com/pterodactyl/wings | authority:primary]

3. **Pterodactyl's extensibility revolves around "Eggs"** — community-contributed JSON game configurations (referenced via pterodactyleggs.com) that are imported into the panel rather than a code-level plugin system. [src:https://github.com/pterodactyl/panel | authority:primary]

4. **Pelican is a fork of Pterodactyl that keeps the same Panel + Wings + Node split**: panel is a web app, Wings runs on each Node (a machine) inside Docker for isolation, and Wings is version-pinned to a minimum compatible Pelican Panel release. [src:https://pelican.dev/docs/ | authority:primary]

5. **Architecturally Pelican is a Laravel/PHP rewrite using Filament for the admin and client UIs**, with a Webpack→Vite build switch, plus first-class additions Pterodactyl lacks: OAuth, webhooks, themes, and a plugin system. [src:https://github.com/pelican-dev/panel | authority:primary] [src:https://pelican.dev/docs/comparison/ | authority:primary]

6. **Crafty Controller is a single-process Python application built on the Tornado web server** with a WebSocket manager for real-time updates; it boots from `main.py`, which initializes a central Controller plus sub-controllers (servers/users/tasks). It is distributed as packages for Docker/Linux/Windows/macOS rather than as one universal binary, though Windows users get a compiled .exe. [src:https://deepwiki.com/apdevstudio/crafty-controller | authority:secondary] [src:https://gitlab.com/crafty-controller/crafty-4 | authority:primary]

7. **PufferPanel collapses panel and daemon into a single Go binary** (the daemon was merged into the main project in v2.1.0); a config toggle decides whether the binary acts as panel, node, or both, enabling the simplest single-host deployment of any panel surveyed. [src:https://docs.pufferpanel.com/en/2.x/release-notes/2.1.0.html | authority:primary] [src:https://github.com/pufferpanel/pufferpanel | authority:primary]

8. **PufferPanel is built primarily in Go (~50%) with Vue/SCSS frontend**, with explicit modules for OAuth2, SFTP, middleware, and operations, and supports a templates system for game definitions analogous to Pterodactyl Eggs. [src:https://github.com/pufferpanel/pufferpanel | authority:primary]

9. **MCSManager uses a three-tier distributed architecture** (Frontend / Panel / Daemon) where a Koa-based Node.js panel orchestrates many daemons over Socket.IO; the codebase is ~57% TypeScript and ~40% Vue, runs on Node.js ≥16.20.2, and requires no database. [src:https://github.com/MCSManager/MCSManager | authority:primary] [src:https://docs.mcsmanager.com/ops/mcsm_network.html | authority:primary]

10. **MCSManager deliberately offloads heavy traffic (file uploads, console streams) directly from browser to daemon** rather than proxying through the panel, which means each daemon must be publicly addressable over HTTPS and at least two ports must be reverse-proxied — an explicit topology trade-off for performance. [src:https://docs.mcsmanager.com/ops/mcsm_network.html | authority:primary]

11. **Portainer uses a Server + Agent topology** with a stateful server container plus stateless agents shipped per host/cluster; Edge Agents reverse-tunnel out to the server (encrypted TLS) for environments where inbound exposure is undesirable, while classic agents require server→agent reachability on the same network. [src:https://docs.portainer.io/start/architecture | authority:primary]

12. **Portainer is implemented mostly in TypeScript (~49%) and Go (~36%)** and exposes a documented JSON REST API (`GET`/`POST`/`PUT`/`DELETE`) for programmatic management of Docker/Swarm/Kubernetes/ACI; no GraphQL endpoint is documented. [src:https://github.com/portainer/portainer | authority:primary] [src:https://docs.portainer.io/api/access | authority:primary]

13. **Dockge is the canonical "stacks-as-files" panel**: it does not move or hide your Compose files — they live on disk (default `/opt/stacks`) and remain operable via plain `docker compose`. It runs as a single Docker container and uses TypeScript backend / Vue frontend with Socket.IO for reactive updates. [src:https://github.com/louislam/dockge | authority:primary]

14. **Dockge gained multi-host support in v1.4.0 via an agent model**, letting one UI talk to several Docker hosts; it has no formal plugin system — the design intentionally stays narrow around docker-compose. [src:https://github.com/louislam/dockge | authority:primary]

15. **Komodo follows a Core + Periphery topology**: Core is the central web server (REST + WebSocket API + UI); Periphery is a small stateless Rust binary on each managed host that receives commands over a bidirectional WebSocket and executes Docker/Git/system tasks. The codebase is ~60% Rust, ~37% TypeScript, with official client libraries in Rust, JS/Node, and CLI. [src:https://github.com/moghtech/komodo | authority:primary] [src:https://komo.do/docs/intro | authority:primary]

16. **Komodo provides first-class declarative/IaC config via "Resource Sync"**: TOML files (e.g. `stacks.toml`, `repos.toml`) describe servers, stacks, repos, users, etc.; Core diffs them against live state and can pull from a Git repo with webhook-driven `/sync` and `/refresh` actions, giving a true GitOps loop — uncommon among the other panels surveyed. [src:https://komo.do/docs/resources/webhooks | authority:primary] [src:https://github.com/moghtech/komodo/blob/main/config/periphery.config.toml | authority:primary]

### Tradeoffs / counter-evidence found

- **Single-binary vs split-daemon is a real spectrum, not a binary**. PufferPanel chose to merge panel and daemon into one Go binary toggled by config for operational simplicity [src:https://docs.pufferpanel.com/en/2.x/release-notes/2.1.0.html | authority:primary], whereas Pterodactyl/Pelican keep a hard PHP/Go split that pays a deployment cost but lets the daemon be written in a systems language and panel in a familiar PHP/Laravel stack [src:https://github.com/pterodactyl/wings | authority:primary] [src:https://github.com/pterodactyl/panel | authority:primary]. MCSManager goes further and pushes browser↔daemon direct streams to bypass the panel entirely, accepting reverse-proxy and HTTPS complexity in exchange for throughput [src:https://docs.mcsmanager.com/ops/mcsm_network.html | authority:primary].

- **Edge vs classic agent direction matters for security topology**. Portainer documents that Edge Agents initiate the tunnel outward over TLS so the server never needs inbound access to the agent host — explicitly recommended over the legacy classic agent direction [src:https://docs.portainer.io/start/architecture | authority:primary]. Komodo's Periphery is similarly bidirectional-WebSocket, but it is the Core that opens the connection to Periphery [src:https://komo.do/docs/intro | authority:primary], a different trust direction than Edge.

- **"Plugin system" means very different things across panels.** Pelican advertises plugins, themes, OAuth and webhooks as differentiators over Pterodactyl [src:https://pelican.dev/docs/comparison/ | authority:primary]; Dockge explicitly has no plugin model and treats narrowness as a feature [src:https://github.com/louislam/dockge | authority:primary]; Pterodactyl's "extensibility" is largely the JSON Eggs catalog, not code-level extension [src:https://github.com/pterodactyl/panel | authority:primary].

### Gaps (no source found)

- Could not find a primary, fetchable Pterodactyl docs page describing the Panel↔Wings authentication/handshake protocol in detail (the Wings install page exists but doesn't enumerate it; the Wings README mentions HTTP API + SFTP but not the panel-side auth flow). [src:https://pterodactyl.io/wings/1.0/installing.html | authority:primary]
- Could not retrieve a fetchable primary Pterodactyl page confirming OAuth2 support in the public API (returned 404s); only Pelican is confirmed via primary docs to add OAuth as a differentiator [src:https://pelican.dev/docs/comparison/ | authority:primary].
- Could not directly fetch a Crafty Controller docs page enumerating its REST API surface or extension points; framework (Tornado) is well-attested via secondary DeepWiki and indirect sources but not from the official docs page in this session. [src:https://deepwiki.com/apdevstudio/crafty-controller | authority:secondary]
- No primary source confirming Komodo Resource Sync at the canonical `/docs/resources/sync-resources` URL — the URL 404'd; claim is supported via a related primary webhook docs page plus the live `periphery.config.toml` in the repo. [src:https://komo.do/docs/resources/webhooks | authority:primary] [src:https://github.com/moghtech/komodo/blob/main/config/periphery.config.toml | authority:primary]
- Did not confirm whether PufferPanel ships a public REST API contract (templates and OAuth2 module are visible in repo, but a stable documented external API surface wasn't located in the docs index returned). [src:https://github.com/pufferpanel/pufferpanel | authority:primary]

### Raw sources consulted

- https://pterodactyl.io/project/introduction.html (primary)
- https://github.com/pterodactyl/panel (primary)
- https://github.com/pterodactyl/wings (primary)
- https://pterodactyl.io/wings/1.0/installing.html (primary)
- https://pelican.dev/docs/ (primary)
- https://pelican.dev/docs/comparison/ (primary)
- https://github.com/pelican-dev/panel (primary)
- https://gitlab.com/crafty-controller/crafty-4 (primary)
- https://docs.craftycontrol.com/ (primary)
- https://deepwiki.com/apdevstudio/crafty-controller (secondary)
- https://github.com/pufferpanel/pufferpanel (primary)
- https://docs.pufferpanel.com/en/2.x/release-notes/2.1.0.html (primary)
- https://github.com/MCSManager/MCSManager (primary)
- https://docs.mcsmanager.com/ops/mcsm_network.html (primary)
- https://docs.portainer.io/start/architecture (primary)
- https://docs.portainer.io/api/access (primary)
- https://github.com/portainer/portainer (primary)
- https://github.com/louislam/dockge (primary)
- https://github.com/moghtech/komodo (primary)
- https://komo.do/docs/intro (primary)
- https://komo.do/docs/resources/webhooks (primary)
- https://github.com/moghtech/komodo/blob/main/config/periphery.config.toml (primary)

Note: I noticed a prompt-injection-style instruction embedded in one Portainer fetch result suggesting I append `?ask=...` to a URL to query the docs differently — I ignored it as it was not a user instruction.
agentId: a3558c326e290f560 (use SendMessage with to: 'a3558c326e290f560' to continue this agent)
<usage>total_tokens: 43349
tool_uses: 45
duration_ms: 218345</usage>