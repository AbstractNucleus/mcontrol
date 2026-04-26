# Sources

Total verifier verdicts: 110; unique URLs: 110
Verifier counts: OK=73 WEAK=19 MISMATCH=7 DEAD=3 HALLUCINATED=0 (total=102)

| # | URL | Authority (claimed → actual) | Status | Evidence / note |
|---|-----|------------------------------|--------|-----------------|
| 1 | <https://api.github.com/repos/CubeCoders/AMP> | primary | WEAK | Repository exists but only contains issue tracking/documentation. The repo itself is MIT-licensed but does not contain AMP source code; AMP itself is closed-source |
| 2 | <https://api.github.com/repos/MCSManager/MCSManager> | primary | OK |  |
| 3 | <https://api.github.com/repos/PufferPanel/PufferPanel> | primary | OK |  |
| 4 | <https://api.github.com/repos/pelican-dev/panel> | primary | WEAK | API confirms AGPL-3.0 license but reports `"fork":false` — repository is not a GitHub fork even though Pelican is a code fork in spirit |
| 5 | <https://api.github.com/repos/pterodactyl/game-eggs> | primary | OK |  |
| 6 | <https://api.github.com/repos/pterodactyl/panel> | primary | OK |  |
| 7 | <https://blog.aflorzy.com/posts/setup-pelican-in-docker> | secondary | WEAK | Article discusses initial installation complexity ('quite intense') but does not address migration friction specifically |
| 8 | <https://craftycontrol.com/> | primary | OK |  |
| 9 | <https://deepwiki.com/apdevstudio/crafty-controller> | secondary | WEAK | Confirms Crafty uses Tornado web server but does not specify single-process configuration |
| 10 | <https://discourse.cubecoders.com/t/amp-is-not-for-me-gave-it-a-try-found-it-too-cumbersome-can-i-get-a-refund/4899> | primary | OK |  |
| 11 | <https://discourse.cubecoders.com/t/changes-to-amp-product-tiers-in-q3-2023/5178> | primary | WEAK | Confirms four tiers and instance caps, but does not specifically state only Enterprise is commercial — all tiers are paid commercial offerings on this page |
| 12 | <https://discourse.cubecoders.com/t/editions-comparison-sheet/2247> | primary | OK |  |
| 13 | <https://discourse.cubecoders.com/t/frequently-requested-features/5027> | primary | OK |  |
| 14 | <https://discourse.cubecoders.com/t/supported-applications-compatibility/1828> | primary | WEAK | Mentions plugin support but does not specifically confirm RCON, console, player tracking, or crash recovery features for the Minecraft module |
| 15 | <https://docker-minecraft-server.readthedocs.io/en/latest/> | primary | OK |  |
| 16 | <https://docker-minecraft-server.readthedocs.io/en/latest/configuration/server-properties/> | primary | OK |  |
| 17 | <https://docker-minecraft-server.readthedocs.io/en/latest/mods-and-plugins/> | primary | OK |  |
| 18 | <https://docker-minecraft-server.readthedocs.io/en/latest/sending-commands/commands/> | primary | OK |  |
| 19 | <https://docker-minecraft-server.readthedocs.io/en/latest/types-and-platforms/> | primary | OK |  |
| 20 | <https://docker-minecraft-server.readthedocs.io/en/latest/variables/> | primary | OK |  |
| 21 | <https://dockge.kuma.pet/> | primary → unknown | DEAD | HTTP 403 forbidden |
| 22 | <https://docs.craftycontrol.com/> | primary | WEAK | Confirms Bedrock, file manager, backup manager, metrics, scheduler. Does not explicitly mention server.properties editor or Forge zip-import on this page. |
| 23 | <https://docs.craftycontrol.com/pages/user-guide/faq/> | primary | OK |  |
| 24 | <https://docs.craftycontrol.com/pages/user-guide/server-creation/minecraft/> | primary | OK |  |
| 25 | <https://docs.mcsmanager.com/apis/get_apikey.html> | primary | OK |  |
| 26 | <https://docs.mcsmanager.com/ops/mcsm_network.html> | primary | OK |  |
| 27 | <https://docs.portainer.io/admin/user/roles> | primary | OK |  |
| 28 | <https://docs.portainer.io/api/access> | primary | WEAK | Confirms RESTful API with per-user access tokens, but does not address TS/Go implementation language |
| 29 | <https://docs.portainer.io/api/examples> | primary | OK |  |
| 30 | <https://docs.portainer.io/start/architecture> | primary | OK |  |
| 31 | <https://docs.pufferpanel.com/en/2.x/environments/docker.html> | primary | OK |  |
| 32 | <https://docs.pufferpanel.com/en/2.x/environments/standard.html> | primary | OK |  |
| 33 | <https://docs.pufferpanel.com/en/2.x/release-notes/2.1.0.html> | primary | OK |  |
| 34 | <https://docs.pufferpanel.com/en/3.x/release-notes/3.0.0.html> | primary | OK |  |
| 35 | <https://eggs.pterodactyl.io/egg/games-curseforge-generic/> | primary | OK |  |
| 36 | <https://eggs.pterodactyl.io/egg/games-paper/> | primary | OK |  |
| 37 | <https://forum.level1techs.com/t/amp-game-server-good-or-bad/231908> | tertiary | MISMATCH | Discussion contrasts AMP favorably with Pterodactyl. Users say AMP 'just works' and praise its documentation. Does not support 'cumbersome cryptic' characterization. |
| 38 | <https://forum.level1techs.com/t/minecraft-web-panel-recommendations/233819> | tertiary | OK |  |
| 39 | <https://github.com/BlueprintFramework/framework> | primary | OK |  |
| 40 | <https://github.com/CubeCoders/AMP> | primary | OK |  |
| 41 | <https://github.com/FinnAppel/Ptero-to-Pelican-Migration-Script> | secondary | OK |  |
| 42 | <https://github.com/MCSManager/MCSManager> | primary | WEAK | Confirms three-tier architecture and v10.12.4 latest, but does not explicitly mention Socket.IO as the protocol |
| 43 | <https://github.com/MCSManager/MCSManager/blob/master/LICENSE> | primary | OK |  |
| 44 | <https://github.com/MCSManager/MCSManager/blob/master/README.md> | primary | OK |  |
| 45 | <https://github.com/PufferPanel/PufferPanel> | primary | OK |  |
| 46 | <https://github.com/PufferPanel/PufferPanel/blob/master/LICENSE> | primary | OK |  |
| 47 | <https://github.com/PufferPanel/PufferPanel/blob/v3/README.md> | primary | MISMATCH | README does not use the word 'simplest'; it states PufferPanel 'provides an easy-to-use interface for everyone from individual users to large networks' |
| 48 | <https://github.com/SelfhostedPro/Yacht> | primary | OK |  |
| 49 | <https://github.com/SelfhostedPro/Yacht/blob/master/LICENSE.md> | primary | OK |  |
| 50 | <https://github.com/SelfhostedPro/Yacht/tags> | primary | OK |  |
| 51 | <https://github.com/community-scripts/ProxmoxVE/issues/13568> | primary | OK |  |
| 52 | <https://github.com/coollabsio/coolify/discussions/4215> | tertiary | MISMATCH | Discussion is a feature request to add Pterodactyl/Pelican to Coolify, not a comparison of futures or safety. Source does not support the comparative claim. |
| 53 | <https://github.com/itzg/docker-minecraft-server> | primary | OK |  |
| 54 | <https://github.com/itzg/docker-minecraft-server/blob/master/docker-compose.yml> | primary | OK |  |
| 55 | <https://github.com/itzg/docker-minecraft-server/discussions/3099> | primary | MISMATCH | Discussion is about autopause cycling every 10 minutes due to network pings, not about a Watchdog conflict |
| 56 | <https://github.com/itzg/docker-minecraft-server/issues/3261> | primary | OK |  |
| 57 | <https://github.com/jesseduffield/lazydocker> | primary | OK |  |
| 58 | <https://github.com/louislam/dockge> | primary | OK |  |
| 59 | <https://github.com/louislam/dockge/blob/master/LICENSE> | primary | OK |  |
| 60 | <https://github.com/louislam/dockge/discussions/146> | primary | OK |  |
| 61 | <https://github.com/louislam/dockge/releases> | primary | OK |  |
| 62 | <https://github.com/mbecker20/monitor/releases/tag/v1.13.0> | primary | OK |  |
| 63 | <https://github.com/moghtech/komodo> | primary | OK |  |
| 64 | <https://github.com/moghtech/komodo/blob/main/LICENSE> | primary | OK |  |
| 65 | <https://github.com/moghtech/komodo/blob/main/config/periphery.config.toml> | primary | OK |  |
| 66 | <https://github.com/moghtech/komodo/releases/latest> | primary | WEAK | Page confirms v2.1.2 but does not show language or license on the release page itself; those are on the main repo page |
| 67 | <https://github.com/pelican-dev/panel> | primary | OK |  |
| 68 | <https://github.com/pelican-dev/panel/discussions/13> | tertiary | WEAK | Discussion is about a migration tool with one user noting risk concerns, but does not directly frame Pelican as 'future' vs Pterodactyl as 'safe today' |
| 69 | <https://github.com/pelican-eggs/eggs> | primary | MISMATCH | Repository was archived May 2024 and content migrated into separate category-based repos. These are configuration files, not migration tools. |
| 70 | <https://github.com/portainer/portainer> | primary | OK |  |
| 71 | <https://github.com/portainer/portainer/blob/develop/LICENSE> | primary | OK |  |
| 72 | <https://github.com/portainer/portainer/issues/6481> | primary | OK |  |
| 73 | <https://github.com/portainer/portainer/releases/latest> | primary | OK |  |
| 74 | <https://github.com/pterodactyl/panel> | primary | WEAK | Page references Wings docs and Blueprint but does not clearly describe Panel+Wings architecture or claim eggs as the extensibility model |
| 75 | <https://github.com/pterodactyl/panel/blob/1.0-develop/LICENSE.md> | primary | OK |  |
| 76 | <https://github.com/pterodactyl/panel/blob/develop/LICENSE.md> | primary | OK |  |
| 77 | <https://github.com/pterodactyl/panel/issues/3040> | primary | OK |  |
| 78 | <https://github.com/pterodactyl/panel/issues/4447> | primary | OK |  |
| 79 | <https://github.com/pterodactyl/panel/issues/4850> | primary | OK |  |
| 80 | <https://github.com/pterodactyl/panel/issues/5063> | primary | OK |  |
| 81 | <https://github.com/pterodactyl/panel/releases/tag/v1.12.2> | primary | MISMATCH | Actual release date is March 26, 2026 (per GitHub API published_at: 2026-03-26T23:56:46Z), not 2024 as claimed |
| 82 | <https://github.com/pterodactyl/wings> | primary | OK |  |
| 83 | <https://github.com/pterodactyl/yolks> | primary | OK |  |
| 84 | <https://github.com/pufferpanel/pufferpanel> | primary | WEAK | Confirms ~50% Go and Vue/SCSS frontend mix, but contradicts 'single Go binary' since the project is multi-language full-stack with Vue/SCSS components |
| 85 | <https://github.com/pufferpanel/pufferpanel/issues/1439> | primary | OK |  |
| 86 | <https://github.com/pyrohost/pyrodactyl> | primary | OK |  |
| 87 | <https://gitlab.com/api/v4/projects/crafty-controller%2Fcrafty-4> | primary | OK |  |
| 88 | <https://gitlab.com/api/v4/projects/crafty-controller%2Fcrafty-4/releases> | primary | OK |  |
| 89 | <https://gitlab.com/crafty-controller/crafty-4> | primary | WEAK | Confirms Python language but does not mention Tornado or directly identify Arcadia Technology as developer (only references translate.arcadiatech.org) |
| 90 | <https://gitlab.com/crafty-controller/crafty-4/-/blob/master/LICENSE> | primary | OK |  |
| 91 | <https://hub.docker.com/r/itzg/minecraft-server> | primary | OK |  |
| 92 | <https://komo.do/docs/intro> | primary | OK |  |
| 93 | <https://komo.do/docs/resources/permissioning> | primary → unknown | DEAD | HTTP 404 |
| 94 | <https://komo.do/docs/resources/webhooks> | primary → unknown | DEAD | HTTP 404 |
| 95 | <https://komo.do/docs/setup/advanced> | primary | OK |  |
| 96 | <https://lowendspirit.com/discussion/9906/any-good-alternatives-to-pterodactyl> | tertiary | MISMATCH | Discussion shows opposite trend — practitioners commit to Pterodactyl: 'Pterodactyl is basically what the industry uses' and 'Pterodactyl is still the most popular' |
| 97 | <https://pelican.dev/docs/> | primary | WEAK | Page describes Panel + Wings architecture but does not mention a separate Node component |
| 98 | <https://pelican.dev/docs/about> | primary | OK |  |
| 99 | <https://pelican.dev/docs/comparison/> | primary | WEAK | Page confirms fork status and improvements (PostgreSQL, SQLite, Filament, Vite, OAuth, Turnstile, webhooks, RBAC) but does not directly mention the MIT→AGPL relicensing |
| 100 | <https://pelican.dev/docs/panel/getting-started/> | primary | OK |  |
| 101 | <https://pelican.dev/faq/> | primary | OK |  |
| 102 | <https://pterodactyl.io/community/config/eggs/creating_a_custom_egg.html> | primary | OK |  |
| 103 | <https://pterodactyl.io/community/config/eggs/creating_a_custom_image.html> | primary | WEAK | Confirms container user and /home/container conventions, but does not address throwaway container for egg installs |
| 104 | <https://pterodactyl.io/project/introduction.html> | primary | WEAK | Mentions Panel and Wings as separate components but does not detail the architectural relationship between them on this page |
| 105 | <https://pterodactyl.io/wings/1.0/installing.html> | primary | WEAK | Page states Wings 'requires Docker' but doesn't explicitly call it 'Docker-native' — it's a daemon that orchestrates Docker containers |
| 106 | <https://pufferpanel.com/> | primary | OK |  |
| 107 | <https://wiki.craftycontrol.com/en/4/docs/API%20V2> | primary | WEAK | URL redirects to docs.craftycontrol.com root; the v2 API documentation does exist at the redirected docs site but the original wiki URL no longer hosts it directly |
| 108 | <https://www.portainer.io/> | primary | OK |  |
| 109 | <https://www.xda-developers.com/pterodactyl-favorite-way-manage-self-hosted-game-servers/> | secondary | OK |  |
| 110 | <https://www.xda-developers.com/why-i-stopped-using-portainer-and-went-back-to-dockge/> | secondary | OK |  |