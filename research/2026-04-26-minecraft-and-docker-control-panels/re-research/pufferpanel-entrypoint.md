# Re-research: pufferpanel-entrypoint

Confirmed — the official PufferPanel minecraft template builds its own server (does its own version downloads, does its own jvm command), not using itzg. No `itzg` references appear anywhere in the pufferpanel org. I now have everything needed.

### Re-research for: PufferPanel ENTRYPOINT bypass and itzg conflict
Status: **RESOLVED (with one caveat — see below)**

**The ENTRYPOINT-bypass claim is directly confirmed by primary sources.**

PufferPanel's own 3.x docs state it explicitly: *"PufferPanel does NOT use the images default entrypoint but rather creates a fresh container for the server, mounts in the server files and runs the run command defined for the server in PufferPanel in the root of the server files"* [src: https://docs.pufferpanel.com/en/3.x/environments/docker.html | authority: official PufferPanel 3.x docs].

This is mirrored in the source. In `servers/docker/docker.go` the daemon parses the panel's configured run command and assigns it directly to `containerConfig.Entrypoint`, overriding whatever the image declared:

```go
cmd, args := utils.SplitArguments(data.Command)
cmdSlice := strslice.StrSlice{}
if data.Command != "" {
    cmdSlice = append(cmdSlice, cmd)
    cmdSlice = append(cmdSlice, args...)
}
...
if len(containerConfig.Entrypoint) == 0 && len(cmdSlice) > 0 {
    containerConfig.Entrypoint = cmdSlice
}
```
[src: https://github.com/pufferpanel/pufferpanel/blob/main/servers/docker/docker.go | authority: PufferPanel main branch source]. Note the guard `len(containerConfig.Entrypoint) == 0` only protects an entrypoint set in PufferPanel's own container config (the per-server JSON's `environment` block) — not the image's baked-in ENTRYPOINT, which Docker's API replaces whenever the create-call sets a non-nil Entrypoint.

The same file also calls `d.cli.ContainerCreate(ctx, containerConfig, ...)` with that overridden `containerConfig`, confirming the create-time override path.

**The "fights itzg/minecraft-server" framing is inference, not directly cited.** A repo-search for "itzg" across `pufferpanel/pufferpanel`, `pufferpanel/templates`, and the rest of the pufferpanel org returns zero hits. The official `pufferpanel/templates` Minecraft template (`minecraft/minecraft.json`) defines its own `mojangdl`/Paper/Forge install steps and a hand-rolled `${java} -Xmx... -jar server.jar` run command — i.e., the canonical PufferPanel design assumes thin Java/SteamCMD/Ubuntu base images (see `pufferpanel/runtime-images` which only ships `java`, `steamcmd`, `ubuntu`) and a panel-driven launcher [src: https://github.com/pufferpanel/templates/blob/main/minecraft/minecraft.json | authority: official PufferPanel templates repo] [src: https://github.com/pufferpanel/runtime-images | authority: official PufferPanel runtime images repo].

The closest thing to a "user report" is issue #1077, where a user with *"an entrypoint with no default arguments in the Dockerfile"* hits a panic precisely because PufferPanel insists on supplying a run command — i.e., the architectural mismatch with self-launching images is real and observable, just not specifically against itzg [src: https://github.com/pufferpanel/pufferpanel/issues/1077 | authority: PufferPanel issue tracker]. And issue #1116 shows a user using `openjdk:17-alpine` (a thin base) with the standard panel-supplied jar/run pattern — again consistent with the design [src: https://github.com/pufferpanel/pufferpanel/issues/1116 | authority: PufferPanel issue tracker].

**Recommendation for the original write-up:** keep the ENTRYPOINT-override claim — it is documented and in source. Soften the itzg-specific framing to something like: *"By design, PufferPanel's Docker mode overrides the image's ENTRYPOINT with the panel-defined run command, so it expects thin base images (its own runtime-images ship only `java`/`steamcmd`/`ubuntu`). A self-launching 'fat' image like `itzg/minecraft-server`, whose own entrypoint performs version selection and templating, would have all of that bypassed — none of itzg's env-var-driven setup runs, and the user is back to writing a panel-side install/run pipeline."* That phrasing is fully supported by the cited primary sources without inventing a user report that does not appear to exist.

Key sources:
- https://docs.pufferpanel.com/en/3.x/environments/docker.html
- https://github.com/pufferpanel/pufferpanel/blob/main/servers/docker/docker.go (lines ~395–460)
- https://github.com/pufferpanel/pufferpanel/issues/1077
- https://github.com/pufferpanel/pufferpanel/issues/1116
- https://github.com/pufferpanel/templates/blob/main/minecraft/minecraft.json
- https://github.com/pufferpanel/runtime-images
agentId: a1bb6a9fe5f9a8c96 (use SendMessage with to: 'a1bb6a9fe5f9a8c96' to continue this agent)
<usage>total_tokens: 31267
tool_uses: 19
duration_ms: 127855</usage>