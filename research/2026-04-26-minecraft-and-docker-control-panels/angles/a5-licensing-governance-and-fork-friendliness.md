# Angle a5: Licensing, governance, and fork-friendliness

**Question:** What are the licenses, governance models, contribution velocity, and known fork histories of the candidate projects (e.g., MCSManager's license shifts, AMP being closed-source, Pterodactyl's MIT + Pelican fork, Crafty's GPL), and which are realistically buildable-on?
**Why it matters:** A technically perfect base is useless if the license or governance blocks mcontrol's intended distribution and modifications.
**Boundaries:** Does NOT cover technical features or architecture; purely legal, social, and project-health signals.

---

I have sufficient material. Let me compile the findings.

## Angle: Licensing, governance, and fork-friendliness

### Claims (with citations)

1. **MCSManager is licensed under Apache License 2.0**, with the LICENSE file containing the standard Apache 2.0 grant of "perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable copyright license" — confirmed in both the LICENSE file and README footer ("© 2025 MCSManager"). [src:https://github.com/MCSManager/MCSManager/blob/master/LICENSE | authority:primary] [src:https://github.com/MCSManager/MCSManager/blob/master/README.md | authority:primary]

2. **MCSManager is actively maintained**, with latest release v10.12.4 on Feb 16, 2026, and ~4,063 commits on the master branch. [src:https://github.com/MCSManager/MCSManager | authority:primary]

3. **Pterodactyl Panel is licensed under the MIT License** (verbatim "The MIT License (MIT)" in LICENSE.md). [src:https://github.com/pterodactyl/panel/blob/develop/LICENSE.md | authority:primary]

4. **Pterodactyl's most recent release is v1.12.2, dated March 26, 2024** — i.e., the project has not produced a new release since the Pelican fork. [src:https://github.com/pterodactyl/panel/releases/tag/v1.12.2 | authority:primary]

5. **Pelican Panel is a fork of Pterodactyl, relicensed from MIT to AGPLv3.** Pelican's official FAQ states verbatim: "We forked from Pterodactyl and made the decision to relicense the Panel from the original MIT license to the AGPLv3 license," citing "Difference of visions, directions, and opinions" and noting they gave the Pterodactyl team 2 months of advance notice. [src:https://pelican.dev/faq/ | authority:primary]

6. **Pelican Panel's LICENSE.md is AGPL-3.0**, confirmed via the GitHub repo (footer/license badge AGPL-3.0). [src:https://github.com/pelican-dev/panel | authority:primary]

7. **Pelican is led by a named team of ex-Pterodactyl contributors**, including Lance Pioch (`shadowlancer`, "Project Lead & Fullstack Dev"), Michael Parker (`parkervcp`, "Egg/Docker Maintainer"), Charles Morgan (`areyouscared`), Alex Vlad (`.scai`), `boy132`, and Martin Oscar (`rmartinoscar`). [src:https://pelican.dev/docs/about | authority:primary]

8. **Pelican Panel is highly active**, with ~6,566 commits on main, 32 releases, and latest v1.0.0-beta33 on Feb 18, 2026; ~2k stars. [src:https://github.com/pelican-dev/panel | authority:primary]

9. **AMP (Application Management Panel) by CubeCoders is closed-source / proprietary** with a perpetual-license commercial pricing model: Standard ~£7.50 (5 instances), Professional ~£15 (15 instances), Advanced ~£30 (50 instances), plus an Enterprise tier. [src:https://discourse.cubecoders.com/t/changes-to-amp-product-tiers-in-q3-2023/5178 | authority:primary]

10. **Crafty Controller is licensed under GPL-3.0-or-later** ("GNU General Public License v3.0 or later"), hosted on GitLab (the GitHub repo was moved). [src:https://gitlab.com/crafty-controller/crafty-4/-/blob/master/LICENSE | authority:primary]

11. **Crafty Controller is governed as a community project under Arcadia Technology** (copyright "© 2025 Arcadia Technology"), with explicit Leadership / Advisors / Core Team / Helpers tiers. The repo shows ~6,000+ commits and 68 releases since August 2020. [src:https://craftycontrol.com/ | authority:primary] [src:https://gitlab.com/crafty-controller/crafty-4 | authority:primary]

12. **PufferPanel is licensed under Apache License 2.0**, organization-maintained under the `pufferpanel` GitHub org, with latest release v3.0.7 on April 21, 2026 (active). [src:https://github.com/PufferPanel/PufferPanel/blob/master/LICENSE | authority:primary] [src:https://github.com/PufferPanel/PufferPanel | authority:primary]

13. **Portainer Community Edition is licensed under the zlib license** (the LICENSE file contains the zlib disclaimer text; the README states "Portainer is licensed under the zlib license"). It is **company-backed (Portainer.io, based in New Zealand)** and offered as CE + Business Edition + a Home & Student license. [src:https://github.com/portainer/portainer/blob/develop/LICENSE | authority:primary] [src:https://www.portainer.io/ | authority:primary]

14. **Portainer is highly active and well-resourced** — 37.3k stars, latest release 2.39.1 LTS on March 19, 2026, 178 total releases. [src:https://github.com/portainer/portainer | authority:primary]

15. **Dockge is MIT-licensed**, maintained primarily by Louis Lam (`louislam`, also the maintainer of Uptime Kuma). Latest release v1.5.0 on March 30, 2025; 23k+ stars; 102 open issues / 39 open PRs suggest a single-maintainer bottleneck. [src:https://github.com/louislam/dockge/blob/master/LICENSE | authority:primary] [src:https://github.com/louislam/dockge | authority:primary]

16. **Komodo is GPL-3.0-licensed** ("GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007") and maintained under the `moghtech` org; latest release v2.1.2 on April 10, 2026, ~2,848 commits, 11k stars — actively developed. [src:https://github.com/moghtech/komodo/blob/main/LICENSE | authority:primary] [src:https://github.com/moghtech/komodo | authority:primary]

17. **Yacht is MIT-licensed** (LICENSE.md uses standard MIT permission grant) and maintained by `wickedyoda` under the SelfhostedPro organization. The README explicitly warns it is dormant: "This applicaton has not been updated in a while, I have brought it up to date as much as possible for security," with a backend rewrite happening in a separate `Yacht-Docker-Container` repo. [src:https://github.com/SelfhostedPro/Yacht/blob/master/LICENSE.md | authority:primary] [src:https://github.com/SelfhostedPro/Yacht | authority:primary]

### Tradeoffs / counter-evidence found

- **License compatibility implications for "build-on" candidates:**
  - MIT (Pterodactyl, Dockge, Yacht) and Apache-2.0 (MCSManager, PufferPanel) are the most fork-friendly — both permit closed-source derivatives and re-licensing of derivative work (Pelican's MIT→AGPL relicense being a live example). [src:https://github.com/pterodactyl/panel/blob/develop/LICENSE.md | authority:primary] [src:https://pelican.dev/faq/ | authority:primary]
  - AGPL (Pelican) and GPL-3.0 (Crafty, Komodo) are *copyleft* and force any network-served derivative (AGPL) or distributed binary (GPL) to also be open-sourced under the same license — a meaningful constraint if `mcontrol` ever wants a commercial/closed tier.
  - zlib (Portainer CE) is permissive but unusual — a less-recognized license that may create vendor-lock concerns since the Portainer company also owns the BE commercial fork. [src:https://github.com/portainer/portainer/blob/develop/LICENSE | authority:primary]

- **Pelican vs Pterodactyl tone of dispute:** Pelican's FAQ insists hostilities are "not at all" and the team gave 2 months of notice, framing the fork as amicable — but the relicense (MIT→AGPL) is *legally* unilateral, since contributors didn't need original maintainer consent. [src:https://pelican.dev/faq/ | authority:primary]

- **Single-maintainer fragility:** Dockge (Louis Lam) has 23k stars but the last release is from March 2025 and the repo has 102 open issues — bus-factor risk inherited from one person also running Uptime Kuma. [src:https://github.com/louislam/dockge | authority:primary]

- **Pterodactyl is not formally archived but effectively stagnant:** v1.12.2 (March 2024) preceded the Pelican fork and there's been no subsequent release, suggesting the project has functionally ceded development momentum to Pelican. [src:https://github.com/pterodactyl/panel/releases/tag/v1.12.2 | authority:primary]

### Gaps (no source found)

- **MCSManager license-shift history:** I could not find primary evidence of any prior license (the question hypothesized a shift). Current LICENSE is Apache-2.0 with no mention of past licenses; web search did not surface a documented relicense event. The premise that MCSManager *had* a license shift may be inaccurate, or it predates the current repo's history — needs git-log archaeology to confirm.
- **Exact fork date of Pelican Panel:** Pelican's FAQ confirms the fork happened with 2 months' advance notice but does not state a specific date; secondary sources (Admincraft / answeroverflow) reference "April 12" but I did not verify on a primary Pelican blog post or GitHub announcement.
- **Pterodactyl's current maintainer status post-fork:** I could not retrieve a primary statement from main maintainer Matthew (Dane) about his ongoing role; secondary sources claim he was "no longer accepting new pull requests and only doing security updates," but I did not find a primary confirmation on Pterodactyl's site or GitHub.
- **PufferPanel governance specifics** (named maintainers, leadership structure) were not surfaced — README points to Discord for contact rather than naming individuals.
- **Komodo maintainer identity** beyond the `moghtech` org name is not surfaced on the repo landing page.
- **Open vs closed PR ratios** were not consistently retrievable across all repos via WebFetch (the rendered GitHub pages truncated.

### Raw sources consulted

- https://github.com/MCSManager/MCSManager/blob/master/LICENSE
- https://github.com/MCSManager/MCSManager/blob/master/README.md
- https://github.com/MCSManager/MCSManager
- https://github.com/pterodactyl/panel/blob/develop/LICENSE.md
- https://github.com/pterodactyl/panel
- https://github.com/pterodactyl/panel/releases
- https://github.com/pterodactyl/panel/releases/tag/v1.12.2
- https://github.com/pelican-dev/panel
- https://pelican.dev/faq/
- https://pelican.dev/docs/about
- https://pelican.dev/docs/comparison/
- https://gitlab.com/crafty-controller/crafty-4
- https://gitlab.com/crafty-controller/crafty-4/-/blob/master/LICENSE
- https://craftycontrol.com/
- https://github.com/PufferPanel/PufferPanel
- https://github.com/PufferPanel/PufferPanel/blob/master/LICENSE
- https://github.com/portainer/portainer
- https://github.com/portainer/portainer/blob/develop/LICENSE
- https://www.portainer.io/
- https://github.com/louislam/dockge
- https://github.com/louislam/dockge/blob/master/LICENSE
- https://github.com/moghtech/komodo
- https://github.com/moghtech/komodo/blob/main/LICENSE
- https://github.com/SelfhostedPro/Yacht
- https://github.com/SelfhostedPro/Yacht/blob/master/LICENSE.md
- https://discourse.cubecoders.com/t/changes-to-amp-product-tiers-in-q3-2023/5178
agentId: a0564cdd389141c4f (use SendMessage with to: 'a0564cdd389141c4f' to continue this agent)
<usage>total_tokens: 40776
tool_uses: 43
duration_ms: 198448</usage>