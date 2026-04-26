# Angle a2: Docker-generic container panel landscape

**Question:** What are the leading general-purpose Docker/Compose management panels (Portainer, Dockge, Yacht, Komodo, Lazydocker, etc.), and what primitives do they expose (stack/compose editing, container lifecycle, logs, exec, volumes, networks, image management, RBAC)?
**Why it matters:** Establishes the baseline of container-management UX mcontrol either reuses, embeds, or has to reimplement.
**Boundaries:** Does NOT cover Kubernetes-only panels (Rancher, Lens), does NOT cover Minecraft-specific tooling, does NOT cover the Minecraft+Docker overlap (covered in a3).

---

Got enough from the search snippet. I have sufficient material now to produce the final report.

## Angle: Docker-generic container panel landscape

### Claims (with citations)

- **Portainer is the dominant general-purpose Docker UI, distributed as a single container that manages local and remote Docker, Swarm, Kubernetes, Podman, and ACI environments**: it exposes container/image/volume/network management plus an extensive API, and ships in two editions — Community (open source) and Business (paid, adds RBAC and other enterprise features). [src:https://github.com/portainer/portainer | authority:primary]

- **Portainer's latest CE release is 2.39.1 LTS (March 19, 2026)**, indicating active maintenance on a long-term-support cadence. [src:https://github.com/portainer/portainer/releases/latest | authority:primary]

- **Portainer uses a Server + Agent topology, with an Edge Agent variant that reverses the connection direction (agent dials out to server over an encrypted TLS tunnel)** so remote agents don't have to be exposed to the internet; "Fleet Governance Policies are not available with the classic Agent" — Edge is the recommended path for distributed deployments. [src:https://docs.portainer.io/start/architecture | authority:primary]

- **Portainer Business Edition adds the granular role set on top of the always-available Administrator/Standard User**: Operator, Helpdesk, and Read-Only User roles are documented under the Business Edition RBAC section. [src:https://docs.portainer.io/admin/user/roles | authority:primary]

- **Dockge is an MIT-licensed Docker Compose stack manager from Louis Lam (the Uptime Kuma author), latest release v1.5.0 on March 30, 2025**, deliberately scoped to compose stacks rather than ad-hoc containers/networks/volumes — its README explicitly tells you to use Portainer instead if you need general Docker management. [src:https://github.com/louislam/dockge | authority:primary]

- **Dockge stores stacks as plain compose files on disk and exposes a YAML editor, an interactive web terminal that streams deploy/output, and a `docker run` → `compose.yaml` converter**; it does not ship explicit RBAC, volume, or network management. [src:https://github.com/louislam/dockge | authority:primary]

- **Dockge gained multi-host support in v1.4.0 (January 3, 2025) via "multiple Dockge instances," where one primary instance proxies to other Dockge deployments** — i.e., agent-per-host but the agent is just another full Dockge install rather than a thin agent binary. [src:https://github.com/louislam/dockge/releases | authority:primary]

- **Yacht (SelfhostedPro/Yacht) is effectively dormant**: MIT-licensed, focuses on Portainer-compatible 1-click templates, runs as a single container against `/var/run/docker.sock`, has no implemented user management, and its README explicitly states "This application has not been updated in a while." [src:https://github.com/SelfhostedPro/Yacht | authority:primary]

- **Yacht's last actual release tag is v0.0.7-alpha-hf-1 from May 31, 2021**, with master-branch activity in 2025 limited to README updates — confirming it is not a viable choice for new deployments. [src:https://github.com/SelfhostedPro/Yacht/tags | authority:primary]

- **Komodo (moghtech/komodo) is a Rust+TypeScript GPL-3.0 panel currently at v2.1.2 (April 10, 2026)** — one of the most actively developed challengers to Portainer in this space. [src:https://github.com/moghtech/komodo/releases/latest | authority:primary]

- **Komodo uses an explicit Core + Periphery split**: Core hosts the API and UI and is the only thing users interact with; Periphery is "a small, stateless agent running on each connected server… called by Core to perform actions, report system usage, and retrieve container logs." This is a true server+agent-per-host topology. [src:https://komo.do/docs/intro | authority:primary]

- **Komodo's primitive set is broader than Portainer/Dockge feature-for-feature on the orchestration axis**: container lifecycle, compose stacks with auto-deploy on git push, browser shell + container exec, log viewing, image builds (with optional AWS EC2 spot-instance build capacity), Procedures/Actions for multi-step scheduled workflows, and an audit log of every change with user + timestamp. [src:https://komo.do/docs/intro | authority:primary]

- **Komodo's RBAC is the most comprehensive of the open-source panels surveyed**: granular per-resource permissions, User Groups (recommended over per-user grants) layered like Linux permissions, an "Everyone" mode for groups, and User Groups definable in Resource Syncs. Sign-on supports username/password plus OAuth (GitHub, Google) and generic OIDC providers (e.g., Keycloak). [src:https://komo.do/docs/resources/permissioning | authority:primary] [src:https://komo.do/docs/setup/advanced | authority:primary]

- **Komodo was previously called "Monitor" by mbecker20**: the v1.13 release on August 10, 2022 was titled "Komodo - Docker compose support" and the project later moved from `mbecker20/monitor` to `moghtech/komodo`, with Komodo being chosen because the Komodo dragon is a sub-species of monitor lizard. [src:https://github.com/mbecker20/monitor/releases/tag/v1.13.0 | authority:primary]

- **Lazydocker is the reference TUI in this category**: MIT-licensed Go binary by Jesse Duffield, latest release v0.25.2 (April 19, 2026), supports compose service management, restart/remove/rebuild, attach to container/service, log windows, image-layer inspection, volume/image pruning, and ASCII metric graphs — strictly local (single host, single user, no RBAC, no web UI). [src:https://github.com/jesseduffield/lazydocker | authority:primary]

### Tradeoffs / counter-evidence found

- **Compose-only vs. full Docker**: Dockge's author deliberately scopes the tool to compose and points users to Portainer when they need ad-hoc container/network/volume management — the "scope creep is bad" stance is a real product-design fork in this space [src:https://github.com/louislam/dockge | authority:primary].
- **Portainer's RBAC story is paywalled**: the granular role set (Operator, Helpdesk, Read-Only) lives in Business Edition; CE users get only Admin/Standard, which is a meaningful gap if multi-tenant control is a goal [src:https://docs.portainer.io/admin/user/roles | authority:primary].
- **"Active maintenance" is unevenly distributed**: Yacht is dormant since 2021 release-wise [src:https://github.com/SelfhostedPro/Yacht/tags | authority:primary] while Komodo and Lazydocker shipped releases in April 2026 [src:https://github.com/moghtech/komodo/releases/latest | authority:primary] [src:https://github.com/jesseduffield/lazydocker | authority:primary] — picking a panel by feature alone without checking release cadence is risky.
- **Multi-host architectures differ sharply**: Komodo ships a thin Periphery agent [src:https://komo.do/docs/intro | authority:primary]; Portainer ships an Edge Agent that dials out [src:https://docs.portainer.io/start/architecture | authority:primary]; Dockge proxies between full Dockge instances [src:https://github.com/louislam/dockge/releases | authority:primary]; Lazydocker is single-host only [src:https://github.com/jesseduffield/lazydocker | authority:primary]. For mcontrol's likely "manage many small servers" use case these are very different operational footprints.

### Gaps (no source found)

- I could not load the Portainer CE-vs-BE feature comparison page (`portainer-business-feature-list`, `take-the-tour`, `take-3-minutes`, `get-portainer` all 404'd via WebFetch); confirmation of which specific BE-only features exist beyond the role names (e.g., audit log, registry management, OAuth/SSO availability in CE) is not directly cited.
- Yacht's exact license file contents and confirmation of the LICENSE text type were taken from the README claim of MIT but not fetched from a LICENSE file.
- Komodo's `/docs/resources/permissioning` page returned 404 on direct WebFetch; the permissions-and-OIDC details came from a search-result snippet attributed to that URL plus the `/docs/setup/advanced` URL — both should be re-verified by the verifier agent loading the live URLs.
- Specific Portainer image-management feature list (registry add/remove, pull/push, scan integrations) was not directly fetched from a primary docs page.

### Raw sources consulted

- https://github.com/portainer/portainer (primary)
- https://github.com/portainer/portainer/releases/latest (primary)
- https://docs.portainer.io/start/architecture (primary)
- https://docs.portainer.io/admin/user/roles (primary)
- https://github.com/louislam/dockge (primary)
- https://github.com/louislam/dockge/releases (primary)
- https://github.com/SelfhostedPro/Yacht (primary)
- https://github.com/SelfhostedPro/Yacht/tags (primary)
- https://github.com/SelfhostedPro/Yacht/commits/master (primary, supporting)
- https://github.com/moghtech/komodo (primary)
- https://github.com/moghtech/komodo/releases/latest (primary)
- https://komo.do/docs/intro (primary)
- https://komo.do/docs/resources/permissioning (primary, retrieved via search snippet — direct fetch 404'd)
- https://komo.do/docs/setup/advanced (primary, retrieved via search snippet — not directly fetched)
- https://github.com/mbecker20/monitor/releases/tag/v1.13.0 (primary, for the Monitor → Komodo rename)
- https://github.com/jesseduffield/lazydocker (primary)
- https://docs.portainer.io/start/install-ce/server (primary, mostly empty — referenced architecture doc)
- https://docs.portainer.io/start/intro (primary, mostly empty — referenced architecture doc)
agentId: ac3b56ef0e89141ff (use SendMessage with to: 'ac3b56ef0e89141ff' to continue this agent)
<usage>total_tokens: 36624
tool_uses: 35
duration_ms: 197386</usage>