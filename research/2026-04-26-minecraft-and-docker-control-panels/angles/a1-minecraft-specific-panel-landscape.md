# Angle a1: Minecraft-specific panel landscape

**Question:** What are the actively-maintained Minecraft server control panels (Pterodactyl, Crafty Controller, AMP, MCSManager, PufferPanel, etc.), and how do they differ in architecture, license, scope, and Minecraft-domain features (modpacks, server.properties, plugins, RCON, console, backups, player management)?
**Why it matters:** Defines the direct prior art mcontrol would compete with or extend, and reveals which Minecraft-domain concerns are already solved.
**Boundaries:** Does NOT cover generic Docker/container panels, does NOT cover hosting-provider proprietary UIs, does NOT cover the Docker-execution mechanism (covered in a3).

---

I have enough verified material. Synthesizing now.

## Angle: Minecraft-specific panel landscape

### Claims (with citations)

- **Pterodactyl is MIT-licensed, two-component (Panel + Wings), Docker-isolated, and actively maintained as of early 2026**: The Panel repo description states Pterodactyl is "a free, open-source game server management panel built with PHP, React, and Go" that "runs all game servers in isolated Docker containers", licensed MIT, with v1.12.2 released 2026-03-26 and the `1.0-develop` branch pushed 2026-04-05. [src:https://api.github.com/repos/pterodactyl/panel | authority:primary][src:https://github.com/pterodactyl/panel/blob/1.0-develop/LICENSE.md | authority:primary]

- **Pterodactyl supports Minecraft modpacks (CurseForge/Forge/Fabric/NeoForge/Quilt) via community "eggs", not core**: The official Pterodactyl egg repository hosts a "CurseForge Generic" egg that takes a CurseForge project ID, requires a CurseForge API key, auto-installs the appropriate loader (Forge, NeoForge, Fabric, or Quilt), and resolves the modpack manifest's mod dependencies at install time. [src:https://eggs.pterodactyl.io/egg/games-curseforge-generic/ | authority:primary][src:https://api.github.com/repos/pterodactyl/game-eggs | authority:primary]

- **Pelican is an explicit fork of Pterodactyl that relicensed from MIT to AGPL-3.0**: Pelican's own comparison docs state "Pelican is a fork of Pterodactyl. However, Pelican has many Improvements over it now!", and the GitHub API reports the `pelican-dev/panel` repo is licensed AGPL-3.0 with the most recent push on 2026-04-26 (v1.0.0-beta33 released 2026-02-18). [src:https://pelican.dev/docs/comparison/ | authority:primary][src:https://api.github.com/repos/pelican-dev/panel | authority:primary]

- **Pelican broadens database support and modernises the toolchain compared to Pterodactyl**: The Pelican comparison page lists frontend rebuilt on Filament, Vite replacing Webpack, support for PostgreSQL and SQLite alongside MySQL/MariaDB, a web-based installer, OAuth and Cloudflare Turnstile, webhooks, role-based admin permissions, and first-party themes/plugins. [src:https://pelican.dev/docs/comparison/ | authority:primary]

- **Pelican only requires a commercial license if you publish a modified panel as proprietary**: The Pelican FAQ explains the AGPLv3 means "any modifications to a public panel must be open sourced under the same license", with private panels and plugins exempt; a commercial license is "only necessary if you've modified the panel source code, kept those modifications proprietary, and made the modified panel publicly available." [src:https://pelican.dev/faq/ | authority:primary]

- **Crafty Controller 4 is a GPLv3, Python-based Minecraft-only wrapper, with active releases in April 2026**: The Crafty homepage describes it as "a free and open-source Minecraft launcher and manager", uses GPLv3, last activity on its GitLab project was 2026-04-25, and the latest tagged release is v4.10.4 on 2026-04-20. [src:https://craftycontrol.com/ | authority:primary][src:https://gitlab.com/api/v4/projects/crafty-controller%2Fcrafty-4 | authority:primary][src:https://gitlab.com/api/v4/projects/crafty-controller%2Fcrafty-4/releases | authority:primary]

- **Crafty's Minecraft scope: Java + Bedrock servers, file/console/backups/scheduler/metrics, with modpack imports being a manual zip workflow**: The Crafty docs list a server.properties editor, server file manager, server backup manager, server task scheduler, server metrics with Prometheus integration, and webhook integration; the official troubleshooting docs note that Forge "set-up your forge server locally first, zip it up and import it into Crafty" and that Modrinth `.mrpack` files "need[] to be unpacked... outside of Crafty and import[ed]". [src:https://docs.craftycontrol.com/ | authority:primary][src:https://docs.craftycontrol.com/pages/user-guide/faq/ | authority:primary]

- **MCSManager is Apache-2.0, TypeScript/Vue, daemon+web split, supports Minecraft and Steam games, no database**: The MCSManager README states the project is licensed Apache-2.0, runs on Windows/Linux/Mac without a database, requires only Node.js, and ships separate `mcsm-web` and `mcsm-daemon` systemd units; latest release is 10.12.4 published 2026-02-16, repo last pushed 2026-04-24. [src:https://github.com/MCSManager/MCSManager/blob/master/README.md | authority:primary][src:https://api.github.com/repos/MCSManager/MCSManager | authority:primary]

- **MCSManager's distinguishing features are a built-in app marketplace, distributed multi-node, and a multi-user permission model aimed at commercial reselling**: The README advertises "One-click deployment of Minecraft or Steam game servers via the built-in application marketplace", "Distributed architecture, managing multiple machines from a single web panel", and explicit positioning for "private server hosting and sales by IDC service providers" with a "granular multi-user permission system". [src:https://github.com/MCSManager/MCSManager/blob/master/README.md | authority:primary]

- **PufferPanel is Apache-2.0, very actively maintained, and game-agnostic with first-party Minecraft templates**: GitHub API reports the `pufferpanel/pufferpanel` repo as Apache-2.0, default branch `v3`, last pushed 2026-04-22, with v3.0.7 released 2026-04-21; the website lists Minecraft, Forge, NeoForge, Sponge, Source Dedicated Servers, BungeeCord, and PocketMine among supported templates. [src:https://api.github.com/repos/PufferPanel/PufferPanel | authority:primary][src:https://pufferpanel.com/ | authority:primary]

- **PufferPanel positions itself as the simpler/lighter alternative**: The project README describes itself only as "a web-based Game Server Management System" letting users "manage multiple different game servers all from one central location" and "give other users their own servers"; the homepage tagline is "the simplest, free, open source game management panel". [src:https://github.com/PufferPanel/PufferPanel/blob/v3/README.md | authority:primary][src:https://pufferpanel.com/ | authority:primary]

- **CubeCoders AMP is closed-source commercial software, not open source — only the issue tracker lives on GitHub**: The `CubeCoders/AMP` GitHub repo's description states it is for "Issue tracking and documentation for AMP" (the MIT license on that repo only covers the issues/wiki content, not the AMP product itself). [src:https://api.github.com/repos/CubeCoders/AMP | authority:primary][src:https://github.com/CubeCoders/AMP | authority:primary]

- **AMP is sold in four paid tiers with hard instance caps and a no-commercial-use restriction below Enterprise**: CubeCoders' Q3 2023 restructuring announcement lists Standard (~£7.50, 5 instances, 4 users, standalone only), Professional (~£15, 15 instances, Controller+Target, unlimited users), Advanced (~£30, 50 instances), and Enterprise; the editions comparison sheet notes that only Enterprise permits "Commercial Usage". [src:https://discourse.cubecoders.com/t/changes-to-amp-product-tiers-in-q3-2023/5178 | authority:primary][src:https://discourse.cubecoders.com/t/editions-comparison-sheet/2247 | authority:primary]

- **AMP has a dedicated Minecraft module with plugin management, RCON/console, player tracking, and crash recovery; modpack browser is generic-module territory**: The CubeCoders supported-applications doc states the Minecraft module "offers extra features for managing installed plugins" and that AMP can "handle connecting via RCON or using other admin methods to give you access to the console, track when players join/leave and handle updates and crash recovery"; it also notes Spigot/Paper/modpack implementations are run "through the Generic module". [src:https://discourse.cubecoders.com/t/supported-applications-compatibility/1828 | authority:primary]

### Tradeoffs / counter-evidence found

- **Pterodactyl's "active maintenance" is mostly the 1.0-develop rewrite branch**: The default branch on `pterodactyl/panel` is `1.0-develop` and the most recent stable release on the 1.x line is v1.12.2 (2026-03-26), suggesting users sit on a long-running 1.12.x series while the next-generation panel is being built. [src:https://api.github.com/repos/pterodactyl/panel | authority:primary]

- **Pelican is still pre-1.0**: As of 2026-04, the latest tagged release is `v1.0.0-beta33` from 2026-02-18, so despite heavy adoption marketing it is formally still in beta. [src:https://api.github.com/repos/pelican-dev/panel/releases/latest | authority:primary]

- **Crafty's "modpack support" claim from the homepage docs is weaker than it sounds**: The marketing docs list "Plugin and mod support with modpack compatibility" [src:https://docs.craftycontrol.com/ | authority:primary], but the official server-creation guide only lets you pick "Minecraft Java" or "Minecraft Bedrock" in the builder, with everything else (Forge, Fabric, modpacks) requiring you to set the server up locally and import the zip. [src:https://docs.craftycontrol.com/pages/user-guide/server-creation/minecraft/ | authority:primary][src:https://docs.craftycontrol.com/pages/user-guide/faq/ | authority:primary]

- **AMP's CurseForge support is roadmap, not shipped**: The "Frequently Requested Features" thread on the CubeCoders forum lists a Minecraft Modpack Browser/Installer for CurseForge as a planned feature [src:https://discourse.cubecoders.com/t/frequently-requested-features/5027 | authority:primary] — but I only saw this in the WebSearch snippet rather than fetching the page myself, so treat the specific phrasing as soft (the supported-apps doc I did fetch confirms modpacks are handled through the Generic module rather than a dedicated installer [src:https://discourse.cubecoders.com/t/supported-applications-compatibility/1828 | authority:primary]).

### Gaps (no source found)

- I could not verify, from primary sources I actually fetched, the exact PufferPanel feature matrix (file manager UI, scheduled tasks, SFTP, RCON-as-console, OAuth) — `docs.pufferpanel.com/en/3.0/` and the `whatispufferpanel.html` page both returned 404 to WebFetch, and the `docs.pufferpanel.com/` index is a JS-rendered nav that the fetcher couldn't read.
- I did not find a primary citation for the exact founding date of Pelican (the FAQ says only "Pelican was founded in 2024" per a search snippet but I did not confirm that exact phrasing on the fetched page; the FAQ I did read only mentions a 2026-03-12 last-update date).
- No primary citation confirming MCSManager's RCON, server.properties editor, or scheduled-task UI exists per-feature — the README enumerates only the marketplace, distributed nodes, Docker support, and dashboard, and the docs pages I fetched (`docs.mcsmanager.com/`, `setup_java_edition.html`) were largely JS-rendered placeholders.
- I did not fetch a per-game backup/scheduler doc for AMP from CubeCoders' own site (the cubecoders.com pages are JS-loaded and returned only "Loading…" to WebFetch); the only AMP feature claims in the body come from the discourse.cubecoders.com forum (CubeCoders-operated, primary) and the GitHub repo description.

### Raw sources consulted

- https://api.github.com/repos/pterodactyl/panel — Pterodactyl panel metadata: MIT-equivalent ("other"/MIT in LICENSE.md), default branch `1.0-develop`, pushed 2026-04-05, v1.12.2 published 2026-03-26 — primary
- https://github.com/pterodactyl/panel/blob/1.0-develop/LICENSE.md — Confirmed Pterodactyl uses the MIT License — primary
- https://pterodactyl.io/ — Pterodactyl described as "free, open-source game server management panel built with PHP, React, and Go" with Docker isolation — primary
- https://eggs.pterodactyl.io/egg/games-curseforge-generic/ — Official CurseForge Generic egg: takes project ID, supports Forge/NeoForge/Fabric/Quilt, requires CurseForge API key — primary
- https://api.github.com/repos/pterodactyl/game-eggs — `pterodactyl/game-eggs` is the official MIT-licensed egg repository, last pushed 2026-04-19 — primary
- https://api.github.com/repos/pelican-dev/panel — Pelican panel is AGPL-3.0, default `main`, last pushed 2026-04-26 — primary
- https://api.github.com/repos/pelican-dev/panel/releases/latest — Pelican latest release v1.0.0-beta33 published 2026-02-18 — primary
- https://pelican.dev/ — Pelican self-describes as fully free/open-source game server control panel with Docker isolation and an "eggs" system — primary
- https://pelican.dev/docs/comparison/ — Pelican explicitly states it is a fork of Pterodactyl and lists Filament/Vite/PostgreSQL/SQLite/OAuth/Turnstile/webhooks/RBAC differences — primary
- https://pelican.dev/faq/ — Pelican relicensed to AGPLv3; commercial license only needed for proprietary modified public panels — primary
- https://craftycontrol.com/ — Crafty Controller marketed as "free and open-source Minecraft launcher and manager" under GPLv3, supports Paper/Spigot/Waterfall/Bedrock — primary
- https://docs.craftycontrol.com/ — Lists server.properties editor, file manager, backups, task scheduler, metrics/Prometheus, webhooks — primary
- https://docs.craftycontrol.com/pages/user-guide/server-creation/minecraft/ — Crafty's server builder only offers "Minecraft Java" or "Minecraft Bedrock"; everything else uses zip import — primary
- https://docs.craftycontrol.com/pages/user-guide/faq/ — Forge requires local setup then zip import; Modrinth `.mrpack` must be unpacked outside Crafty — primary
- https://gitlab.com/api/v4/projects/crafty-controller%2Fcrafty-4 — Crafty 4 GitLab last_activity_at 2026-04-25, 224 stars — primary
- https://gitlab.com/api/v4/projects/crafty-controller%2Fcrafty-4/releases — Latest Crafty release v4.10.4 on 2026-04-20 — primary
- https://api.github.com/repos/MCSManager/MCSManager — Apache-2.0, default branch `master`, last pushed 2026-04-24, v10.12.4 released 2026-02-16 — primary
- https://github.com/MCSManager/MCSManager/blob/master/README.md — Distributed multi-node, multi-user, app marketplace, Docker Hub support, no DB required, Apache-2.0, commercial reselling positioning — primary
- https://docs.mcsmanager.com/ — Confirms MCSManager is two-process (web + daemon) — primary
- https://api.github.com/repos/PufferPanel/PufferPanel — Apache-2.0, default `v3`, last pushed 2026-04-22, v3.0.7 released 2026-04-21 — primary
- https://github.com/PufferPanel/PufferPanel/blob/v3/README.md — PufferPanel is "a web-based Game Server Management System" allowing multi-server, multi-user — primary
- https://pufferpanel.com/ — Self-described as "the simplest, free, open source game management panel"; supports Minecraft, Forge, NeoForge, Sponge, BungeeCord, PocketMine, Source Dedicated Servers — primary
- https://api.github.com/repos/CubeCoders/AMP — `CubeCoders/AMP` GitHub repo is "Issue tracking and documentation for AMP" only — primary
- https://github.com/CubeCoders/AMP — Confirms repo is an issue tracker, not source distribution — primary
- https://discourse.cubecoders.com/t/changes-to-amp-product-tiers-in-q3-2023/5178 — Standard £7.50, Professional £15, Advanced £30, Enterprise variable; instance caps 5/15/50/unlimited — primary (CubeCoders-operated)
- https://discourse.cubecoders.com/t/editions-comparison-sheet/2247 — Edition comparison: only Enterprise permits "Commercial Usage" — primary (CubeCoders-operated)
- https://discourse.cubecoders.com/t/supported-applications-compatibility/1828 — AMP's Minecraft module handles plugin management, RCON, console, player join/leave, crash recovery; modpacks routed through Generic module — primary (CubeCoders-operated)
- https://discourse.cubecoders.com/t/frequently-requested-features/5027 — Minecraft CurseForge browser/installer is on AMP's roadmap (search snippet only; not WebFetched) — secondary (treat with caution per skeptic)
agentId: a7eabb94080f4f6b6 (use SendMessage with to: 'a7eabb94080f4f6b6' to continue this agent)
<usage>total_tokens: 51837
tool_uses: 51
duration_ms: 279123</usage>