# Re-research: pterodactyl-maintenance

I have sufficient data to write the response.

### Re-research for: Pterodactyl maintenance narrative
Status: RESOLVED (with nuance — the "safe choice today" framing is supportable; the "practitioners steer away for small servers" claim is weaker than originally cited)

**Release cadence and contents (RESOLVED, strengthened).** v1.12.2 was published 2026-03-26T23:56:46Z, with a release body containing five bug fixes only: task execution job chaining, dropdown rendering inside the transfer-server modal, spurious activity-log entries on unchanged startup variables, "multiple issues with the docker image," and stuck server transfers from incorrect API permission checks [src:gh api repos/pterodactyl/panel/releases/tags/v1.12.2 | authority:GitHub primary]. The cadence between recent releases is healthier than the 2023–2025 lull: v1.12.0 on 2026-01-06, v1.12.1 on 2026-02-14, v1.12.2 on 2026-03-26 — roughly one minor/patch every ~5–6 weeks in Q1 2026, ending a long gap (v1.11.11 was 2025-06-18 and v1.11.10 was 2024-11-15) [src:gh api repos/pterodactyl/panel/releases | authority:GitHub primary]. Wings is markedly quieter: latest tag is v1.12.1 on 2026-01-13, with only one commit on its default branch since 2026-01-26 (a Dane Everitt error-logging tweak on 2026-04-02) and zero merged PRs in the last 90 days [src:gh api repos/pterodactyl/wings/releases | authority:GitHub primary][src:gh api search/issues PR merged:>=2026-01-26 | authority:GitHub primary].

**Recent activity (RESOLVED).** pterodactyl/panel has 22 commits and 18 merged PRs in the last 90 days (since 2026-01-26), with Dane Everitt himself authoring or merging the security-relevant ones — explicit resource locking on database/backup creation, email-change throttling against enumeration, dependency updates, SFTP session revocation on password change, and scoping of the remote-node token [src:gh api repos/pterodactyl/panel/commits since=2026-01-26 | authority:GitHub primary]. Open-PR backlog is 66 on panel and 40 on wings, with only 10 wings PRs closed in the same window — so panel is actively shipping, wings is mostly dormant [src:gh api search/issues | authority:GitHub primary]. This means the original "actively maintained" claim is true for the panel but weaker for wings; the v1.12.2 date is verified.

**Practitioner consensus (PARTIALLY CONFIRMED-COUNTER).** The lowendspirit/9906 thread does back the "safe choice today" framing — a hosting provider explicitly says "Pelican is the future approach probably but it's in alpha and a fork of Pterodactyl. Nothing compared to Pterodactyl's features, stability" and another user calls Pterodactyl "basically what the industry uses" [src:https://lowendspirit.com/discussion/9906/any-good-alternatives-to-pterodactyl | authority:practitioner forum]. However, that thread does **not** make the "small servers" argument; it discusses provider-scale hosting. The "steer away for small servers" claim isn't substantiated by the cited URL — the thread's framing is the opposite (Pterodactyl is overkill or fine, with Crafty/PufferPanel mentioned as lighter alternatives, but not specifically "steer away"). Meanwhile, the Admincraft/Pelican-leaning sources show a real practitioner shift: one Reddit user who switched to Pelican hit UI bugs and Aikar's-flags boot crashes and was considering reverting to Pterodactyl as the "future-proof" choice [src:WebSearch result citing reddit.com/r/admincraft/comments/1fp9qip | authority:practitioner], while Pelican's own FAQ stays neutral ("Pelican and Pterodactyl are separate projects... we can't say [Pterodactyl's future]") rather than declaring Pterodactyl dead [src:https://pelican.dev/faq/ | authority:Pelican primary]. So: "Pterodactyl is the safe choice today" is defensible; "practitioners steer away from Pterodactyl for small servers" is not supported by the lowendspirit citation and should be dropped or re-sourced.

Sources:
- [Pterodactyl panel v1.12.2 release (GitHub API)](https://github.com/pterodactyl/panel/releases/tag/v1.12.2)
- [Pterodactyl panel releases (GitHub)](https://github.com/pterodactyl/panel/releases)
- [Pterodactyl wings releases (GitHub)](https://github.com/pterodactyl/wings/releases)
- [Pterodactyl panel merged PRs since 2026-01-26 (GitHub search)](https://github.com/pterodactyl/panel/pulls?q=is%3Apr+is%3Amerged+merged%3A%3E%3D2026-01-26)
- [LowEndSpirit: Any good alternatives to Pterodactyl?](https://lowendspirit.com/discussion/9906/any-good-alternatives-to-pterodactyl)
- [Pelican FAQ](https://pelican.dev/faq/)
- [Pelican Comparison](https://pelican.dev/docs/comparison/)
- [Admincraft: Pterodactyl vs Pelican panel (AnswerOverflow mirror)](https://www.answeroverflow.com/m/1385282365840162889)
- [Reddit r/admincraft: Pterodactyl vs Pelican](https://www.reddit.com/r/admincraft/comments/1fp9qip/pterodactyl_vs_pelican/)
agentId: a2a305c38ce50873b (use SendMessage with to: 'a2a305c38ce50873b' to continue this agent)
<usage>total_tokens: 29940
tool_uses: 22
duration_ms: 143052</usage>