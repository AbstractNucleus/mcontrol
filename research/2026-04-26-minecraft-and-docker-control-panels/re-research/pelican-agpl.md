# Re-research: pelican-agpl

Excellent — I have the verbatim FAQ text. I have everything needed. Let me write up the assessment.

### Re-research for: Pelican commercial license carve-out
Status: RESOLVED (claim is substantively correct, but the original phrasing collapses two distinct license layers — AGPL obligations vs. optional commercial license — and needs a small wording fix)

**1. The LICENSE file is plain, unmodified AGPL-3.0 — no Pelican-specific carve-out lives in the license text itself.**
The repo file at `https://raw.githubusercontent.com/pelican-dev/panel/main/license` (note: lowercase `license`, not `LICENSE`) is the FSF stock text: `"GNU AFFERO GENERAL PUBLIC LICENSE / Version 3, 19 November 2007 / Copyright (C) 2007 Free Software Foundation, Inc."` (lines 1–3, total 662 lines). GitHub's API also reports the repo license as `{"key":"agpl-3.0","spdx_id":"AGPL-3.0"}`. There is no `COMMERCIAL.md` in the repo root — only `license` and `contributor_license_agreement.md`. So whatever Pelican says about commercial licensing exists outside the LICENSE file, on the marketing site. [src: https://raw.githubusercontent.com/pelican-dev/panel/main/license | authority: pelican-dev/panel main branch, AGPL-3.0 verbatim]

**2. The AGPL's mandatory clause is Section 13 ("Remote Network Interaction"), not a "public panel" clause.** Verbatim from the license file (lines 540–551):
> "13. Remote Network Interaction; Use with the GNU General Public License. Notwithstanding any other provision of this License, if you modify the Program, your modified version must prominently offer all users interacting with it remotely through a computer network (if your version supports such interaction) an opportunity to receive the Corresponding Source of your version by providing access to the Corresponding Source from a network server at no charge, through some standard or customary means of facilitating copying of software."

This is the mandatory baseline obligation: modify + expose over a network = source must be offered to remote users. The AGPL itself does not use the word "public" or distinguish "public panels" from anything else — it triggers on remote network interaction with a modified version. The "public/private panel" framing is Pelican's *interpretation* of Section 13, communicated on their FAQ, not text from the license. [src: https://raw.githubusercontent.com/pelican-dev/panel/main/license | authority: AGPL-3.0 §13]

**3. Pelican's FAQ is where the "public panel" interpretation and the commercial-license offer live.** Verbatim from `https://pelican.dev/faq/` (the `/blog/commercial-license-faq/` and `/blog/relicensing-pelican-to-agpl/` URLs both 404 — the content was consolidated into the main FAQ):
> "We forked from Pterodactyl and made the decision to relicense the Panel from the original MIT license to the AGPLv3 license."
> "The AGPL license is what is known as a copyleft type license. It requires that any modifications to a public panel must be open sourced under the same license. Private panels do not have that restriction!"
> "Plugins do not fall under the new license because they do not modify the panel source code."

And the explicit three-prong test for *needing the commercial license*:
> "The license change does only affect you if you meet all of the following requirements: 1. You modified the Pelican panel source files. 2. These modifications are not open source. 3. Your modified panel is publicly available. (Note: People who are family, friends, and acquaintances are not the public)"
> "If you meet all of the above requirements you need a commercial license."
> "Please note that the usage or development of plugins/themes does not require a commercial license."

[src: https://pelican.dev/faq/ | authority: official Pelican FAQ, current as of 2026-04]

**4. Verdict on the original claim — "Pelican commercial license only required for proprietary modified PUBLIC panels".** This matches Pelican's own three-prong test almost verbatim: modified + closed-source + publicly available → commercial license needed. So the claim is *factually accurate as a summary of when the optional commercial license is sold.* The overreach risk the reviewer flagged is real but minor: the claim conflates two distinct license layers and can mislead readers into thinking AGPL itself only kicks in for "public" panels. The cleaner formulation is:

- **AGPL-3.0 §13 (mandatory, baseline):** any modified Pelican Panel exposed to remote users over a network must offer those users the Corresponding Source. This is non-negotiable and applies regardless of Pelican's marketing language.
- **Pelican commercial license (optional, sold separately):** lets you escape the §13 source-disclosure obligation. Per Pelican's FAQ, you only need to *buy* it if all three conditions hold (modified + closed-source + publicly available, where "public" excludes "family, friends, and acquaintances"). Plugins and themes are explicitly carved out — they "do not fall under the new license because they do not modify the panel source code."

So the original claim's substance is correct (the *commercial* license is only needed for the public-modified-proprietary case), but the safer phrasing is "Pelican's commercial license is only *required to be purchased* when you operate a publicly-available, modified, closed-source panel — the underlying AGPL still governs every modified deployment." [src: https://pelican.dev/faq/ | authority: Pelican FAQ] [src: https://raw.githubusercontent.com/pelican-dev/panel/main/license | authority: AGPL-3.0 §13]

Sources:
- [pelican-dev/panel `license` file (raw)](https://raw.githubusercontent.com/pelican-dev/panel/main/license)
- [pelican-dev/panel repo](https://github.com/pelican-dev/panel)
- [Pelican Frequently Asked Questions](https://pelican.dev/faq/)
- [Pelican homepage](https://pelican.dev/)
agentId: a0f138f23bd4dac47 (use SendMessage with to: 'a0f138f23bd4dac47' to continue this agent)
<usage>total_tokens: 32049
tool_uses: 19
duration_ms: 143923</usage>