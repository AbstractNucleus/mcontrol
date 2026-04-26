# Angle a3: Overlap zone — how Minecraft panels handle Docker (and vice versa)

**Question:** Which Minecraft panels natively run servers in containers (Pterodactyl Wings, PufferPanel), how do they model the container boundary (egg/image/template abstraction, volume layout, networking), and conversely, what does running itzg/minecraft-server under a generic Docker panel look like in practice?
**Why it matters:** This is mcontrol's exact problem space — understanding where the two ecosystems already meet reveals the unfilled niche.
**Boundaries:** Does NOT re-list panels from a1/a2; focuses only on the integration seam. Does NOT cover bare-metal/systemd Minecraft management.

---

I have enough material. Compiling the report now.

## Angle: Overlap zone — Minecraft panels and Docker

### Claims (with citations)

**Pterodactyl Wings is Docker-native by design.** Wings is described as "Pterodactyl's server control plane" and requires "a Linux system capable of running Docker containers"; it does not run on Windows [src:https://pterodactyl.io/wings/1.0/installing.html | authority:primary] [src:https://github.com/pterodactyl/wings | authority:primary]. Every server Wings manages is a Docker container; allocations (IP + port pairs) are defined in the Panel and bound to those containers [src:https://pterodactyl.io/wings/1.0/installing.html | authority:primary].

**The Egg is the per-game template that drives the container.** An Egg specifies a valid Docker image, a start command, a "stop command" (e.g. `stop`, `end`, or `^C` for SIGINT), variables exposed as `{{VARIABLE_NAME}}` for substitution, configuration-file definitions, and a "done" marker line that signals readiness to the daemon [src:https://pterodactyl.io/community/config/eggs/creating_a_custom_egg.html | authority:primary].

**Container conventions are strict.** Every Pterodactyl-compatible image must contain a Linux user named `container` with home `/home/container`, and `WORKDIR` must be `/home/container`. The startup command is passed in as the `STARTUP` environment variable with `{{...}}` placeholders that the entrypoint expands at runtime, decoupling the image from the specific game configuration [src:https://pterodactyl.io/community/config/eggs/creating_a_custom_image.html | authority:primary].

**Egg installs use a separate, throwaway install container.** Wings spawns an installer container with an entrypoint and `/mnt/install/install.sh`, runs the install script (typically as root), writes server content into `/mnt/server`, then a second container (the actual game container) is started with that content force-mounted into `/home/container`. This split exists because the runtime container runs as the unprivileged `container` user [src:https://pterodactyl.io/community/config/eggs/creating_a_custom_image.html | authority:primary].

**Pterodactyl maintains a curated image set called "yolks."** `pterodactyl/yolks` is "A curated collection of core images that can be used with Pterodactyl's Egg system," organized into base OSes (Alpine/Debian), game-specific images, installer images, and generic "yolks" runtimes (Java, Python, Node.js, Go) so different Eggs can share runtimes and switch versions independently [src:https://github.com/pterodactyl/yolks | authority:primary]. The official Paper Minecraft egg, for example, uses `ghcr.io/ptero-eggs/yolks:java_25` (and other Java versions) and runs `java -Xms128M -XX:MaxRAMPercentage=95.0 -Dterminal.jline=false -Dterminal.ansi=true -jar {{SERVER_JARFILE}}` after `curl`-downloading the JAR validated against PaperMC's API [src:https://eggs.pterodactyl.io/egg/games-paper/ | authority:primary].

**Pterodactyl's port model has TCP/UDP coupling that is awkward for Minecraft.** Wings allocates both TCP and UDP for any allocated port; "Although Minecraft only uses the tcp port, the udp port is still occupied by the container, and cannot be used by other containers / programs," which prevents reusing the same numeric port for, e.g., a UDP tunnel alongside the Minecraft TCP listener [src:https://github.com/pterodactyl/panel/issues/4850 | authority:primary].

**PufferPanel offers two environments — Docker and "standard" (subprocess).** The standard environment "executes commands directly on the host system as the same user PufferPanel is running as," does NOT run commands through a shell, and "does NOT prevent servers from accessing each others or PufferPanels files"; ports below 1024 are off-limits because PufferPanel does not run as root [src:https://docs.pufferpanel.com/en/2.x/environments/standard.html | authority:primary]. The Docker environment "runs a separate docker container for every server," provides "strong isolation for files but also processes," and lets servers bind sub-1024 ports without root because mapping is done by Docker [src:https://docs.pufferpanel.com/en/2.x/environments/docker.html | authority:primary].

**PufferPanel's Docker mode bypasses the image's own ENTRYPOINT.** "PufferPanel does NOT use the images default entrypoint but rather creates a fresh container for the server, mounts in the server files and runs the run command defined for the server in PufferPanel in the root of the server files" [src:https://docs.pufferpanel.com/en/2.x/environments/docker.html | authority:primary]. This means an `itzg/minecraft-server`-style image whose entrypoint does the heavy lifting (version downloads, server.properties templating) would NOT behave as designed inside PufferPanel — Pufferpanel expects to provide its own run command against pre-installed server files.

**PufferPanel 3.0 split panel vs. node and made templates dual-environment.** "Our Docker image also has been cleaned up. It has instead now been designed to only run the panel and a node which creates Docker containers" (previously servers ran inside the PufferPanel container itself). Templates added "conditions" — "a basic 'if' statement system that is designed to help consolidate our templates and drive better logic about if an operator should run," allowing one template to target both Docker and standard environments [src:https://docs.pufferpanel.com/en/3.x/release-notes/3.0.0.html | authority:primary]. Community templates are now pulled from GitHub at use-time rather than copied locally [src:https://docs.pufferpanel.com/en/3.x/release-notes/3.0.0.html | authority:primary].

**The itzg/minecraft-server image is opinionated and entrypoint-driven.** It "automatically installs/upgrades versions, modloaders, modpacks and more at startup" [src:https://github.com/itzg/docker-minecraft-server | authority:primary]. EULA is required (`-e EULA=TRUE`) [src:https://docker-minecraft-server.readthedocs.io/en/latest/ | authority:primary]; data lives at `/data` (the container's volume mount point) [src:https://docker-minecraft-server.readthedocs.io/en/latest/ | authority:primary]; the server type is selected via `TYPE` (default `VANILLA`, with Forge/Fabric and modpack platforms Modrinth, CurseForge, Feed the Beast supported) [src:https://docker-minecraft-server.readthedocs.io/en/latest/types-and-platforms/ | authority:primary] [src:https://docker-minecraft-server.readthedocs.io/en/latest/mods-and-plugins/ | authority:primary]; and "all known server.properties entries can be managed by the environment variables" [src:https://docker-minecraft-server.readthedocs.io/en/latest/configuration/server-properties/ | authority:primary].

**RCON is on by default and is the canonical itzg console path.** "RCON is enabled by default to allow for graceful shut down of the server and coordination of save state during backups," default password is randomly generated each startup, default RCON port is 25575 inside the container, and the docs warn "BE CAUTIOUS OF MAPPING THE RCON PORT EXTERNALLY" [src:https://docker-minecraft-server.readthedocs.io/en/latest/configuration/server-properties/ | authority:primary]. The intended console UX is `docker exec -i mc rcon-cli` for interactive use (with `-i` required) and `docker exec mc rcon-cli stop` for one-shot commands [src:https://docker-minecraft-server.readthedocs.io/en/latest/sending-commands/commands/ | authority:primary].

**Stdin/TTY attach is the alternative console path.** The official compose example sets `stdin_open: true` and `tty: true` along with `restart: unless-stopped`, image `itzg/minecraft-server`, env `EULA: "true"`, port `25565:25565`, and a named volume `data` mounted at `/data` [src:https://github.com/itzg/docker-minecraft-server/blob/master/docker-compose.yml | authority:primary]. With `-it` set, you can `docker attach <name>` and detach with Ctrl-p Ctrl-q [src:https://docker-minecraft-server.readthedocs.io/en/latest/sending-commands/commands/ | authority:primary].

**Generic Docker panels expose console via a web terminal but have no Minecraft semantics.** Dockge advertises "Interactive Web Terminal" alongside compose stack create/edit/start/stop/restart/delete and `docker run → compose.yaml` conversion, with the file-based principle "Dockge won't kidnap your compose files, they are stored on your drive as usual" [src:https://github.com/louislam/dockge | authority:primary]. In a Dockge/Portainer workflow you author a compose stack pointing at `itzg/minecraft-server`, mount `/data` to a host path or named volume for backups, and reach the console either by `docker exec -i ... rcon-cli` from the panel's terminal or by `docker attach` if `tty: true` and `stdin_open: true` are set [src:https://github.com/itzg/docker-minecraft-server/blob/master/docker-compose.yml | authority:primary] [src:https://docker-minecraft-server.readthedocs.io/en/latest/sending-commands/commands/ | authority:primary].

### Tradeoffs / counter-evidence found

- **Pterodactyl egg model vs. itzg image model are philosophical opposites.** Pterodactyl's images are deliberately *thin* runtimes (a Java version, a `container` user, an entrypoint that just `eval`s `${STARTUP}`), and the *Egg* carries the install script (`curl` the JAR, write `server.properties`, etc.) [src:https://pterodactyl.io/community/config/eggs/creating_a_custom_image.html | authority:primary] [src:https://eggs.pterodactyl.io/egg/games-paper/ | authority:primary]. The itzg image is the inverse: a *fat* image whose entrypoint does version selection, downloading, and config templating from env vars [src:https://github.com/itzg/docker-minecraft-server | authority:primary] [src:https://docker-minecraft-server.readthedocs.io/en/latest/configuration/server-properties/ | authority:primary]. Running itzg under Pterodactyl means fighting both layers; running Pterodactyl-style thin images under a generic Docker panel means re-implementing what the Egg used to do.
- **PufferPanel's Docker mode disables the image entrypoint.** That is documented as a feature for security/consistency, but it directly defeats `itzg/minecraft-server`, which expects its entrypoint to run [src:https://docs.pufferpanel.com/en/2.x/environments/docker.html | authority:primary] [src:https://github.com/itzg/docker-minecraft-server | authority:primary].
- **Minecraft barely uses Pterodactyl's port model — Wings still wastes the UDP allocation.** Even though Java Edition is TCP-only, Wings binds both protocols on the allocated port [src:https://github.com/pterodactyl/panel/issues/4850 | authority:primary]. For a Java-Minecraft-focused panel this is dead weight; for a Bedrock panel the opposite (UDP-only) would be wasted.
- **RCON-on-by-default is convenient but a foot-gun.** itzg's docs warn loudly against publishing the RCON port externally because the default password is random per startup unless explicitly set [src:https://docker-minecraft-server.readthedocs.io/en/latest/configuration/server-properties/ | authority:primary]. A Minecraft-aware panel can hide the password and proxy the console safely; a generic Docker panel just gives you a terminal.

### Gaps (no source found)

- I could not retrieve a specific primary doc enumerating PufferPanel's standard JVM image used by its Java-server templates after 2.6 (the search summary mentioned "Eclipse JVM" but I did not find the canonical doc page that names it).
- No primary source fetched for what "exec into container" actually looks like in Portainer's UI specifically (the OneUptime blog discussed it but I did not WebFetch it; treat the Portainer-specific UX as not directly cited beyond the Dockge "Interactive Web Terminal" reference).
- No primary doc was retrieved on Pterodactyl Wings' specific Docker network bridge naming (the Minecraft proxy guide referenced `172.18.0.1` as the in-container reach-back address but only as proxy-config advice, not as a general networking spec) [src:https://pterodactyl.io/community/games/minecraft.html | authority:primary].

### Raw sources consulted

- https://pterodactyl.io/wings/1.0/installing.html (primary)
- https://github.com/pterodactyl/wings (primary)
- https://pterodactyl.io/community/config/eggs/creating_a_custom_egg.html (primary)
- https://pterodactyl.io/community/config/eggs/creating_a_custom_image.html (primary)
- https://github.com/pterodactyl/yolks (primary)
- https://eggs.pterodactyl.io/egg/games-paper/ (primary)
- https://github.com/pterodactyl/panel/issues/4850 (primary)
- https://pterodactyl.io/community/games/minecraft.html (primary)
- https://docs.pufferpanel.com/en/2.x/environments/standard.html (primary)
- https://docs.pufferpanel.com/en/2.x/environments/docker.html (primary)
- https://docs.pufferpanel.com/en/2.x/templates/templates.html (primary)
- https://docs.pufferpanel.com/en/3.x/templates/templates.html (primary)
- https://docs.pufferpanel.com/en/3.x/release-notes/3.0.0.html (primary)
- https://github.com/itzg/docker-minecraft-server (primary)
- https://github.com/itzg/docker-minecraft-server/blob/master/docker-compose.yml (primary)
- https://docker-minecraft-server.readthedocs.io/en/latest/ (primary)
- https://docker-minecraft-server.readthedocs.io/en/latest/variables/ (primary)
- https://docker-minecraft-server.readthedocs.io/en/latest/configuration/server-properties/ (primary)
- https://docker-minecraft-server.readthedocs.io/en/latest/types-and-platforms/ (primary)
- https://docker-minecraft-server.readthedocs.io/en/latest/mods-and-plugins/ (primary)
- https://docker-minecraft-server.readthedocs.io/en/latest/sending-commands/commands/ (primary)
- https://github.com/louislam/dockge (primary)
agentId: ab4edb1fc9b676ada (use SendMessage with to: 'ab4edb1fc9b676ada' to continue this agent)
<usage>total_tokens: 48485
tool_uses: 37
duration_ms: 246936</usage>