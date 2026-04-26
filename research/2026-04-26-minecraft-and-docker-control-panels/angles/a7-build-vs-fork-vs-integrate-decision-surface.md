# Angle a7: Build-vs-fork-vs-integrate decision surface

**Question:** Given a1–a6, what are the concrete strategic options for mcontrol (fork Pterodactyl/Pelican, build a Dockge plugin, wrap itzg/minecraft-server with a thin custom UI, contribute upstream to Crafty, integrate via Portainer's API), and what are the trade-offs of each on the axes of scope-fit, maintenance burden, and differentiation?
**Why it matters:** This is the actual decision the research must inform — without it, the survey is academic.
**Boundaries:** Does NOT re-describe the panels themselves; assumes a1–a6 as input and only synthesizes the strategic recommendation surface.

---

I have plenty of verified data. Let me now compile the angle output.

## Angle: Build-vs-fork-vs-integrate decision surface

### Claims (with citations)

**1. Portainer exposes a per-user, RESTful API that can act as a gateway to the underlying Docker/Kubernetes API — meaning a third-party UI like mcontrol could plausibly use Portainer purely as an orchestration backend and never touch its UI.** Portainer's API "follows the RESTful architecture" and supports `GET/POST/PUT/DELETE`, with each user's API access scoped to that user's UI permissions; tokens are passed via the `X-API-Key` header [src:https://docs.portainer.io/api/access | authority:primary]. Documentation explicitly frames the API as "a gateway (HTTP queries against the Portainer API) to the underlying Docker/Kubernetes API" [src:https://docs.portainer.io/api/examples | authority:primary].

**2. However, integrating *through* Portainer carries a known feature-parity caveat: stacks created via API may not be fully editable in the Portainer UI afterward.** The Portainer GitHub issue tracker contains a long-standing "Control over this stack is limited" report where API-created Swarm stacks couldn't subsequently be edited in the UI; the issue was labeled `unable-to-reproduce` and went stale, but never resolved [src:https://github.com/portainer/portainer/issues/6481 | authority:primary]. This implies that mcontrol-as-Portainer-frontend would either need to render a parallel UI for everything or accept a degraded mixed-mode experience.

**3. Pterodactyl's primary documented extension target is the egg system — JSON templates declaring Docker image, startup command, configurable variables, and config-file parsers — which is the supported way to add new server types without forking the panel.** An egg JSON includes Configuration Files (parsers for YAML/JSON/properties/XML), Start Configuration, and Variables with validation and permission controls; "the Daemon will process this block prior to booting the server to ensure all of the required settings are defined and set correctly" [src:https://pterodactyl.io/community/config/eggs/creating_a_custom_egg.html | authority:primary]. For mcontrol this means: building on Pterodactyl can be done as "ship an egg" without touching panel source — minimal maintenance, but also minimal differentiation since you inherit Pterodactyl's UI.

**4. Beyond eggs, the de-facto extension framework for Pterodactyl is the third-party Blueprint, which is actively maintained and provides true extension APIs, HTML injection, and stylesheet modification.** Blueprint is "an open-source extension framework/manager for Pterodactyl"; CLI is Bash, backend is PHP/Laravel, frontend is React/TypeScript and Blade [src:https://github.com/BlueprintFramework/framework | authority:primary]. The repo shows 1,853 commits, 523 stars, and a release tagged `beta-2026-01` from January 16, 2026 — i.e. still active [src:https://github.com/BlueprintFramework/framework | authority:primary]. The trade-off: Blueprint extensions work by patching Pterodactyl files, which is exactly the brittle-coupling pattern Pelican was designed to escape (see claim 5).

**5. Pelican is a fork of Pterodactyl that explicitly built a "real" first-party plugin system (released in beta30) where plugins don't touch core files — but its design choices broke compatibility with Blueprint, and the Blueprint maintainer has declined to support it.** Pelican's FAQ states the plugin system is real (vs. core-file mods) and that "Blueprint extensions are not compatible with Pelican"; the Blueprint creator "stated they lack capacity to support multiple Pterodactyl forks" [src:https://pelican.dev/faq/ | authority:primary]. Pelican is AGPL-3.0 and shows 2k stars, 6,566 commits, with a recent release `v1.0.0-beta33` from February 18, 2026 [src:https://github.com/pelican-dev/panel | authority:primary]. Implication for mcontrol: Pelican is the cleaner *future* target for a plugin (no patching), but its plugin ecosystem is younger and smaller than Blueprint's; it also relicensed to AGPL-3.0 which has copyleft implications for any panel modifications you publish.

**6. There are already multiple competing Pterodactyl forks (Pelican, Pyrodactyl), which is a market signal that "fork Pterodactyl" is a crowded strategic position.** Pyrodactyl explicitly positions against Pelican: "the Pterodactyl-based game server panel that's faster, smaller, safer, and more accessible than Pelican," with claims of "over 170 times smaller" downloads and "over 16 times faster" load times; v4.5.0 was released October 28, 2025 with 903 stars and 6,211 commits [src:https://github.com/pyrohost/pyrodactyl | authority:primary]. For mcontrol this means a "yet another fork" play has to compete with two other actively-developed forks, not just Pterodactyl itself.

**7. Dockge's design is deliberately minimal and explicitly *not* a Portainer replacement — it owns no plugin/REST API surface, but its "compose files live on disk in a folder" philosophy makes filesystem-level integration trivial.** Maintainer states "Dockge won't kidnap your compose files, they are stored on your drive as usual. You can interact with them using normal `docker compose` commands" [src:https://dockge.kuma.pet/ | authority:primary]. Dockge "is currently only focusing on docker-compose with a better user interface" and explicitly excludes Docker network management and single-container operations [src:https://github.com/louislam/dockge | authority:primary, via project README/FAQ]. There is no documented REST API; communication is web UI plus WebSocket/Socket.IO [src:https://github.com/louislam/dockge | authority:primary]. Implication: mcontrol cannot build a "Dockge plugin" in any conventional sense — but it *can* trivially co-exist by writing compose files into Dockge's stacks directory, since Dockge will then surface and manage them.

**8. Dockge's host-path-equals-container-path requirement constrains any co-located deployment.** The maintainer explains in discussion #146 that Docker Compose resolves relative volume paths against the stacks directory, and since the daemon runs on the host, the host and container paths for that directory must match or volumes land in unexpected locations [src:https://github.com/louislam/dockge/discussions/146 | authority:primary]. Implication: an mcontrol-writes-compose-files-for-Dockge integration must pin a single canonical stacks path, limiting deployment flexibility.

**9. Crafty Controller exposes a documented v2 REST API behind bearer-token auth, intended for third-party automation; this is the "integrate with Crafty" surface.** "A valid token passed via the Authorization HTTP header is required for every single endpoint except `/api/v2/login`, `/api/v2` and `/api/v2/jsonschema/*`"; documented endpoints include `POST /api/v2/users`, `GET /api/v2/servers/{server_id}/stats`, `GET /api/v2/crafty/stats`, `PATCH /api/v2/servers/{server_id}` [src:https://wiki.craftycontrol.com/en/4/docs/API%20V2 | authority:primary, via search-result excerpts of the official wiki]. Crafty also documents "Server Webhooks" and Prometheus open-metrics for event-driven and observability integration [src:https://docs.craftycontrol.com/ | authority:primary]. Trade-off: Crafty's API is well-suited to *complementary* tools (dashboards, bots, CI), but Crafty itself is a UI — mcontrol-as-Crafty-frontend would be redundant.

**10. MCSManager publishes an HTTP API keyed per-user but has *no documented plugin/extension architecture* — meaning the only integration shape is "external tool calls API," not "extend the panel."** The official docs describe Instance, Dashboard, Users, Files, and Images APIs; "If you are an admin account, your API key will also have admin privileges" [src:https://docs.mcsmanager.com/apis/get_apikey.html | authority:primary]. No plugin/extension architecture is documented [src:https://docs.mcsmanager.com/apis/get_apikey.html | authority:primary]. Implication: MCSManager is integration-friendly but not extension-friendly — you cannot ship "an mcontrol plugin for MCSManager."

**11. itzg/minecraft-server is at internet-scale adoption (100M+ Docker Hub pulls) and has 80+ documented env vars, but the documentation explicitly disclaims that the variables reference page may be out-of-date and the repo offers no formal stability commitment.** Docker Hub shows "100M+" pulls, with 554,318 pulls in a single week [src:https://hub.docker.com/r/itzg/minecraft-server | authority:primary]. The project has 13.6k GitHub stars, 1.9k forks, 139 releases, latest April 2026 [src:https://github.com/itzg/docker-minecraft-server | authority:primary]. The variables page itself warns: "The variables listed on this page are manually documented and may be out-of-date or inaccurate" — though one example (`ENABLE_ROLLING_LOGS`) is explicitly "maintained for backward compatibility" [src:https://docker-minecraft-server.readthedocs.io/en/latest/variables/ | authority:primary]. Implication: a thin mcontrol UI over itzg/minecraft-server inherits enormous user familiarity and a battle-tested image, but any contract is *de facto* (community expectation), not *de jure* (maintainer-promised) — mitigation is automated env-var schema testing in CI.

**12. The egg format itself is a portable asset across the Pterodactyl-fork ecosystem: pelican-eggs preserves the egg JSON shape and migration path.** The pelican-eggs repository was archived May 14, 2024 to facilitate integration with the Pelican Panel Egg System, with contents migrated into category-specific repos (Minecraft, Database, Games, etc.); the original repo carried 3,921 commits, 3.1k stars, 2.2k forks [src:https://github.com/pelican-eggs/eggs | authority:primary]. Implication: shipping mcontrol as "an egg" (or set of eggs) is the lowest-effort distribution path that *automatically* covers Pterodactyl, Pelican, and Pyrodactyl users without per-fork engineering.

### Tradeoffs / counter-evidence found

- **Fork Pterodactyl/Pelican (high differentiation, high maintenance):** Pelican has a clean plugin architecture but small ecosystem; Blueprint has the ecosystem but works against Pterodactyl, not Pelican; Pyrodactyl proves multiple competing forks already exist, raising the bar for "another fork" to justify itself [Claims 5, 6].
- **Build a Dockge plugin (not really possible):** Dockge has no plugin API and no REST API — only a web UI and WebSockets; the only "integration" is filesystem co-location, which inherits Dockge's host-path constraint [Claims 7, 8].
- **Wrap itzg/minecraft-server with thin custom UI (lowest scope-fit risk, contract risk):** Massive adoption (100M+ pulls) means env-var changes are *socially* expensive for the maintainer to make, but there is no formal compatibility contract, and the variables-reference page itself is disclaimed as possibly stale [Claim 11].
- **Contribute upstream to Crafty (integrate-as-API-consumer, not as-plugin):** Crafty's API is the integration surface, but Crafty *itself is already a panel* — building "on top of" Crafty competes with Crafty rather than extending it; webhooks/Prometheus suggest Crafty's authors envision *complementary* tools (dashboards, alerting), not replacement UIs [Claim 9].
- **Integrate via Portainer API (broad reach, parity caveat):** Portainer's API can drive stacks programmatically, but the long-standing "API-created stacks have limited UI control" issue [Claim 2] means a hybrid mcontrol+Portainer experience could be confusing; pure API mode (mcontrol owns the UI, Portainer is invisible backend) sidesteps this but loses Portainer's value-add.
- **Ship as a Pterodactyl/Pelican egg (lowest maintenance, near-zero differentiation):** Eggs are portable across forks via the pelican-eggs migration model [Claim 12], but you inherit the host panel's UI entirely — mcontrol has no place to express its own opinions on UX.

### Gaps (no source found)

- **MCSManager plugin story:** Confirmed *negative* (no documented plugin architecture per official docs), but it's possible an undocumented mod community exists in the Chinese-language ecosystem that wasn't surfaced by English-language searches.
- **Pelican plugin catalog size and quality:** Confirmed the plugin system exists (beta30+) but I did not find a verified catalog/marketplace count to compare against Blueprint's ecosystem size.
- **Crafty contribution velocity / acceptance criteria for upstream PRs:** No primary source verified on whether Crafty welcomes large feature contributions from outside the core team.
- **itzg/minecraft-server stated SLA on env-var deprecation:** Found one example of legacy support (`ENABLE_ROLLING_LOGS`) but no maintainer-published deprecation policy.
- **Pyrodactyl plugin/extension story:** Pyrodactyl was confirmed as an active fork but I did not verify whether it has its own plugin system, inherits Blueprint, or aligns with Pelican's plugin model.

### Raw sources consulted

- https://docs.portainer.io/api/access (primary — Portainer official docs)
- https://docs.portainer.io/api/docs (primary — Portainer official docs)
- https://docs.portainer.io/api/examples (primary — Portainer official docs)
- https://github.com/portainer/portainer/issues/6481 (primary — Portainer issue tracker)
- https://pterodactyl.io/community/config/eggs/creating_a_custom_egg.html (primary — Pterodactyl official docs)
- https://github.com/BlueprintFramework/framework (primary — Blueprint repo)
- https://pelican.dev/faq/ (primary — Pelican official FAQ)
- https://github.com/pelican-dev/panel (primary — Pelican repo)
- https://github.com/pelican-eggs/eggs (primary — Pelican-eggs repo)
- https://github.com/pyrohost/pyrodactyl (primary — Pyrodactyl repo)
- https://github.com/louislam/dockge (primary — Dockge repo)
- https://dockge.kuma.pet/ (primary — Dockge official site)
- https://github.com/louislam/dockge/discussions/146 (primary — maintainer comments)
- https://wiki.craftycontrol.com/en/4/docs/API%20V2 (primary — Crafty wiki, accessed via search-result excerpts after the URL 301-redirected on direct fetch)
- https://docs.craftycontrol.com/ (primary — Crafty official docs)
- https://docs.mcsmanager.com/apis/get_apikey.html (primary — MCSManager official docs)
- https://docker-minecraft-server.readthedocs.io/en/latest/variables/ (primary — itzg official docs)
- https://github.com/itzg/docker-minecraft-server (primary — itzg repo)
- https://hub.docker.com/r/itzg/minecraft-server (primary — Docker Hub)
agentId: aafc500dc953cc0e2 (use SendMessage with to: 'aafc500dc953cc0e2' to continue this agent)
<usage>total_tokens: 44321
tool_uses: 33
duration_ms: 210268</usage>