# Angle a6: Practitioner consensus and pain points

**Question:** What do r/admincraft, r/selfhosted, GitHub issues, and HN/forum threads actually say about each panel's real-world failure modes, friction points, and migration patterns (why do people switch from Crafty to Pterodactyl, abandon AMP, run raw itzg compose instead of any panel)?
**Why it matters:** Reveals the unmet needs and anti-patterns that justify (or invalidate) building mcontrol at all.
**Boundaries:** Does NOT survey features or licensing; only lived-experience signal. Excludes vendor-authored marketing comparisons.

---

I have plenty of solid citations now. Let me compile the final report.

## Angle: Practitioner consensus and pain points

### Claims (with citations)

1. **The Pelican fork was driven by maintainer disagreements with Pterodactyl direction, not a hostile split.** The Pelican FAQ describes the cause as "Difference of visions, directions, and opinions," states relations are "Not at all" hostile, and that "2 months of advance notice" was given before launch [src:https://pelican.dev/faq/ | authority:primary]. A large percentage of the Pterodactyl development team forked the project intending to make a better one [src:https://github.com/coollabsio/coolify/discussions/4215 | authority:secondary].

2. **Practitioners treat Pelican as "the future" but Pterodactyl as the safe production choice today.** Discussion participants describe Pterodactyl as "the most popular and mature" while noting "original devs moved over to Pelican panel, which is still in beta" [src:https://github.com/coollabsio/coolify/discussions/4215 | authority:tertiary]. A user requesting Pelican migration tooling said: "I really want to switch to pelican but i dont want to risk breaking the current system. I cant afford a big downtime" [src:https://github.com/pelican-dev/panel/discussions/13 | authority:tertiary].

3. **Pelican is still officially in beta as of early 2026 and ships breaking changes.** Pelican docs explicitly warn "Pelican is currently in Beta, and some things might change or break between beta versions," with the latest release v1.0.0-beta33 dated Feb 18, 2026 [src:https://pelican.dev/docs/panel/getting-started/ | authority:primary].

4. **Pelican install/migration is a known friction point — community-built migration scripts exist as workarounds.** A community member created the Ptero-to-Pelican-Migration-Script repo because the official "easy migration guide" promised in the Pelican FAQ wasn't yet available [src:https://github.com/FinnAppel/Ptero-to-Pelican-Migration-Script | authority:secondary] [src:https://pelican.dev/faq/ | authority:primary]. Author Andrew Flores confirms "The installation process for Pelican is quite intense and the networking configuration for the Panel and Wings and your actual game servers adds another layer of complexity" [src:https://blog.aflorzy.com/posts/setup-pelican-in-docker | authority:secondary].

5. **Pterodactyl's modpack memory handling is a documented real-world pain point.** GitHub issue #4447 reports that switching the Minecraft egg from `-Xmx8192M` to `-XX:MaxRAMPercentage=95.0` causes modpacks like Divine Journey 2 to consume nearly 8 GB instead of ~4 GB and "Server will get killed by OOM killer as soon as a player interacts with it" [src:https://github.com/pterodactyl/panel/issues/4447 | authority:primary].

6. **Wings has a documented memory leak with high-file-count workloads (relevant to dynmap, modpacks).** Issue #5063 reports Wings RAM usage climbing to 32 GB on hosts with ~1 million files — "wings uses a lot of RAM (cache) without clearing it, restarting wings is of no use, as soon as it is turned back on, the memory fills up until it reaches saturation point." The issue was closed as "not planned" [src:https://github.com/pterodactyl/panel/issues/5063 | authority:primary].

7. **Wings volume permission issues recur across users / Docker setups.** Issue #3040 documents Dockerized Wings on Unraid creating server folders with `drwx------` and failing with "bind source path does not exist," and similar reports appear in #1790 and #5170 [src:https://github.com/pterodactyl/panel/issues/3040 | authority:primary].

8. **Crafty Controller's installer reliability is a recurring complaint.** A Proxmox community-script issue captures a Debian 12 / Proxmox 9.1 install failing with `grep: /opt/crafty-controller/crafty/crafty-4/app/config/default-creds.txt: No such file or directory` at line 73 — the installer references credentials before they exist [src:https://github.com/community-scripts/ProxmoxVE/issues/13568 | authority:primary].

9. **Crafty lacks per-server isolation, which pushes multi-tenant practitioners away.** Level1Techs forum thread reports a user confirming via Discord that Crafty "doesn't have" server isolation between instances, while AMP "no issues with isolation and it will default install them via docker" [src:https://forum.level1techs.com/t/minecraft-web-panel-recommendations/233819 | authority:tertiary].

10. **PufferPanel 3.0 has visible console-stickiness regressions reported in production.** Issue #1439 (Aug 2025) describes that after upgrading from 2.7 to 3.0.0-rc.13, "the Minecraft server console becomes unresponsive. Commands … stop appearing until the page is manually refreshed" [src:https://github.com/pufferpanel/pufferpanel/issues/1439 | authority:primary].

11. **AMP's friction is "cumbersome and cryptic" setup, especially for newcomers and multi-instance topologies.** A CubeCoders forum thread captures a user with VPS experience giving up on AMP after finding it "really difficult, cryptic, and complicated to deal with," failing on a Waterfall+Geyser+Floodgate-to-Purpur multi-server setup [src:https://discourse.cubecoders.com/t/amp-is-not-for-me-gave-it-a-try-found-it-too-cumbersome-can-i-get-a-refund/4899 | authority:primary]. Level1Techs commenters separately note "performance impacts in some games" and "It's not FOSS but it's pretty damn good at what it does" [src:https://forum.level1techs.com/t/amp-game-server-good-or-bad/231908 | authority:tertiary].

12. **Practitioner consensus for "one server with friends" steers AWAY from Pterodactyl toward Crafty / AMP / raw Docker.** Cross-thread guidance treats Pterodactyl as overbuilt for a single-server case and recommends Crafty or AMP Free instead, reserving Pterodactyl for multi-server / 50-person communities [src:https://lowendspirit.com/discussion/9906/any-good-alternatives-to-pterodactyl | authority:tertiary]. The XDA author of the "favorite way" piece notes it took "less than a minute … to spin up a Risk of Rain 2 server" — but commenters call the project "no longer well maintained" with a vulnerability disclosed the prior week [src:https://www.xda-developers.com/pterodactyl-favorite-way-manage-self-hosted-game-servers/ | authority:secondary].

13. **itzg + raw Docker Compose has its own well-known pain: autopause vs Watchdog crashes.** Issue #3261 captures the canonical failure: paused Java fails Minecraft's tick watchdog ("Can't keep up! … Running 143850ms or 2877 ticks behind", "Considering it to be crashed, server will forcibly shutdown"), with the user noting "everytime the server autopauses it crashes because of watchdog" [src:https://github.com/itzg/docker-minecraft-server/issues/3261 | authority:primary]. Discussion #3099 also documents containers "running for weeks and never truly pausing" because something keeps pinging port 25565 [src:https://github.com/itzg/docker-minecraft-server/discussions/3099 | authority:primary].

14. **A breakaway "Pyrodactyl" fork explicitly markets itself against both Pterodactyl AND Pelican on bundle size and accessibility — a tertiary signal that practitioners feel both incumbents are bloated/inaccessible.** Pyrodactyl claims "initial download size is over 170 times smaller than leading Pterodactyl forks, including Pelican" and 16x faster load times, framed as "faster, smaller, safer, and more accessible than Pelican" [src:https://github.com/pyrohost/pyrodactyl | authority:primary].

15. **The Portainer-to-Dockge migration pattern shows mature self-hosters abandon heavyweight panels for compose-file-on-disk simplicity.** XDA author who returned to Dockge: "Portainer might be more than what I actually need. Yes, it's powerful, but it's simply got too many moving elements" — the trigger was wanting "stability, reproducibility, and just not breaking your setup" [src:https://www.xda-developers.com/why-i-stopped-using-portainer-and-went-back-to-dockge/ | authority:secondary]. This is the same dynamic implied when itzg-compose users skip panels entirely.

### Tradeoffs / counter-evidence found

- **Pterodactyl is not actually "abandoned" in the literal sense** — repos remain active into 2025/2026 and the LowEndSpirit alternatives thread explicitly found "no genuine complaints driving users away" and noted providers integrating it into billing because of customer demand [src:https://lowendspirit.com/discussion/9906/any-good-alternatives-to-pterodactyl | authority:tertiary]. The "no longer well maintained" claim is one commenter's opinion on XDA, not a maintainer statement [src:https://www.xda-developers.com/pterodactyl-favorite-way-manage-self-hosted-game-servers/ | authority:secondary].
- **AMP gets praise from practitioners precisely on the dimensions where it gets criticized** — Level1Techs users call out "Decent documentation and support," active developer presence, and "user management panel … easy to have a moderator or local admin" as decisive reasons to choose it over open-source alternatives [src:https://forum.level1techs.com/t/amp-game-server-good-or-bad/231908 | authority:tertiary].
- **Pelican license change to AGPLv3 isn't framed as anti-commercial** — the FAQ explicitly notes "Private panels do not have that restriction!" and plugins are exempt, undercutting some Reddit confusion that "pelican is paid only" [src:https://pelican.dev/faq/ | authority:primary].

### Gaps (no source found)

- **r/admincraft and r/selfhosted Reddit threads were not directly fetchable** — both `reddit.com` and `old.reddit.com` returned 403/blocked from WebFetch, and the AnswerOverflow mirrors of admincraft Discord threads (`answeroverflow.com`) also returned 403. So I have *secondary summaries* of admincraft threads via search engines but no primary-quoted Reddit user voices. Many of my Reddit-flavored claims come from forum mirrors (LowEndTalk, LowEndSpirit, Level1Techs, CubeCoders Discourse).
- **No primary source found for "people abandon panels and run raw itzg compose specifically because of panel pain"** — the closest evidence is the Portainer→Dockge migration pattern (XDA) and one r/selfhosted commenter cited via search snippet ("Please don't get a panel you need to pay for"), but I couldn't fetch the underlying Reddit thread to quote it directly.
- **No primary source quantifying "why people switch FROM AMP back to open-source"** — the strongest evidence is the single CubeCoders refund-request thread (#4899); no broad migration-pattern source surfaced.
- **Dockge specifically used for Minecraft / game servers** — no source found tying Dockge directly to game-server practitioner usage; the XDA piece is general homelab.
- **Portainer specifically used for Minecraft** — likewise no thread surfaced focused on Minecraft+Portainer feedback.

### Raw sources consulted

Primary (project repos, FAQs, official forums):
- https://pelican.dev/faq/
- https://pelican.dev/docs/panel/getting-started/
- https://github.com/pelican-dev/panel/discussions/13
- https://github.com/pterodactyl/panel/issues/4447
- https://github.com/pterodactyl/panel/issues/4635
- https://github.com/pterodactyl/panel/issues/5063
- https://github.com/pterodactyl/panel/issues/3040
- https://github.com/pufferpanel/pufferpanel/issues/1439
- https://github.com/itzg/docker-minecraft-server/issues/3261
- https://github.com/itzg/docker-minecraft-server/discussions/3099
- https://github.com/community-scripts/ProxmoxVE/issues/13568
- https://github.com/pyrohost/pyrodactyl
- https://discourse.cubecoders.com/t/amp-is-not-for-me-gave-it-a-try-found-it-too-cumbersome-can-i-get-a-refund/4899
- https://news.ycombinator.com/item?id=14731663

Secondary (community blogs / discussion summaries):
- https://www.xda-developers.com/why-i-stopped-using-portainer-and-went-back-to-dockge/
- https://www.xda-developers.com/pterodactyl-favorite-way-manage-self-hosted-game-servers/
- https://blog.aflorzy.com/posts/setup-pelican-in-docker
- https://github.com/coollabsio/coolify/discussions/4215
- https://github.com/FinnAppel/Ptero-to-Pelican-Migration-Script

Tertiary (forum discussions, alternatives sites):
- https://forum.level1techs.com/t/minecraft-web-panel-recommendations/233819
- https://forum.level1techs.com/t/amp-game-server-good-or-bad/231908
- https://lowendspirit.com/discussion/9906/any-good-alternatives-to-pterodactyl

Sources attempted but blocked (403):
- https://www.answeroverflow.com/m/1262960607779360810
- https://www.answeroverflow.com/m/1350585776643117066
- https://www.answeroverflow.com/m/1385282365840162889
- https://www.spigotmc.org/resources/crafty-controller.80852/reviews
- https://www.spigotmc.org/resources/pufferpanel.40158/reviews
- https://www.reddit.com/r/selfhosted/comments/umvatt/...
- https://old.reddit.com/r/selfhosted/comments/umvatt/...
- https://r.nf/r/selfhosted/comments/umvatt/...
agentId: a5064b091d7b8834a (use SendMessage with to: 'a5064b091d7b8834a' to continue this agent)
<usage>total_tokens: 65727
tool_uses: 58
duration_ms: 295362</usage>