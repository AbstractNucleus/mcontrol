# Slice 9 — Per-server resource visibility

> Lean plan: contract + PR order. Each PR ships an end-to-end working vertical slice; merge in order. The code is the source of truth — this doc is the napkin sketch.

## Goal

Operator opens a server detail page and sees CPU %, memory used vs the cgroup limit, and disk usage of the server directory (which contains the bind-mount tree plus the small scaffold files). The motivating case is decision 009's memory-budget cap: the panel writes `mem_limit` and `-Xmx`, but until now nothing surfaces live usage against the cap, which is exactly the visibility the operator was missing on `monifactory`'s exit-137 OOM (decision 014). One inline card on the detail page, polled via HTMX. No history, no alerts, no host dashboards.

## Scope contract

| | |
|---|---|
| Surface | Inline card on `/servers/{name}` detail page only. No home-page column this slice. |
| Numbers shown | CPU % (aggregated across cores, `docker stats`-style), memory used, memory limit, memory used / limit %, disk-usage bytes of `<dir>/` (the row's `dir`, which contains both the scaffold files and the bind-mounted `server/` subtree per decision 008). |
| CPU + memory source | Docker Engine API `/containers/{id}/stats?stream=false` via the existing `aiodocker` client — single snapshot per render. Picked over shelling out to `docker stats --no-stream`: aiodocker is already a dep, the panel image doesn't ship the docker CLI, parsing JSON is cheaper than parsing tabular text, and it keeps decision 006's "direct socket" posture intact. |
| Disk source | `os.scandir`-based recursive walk of `<dir>/`. Picked over `du -sb`: stdlib (no shell-out, no `du` dependency in the panel image), straightforward to test on `tmp_path`, and trivially symlink-safe (`follow_symlinks=False`). |
| Memory limit source | Same `stats?stream=false` payload (`memory_stats.limit`) — that's what Docker is actually enforcing on the container right now. No separate `inspect` call. No fallback to compose-rendered `mem_limit`: when the container isn't running, the card shows "—" for all four numbers and the operator's next move is Start, not "guess the would-be limit." |
| Refresh model | HTMX `hx-trigger="load, every 5s"` on the card, swapping `/servers/{name}/resources` into itself. Same pattern slice 7 uses for the per-server Players card. Polling stops automatically when the operator navigates away. |
| Caching | None. Each render does one stats call + one scandir walk. At single-host / ~6-server / typical-modpack-size scale the scandir is sub-second; if it ever becomes a problem, the fix is a "Refresh disk" button and dropping disk from the auto-poll, not a cache layer. |
| Not-running fallback | Container-derived numbers (CPU, mem used, mem limit, mem %) render as "—" with a one-line "container not running" caption. Disk still renders — it's filesystem state, not container state. |
| Daemon-unreachable fallback | Same shape as not-running: container-derived numbers blank, disk still renders, caption "Docker daemon unreachable." Distinguished from not-running by `read_container_stats` returning `{"status": "unreachable"}` instead of `{"status": "not-running"}`; both states swallow exceptions and surface a legible empty state, matching `docker_client.container_states_by_name()`'s posture. |
| Legacy gating | None. The card renders on every server (legacy + scaffolded), keyed off the container resolved through `db.container_name_for(row)` per decision 021. |
| CPU % formula | `cpu_delta = cpu_stats.cpu_usage.total_usage − precpu_stats.cpu_usage.total_usage`; `system_delta = cpu_stats.system_cpu_usage − precpu_stats.system_cpu_usage`; `cpu_percent = (cpu_delta / system_delta) × online_cpus × 100` when both deltas > 0, else 0. Matches `docker stats`. |
| Memory used formula | `memory_stats.usage − memory_stats.stats.inactive_file` when `inactive_file` is present (cgroup v2 / modern v1), else `memory_stats.usage − memory_stats.stats.cache` when `cache` is present, else `memory_stats.usage` raw. `docker stats` does the same fallback dance. |
| Path-safety | Disk walk is rooted at `Path(server["dir"]).resolve()`. The slug regex from slice 6 already gates `name`; `dir` comes from the DB row that discovery / scaffolding set, never from the URL. Walk uses `follow_symlinks=False` so an operator-introduced symlink can't redirect the walk outside the bind-mount. |
| Health banner | No new issue types this slice. A daemon-unreachable or container-not-running state is a transient runtime fact, not a scaffold-integrity issue, and the resource card's own caption is the right place to surface it. |

## Card shape

Rendered into `_resources_card.html`. Layout:

```
Resources
─────────────────────────────────────────────
 CPU       12.4 %
 Memory    8.1 / 12.0 GiB   (68 %)
 Disk      4.7 GiB
 ─ updated 14:02:07 (every 5 s)
```

When the container isn't running:

```
Resources
─────────────────────────────────────────────
 CPU       —
 Memory    —
 Disk      4.7 GiB
 ─ container not running
```

Bytes render through a tiny `format_bytes(n)` helper in the module — base-1024, two significant digits, KiB/MiB/GiB/TiB.

## Routes

```
GET    /servers/{name}/resources    → renders _resources_card.html (HTMX-fetchable)
```

Single endpoint. No POSTs — resources are read-only.

## Modules

```
src/mcontrol/
  resources.py                # read_container_stats(name) + read_disk_usage(dir) + format_bytes(n).
  routes/
    server_resources.py       # GET /servers/{name}/resources → renders the card.
  templates/
    _resources_card.html      # inline card; HTMX-swappable.
```

Route file is `server_resources.py` (not `resources.py`) to avoid a top-level name collision with the `mcontrol.resources` module — same convention as slice-7's `routes/server_players.py` next to `mcontrol.membership`.

`resources.py` owns both reads and the byte formatter. Tests in `tests/test_resources.py`:

- `read_disk_usage` on `tmp_path` with nested files, hidden files (`.`-prefixed), and symlinks (assert symlinks contribute only their own link-inode size — `follow_symlinks=False` means the target's bytes are not counted, and a symlink to a directory is not recursed into).
- `read_container_stats` with a faked aiodocker client returning a canned stats dict — assert the CPU and memory math against known inputs, including the cgroup-v1 vs v2 `cache` / `inactive_file` branches and the zero-delta first-tick edge.

## PR sequence

| # | Ships | Notes |
|---|---|---|
| 0 | `resources.py` module | Pure functions: `read_container_stats(container_name) -> dict`, `read_disk_usage(server_dir: Path) -> int`, `format_bytes(n: int) -> str`. Stats returns a tagged dict: `{"status": "ok", "cpu_percent", "mem_used", "mem_limit"}` on success, `{"status": "not-running"}` when the container exists but isn't running, `{"status": "unreachable"}` when the daemon is unreachable or the container is missing entirely. Three states so the card caption can be specific without the route having to call back into `docker_client` to disambiguate. Tests on tmp_path + faked aiodocker. No UI, no routes. |
| 1 | Resource card on detail page | `routes/server_resources.py` registers `GET /servers/{name}/resources`, resolves container via `db.container_name_for(row)`, calls both reads, renders `_resources_card.html`. Detail page mounts the card with `<section id="server-resources" hx-get=".../resources" hx-trigger="load, every 5s" hx-swap="outerHTML"></section>` — same pattern as the players card. Card position: directly under the lifecycle row (state pill + Start/Stop/Restart) and above the metadata `<dl>`, so live status sits with lifecycle controls in one diagnostic cluster. |

## Pre-flight (before PR 0 deploys)

None. No DB migration, no decision change, no new external dependency, no new socket mount. The Docker socket is already mounted (decision 006); the bind-mount path is already settable via `SERVER_BASE_PATH` and recorded in `servers.dir`.

## Path-safety contract

Carried over; restated for the new read site:

1. `name` (server name) gates entry into `/servers/{name}/resources` via the same slug regex used by slice 6 / 7.
2. The disk walk roots at `Path(server["dir"]).resolve()` — `dir` is set by discovery or scaffolding, not by the URL, so traversal payloads can't reach it.
3. `os.scandir(..., follow_symlinks=False)` and `entry.stat(follow_symlinks=False)` ensure operator-introduced symlinks inside the bind-mount don't redirect the walk outside it or double-count linked files.

## Decisions register impact

This slice introduces **no new decision**. The data-source choices fall directly out of existing decisions:

- **006** Direct `/var/run/docker.sock` mount — picks Engine-API stats over `docker stats` shell-out.
- **008** Bind mounts at `~abstract/servers/minecraft/<name>/` — `dir` is a real host path, so an `os.scandir` walk is meaningful and trivial.
- **009** Single memory-budget knob — this slice is the missing live-readout half. The card surfaces what the budget actually permits and what the container actually uses, so the OOM context behind decision 014 becomes legible before exit-137 happens.
- **016** FastAPI + Jinja + HTMX — card is a `hx-trigger="every 5s"` swap in the established pattern.
- **021** Per-server `container_name` override — resource lookup goes through `db.container_name_for(row)`, so a re-pointed row reads the right container's stats.
- **023** No-Dockerfile scaffold — irrelevant to this slice; resource reads work identically on scaffolded and legacy rows.

If a future slice adds historical retention, alerting, or a host-level dashboard, that slice introduces its own decision (likely "metrics retention is out-of-scope for v1" superseded by something concrete). Today's slice doesn't need one — the contract is "read-on-render, single-card, single-page," which is small enough to be self-evident from the code.

## Deferred / out-of-scope

- **Historical graphs / time-series.** No retention store, no Prometheus, no rrdtool. The card shows now; if it becomes important to see "memory over the last hour while the OOM was building," that's a future slice with its own decision (and almost certainly an external time-series store, not in-app storage).
- **Alerts.** No "ping me when memory > 90 %." Single operator on tailnet; the felt need is glance-on-page, not async notification.
- **Home-page resource column.** Six servers each triggering a stats call + scandir on every home render is a meaningful first-byte hit for the page operators land on. Defer until the felt need exists; the detail page is the natural diagnosis surface.
- **Network IO, block IO, PIDs.** Stats payload includes them; the card doesn't render them. Add when a real failure mode points at them.
- **Per-process / JVM-internal stats.** Heap usage, GC counts, thread counts — would require RCON `/forge tps` / `/spark` / JMX exporter, none of which are wired up. Operator can drop a profiling mod into `mods/` per decision 017's "delegate to plugins/mods" posture.
- **Per-disk breakdown** (mods vs world vs backups). One total bytes number is enough for the cap-watching use case. Operator inspects via the slice-5 file browser when they want to know what's eating disk.
- **Host-level dashboard.** Free RAM on the host, host CPU load, host disk free. mcontrol is a per-server panel; host-level visibility is a different tool's job.
- **Multi-host.** Decision 005.
- **Caching layer.** No in-process cache, no Redis, no memoise-with-TTL. If a future scandir-on-poll causes user-visible latency, the fix is a "Refresh disk" button and removing disk from the auto-poll, not a cache.
- **CPU per-core breakdown.** Aggregated `docker stats`-style percent only.
- **Custom poll cadence.** `every 5s` is hard-coded. If the operator ever wants "slower" or "pause polling," that's a small follow-up — for now, navigating away stops the polling, which covers the only realistic concern.
- **Resource card on the home page's compose-up flow / new-server form.** Not meaningful before the container exists.

## Resolved during grilling

1. **Stats source — Engine API vs `docker stats` shell-out:** Engine API. aiodocker is already in the codebase (`docker_client.py`), the panel image deliberately doesn't ship the docker CLI binary (only the socket is mounted, decision 006), and parsing the JSON payload is structurally cleaner than parsing tabular text whose column widths shift with longer container names. The shell-out alternative would force a panel-image dependency for no functional gain.
2. **Disk source — `os.scandir` vs `du -sb`:** `os.scandir`. Stdlib (no `du` dependency in the panel image), trivially testable on `tmp_path`, and `follow_symlinks=False` is a single kwarg vs argv-bothering with `du`'s `-x` / `-l` flags. Cost: a Python loop is a few times slower than `du`'s C; at ~6 servers and modpack-sized worlds (single-digit GB), the absolute time is sub-second either way.
3. **Memory limit source — stats payload vs container inspect vs compose-rendered config:** stats payload (`memory_stats.limit`). It's already in the response we have to call anyway, and it reflects what the cgroup is enforcing right now — not what the compose file says it should be. When the container isn't running there's no limit to surface; the card shows "—" and the operator's next move is Start, not "guess the would-be limit."
4. **Refresh model — auto-poll vs SSE vs operator-click-refresh:** `hx-trigger="load, every 5s"` HTMX poll. Auto-poll is what you want when you're watching memory climb during a startup spike or near a cap; click-refresh adds friction at exactly the wrong moment. SSE gives push semantics but the data is genuinely point-in-time (each tick is a fresh stats call regardless), so the SSE machinery would buy nothing over poll. Polling stops automatically when the operator navigates away.
5. **Poll cadence — 1s vs 5s vs 15s:** 5s. 1s is `docker stats`'s default but it's noisy on the eye and the stats endpoint itself takes ~1s to compute its delta, so a 1s poll is effectively as-fast-as-possible with no headroom for a slow scandir. 15s is too slow for "watching the climb." 5s feels like the right shape for human-in-the-loop diagnosis and matches the cadence other slices have implicitly settled on for HTMX swaps.
6. **Caching — none vs in-process TTL vs separate disk cache:** none. Stats is already a fresh call per render by definition; caching the disk walk to amortise it across polls saves CPU but invents a staleness story (operator deletes 10 GB of mods, when does the card update?). Single-host scale doesn't justify the complexity — recompute on every render is the simplest thing that's correct, and the escape hatch (a "Refresh disk" button + dropping disk from the auto-poll) is a one-PR change if it ever bites.
7. **Surface — detail page only vs detail + home column vs home only:** detail page only. The home page is the operator's landing — six servers each triggering a stats call + scandir would add a measurable first-byte hit for marginal benefit; the operator opens a server's detail page when they're actually diagnosing, and that's where the card belongs. Adding a home column later is non-disruptive once the read functions exist.
8. **Card position on detail page — top (with lifecycle) vs middle (with cards) vs bottom (with logs):** top, directly under the lifecycle row. The diagnosis loop is "look at state, look at memory, decide whether to restart" — those should sit together. Burying it below the file/log/console panes would mean scrolling to find the data that motivates the click on the buttons at the top.
9. **Symlink handling in disk walk — follow vs don't:** don't. `follow_symlinks=False` on both `scandir` and `stat`. Avoids double-counting (an operator-introduced symlink to an external backup dir would otherwise inflate the number) and avoids the walk escaping the bind-mount path-safety boundary. The trade-off — symlinked content inside the bind-mount appears as ~0 bytes — is a non-issue for normal MC server layouts where the bind-mount is the world.
10. **Health banner integration — new issue types vs caption-only:** caption-only. "Container not running" and "Docker daemon unreachable" are transient runtime facts, not scaffold-integrity issues; mixing them into the health banner would dilute its current "the scaffold is broken" semantics. The card's own caption is the right place — it's contextual to the data the operator was just trying to read.
11. **Pause-polling control — yes vs no:** no. Navigating away stops the polling automatically (HTMX poll lives on a DOM node), which covers the only realistic concern. Adding a "pause" button is UI surface for a felt need that doesn't exist on a single-operator panel.
12. **Caption derivation — DB `state` column vs live stats result:** live stats result. The stats function returns `{"status": "ok"|"not-running"|"unreachable"}`, and the route maps that directly to the caption. The DB `state` column is updated by discovery and can lag (or be "unknown" wholesale during a daemon outage), so deriving the caption from `state` would mean "stopped" sometimes shows when the container is actually mid-pull. Live stats is the source of truth for what the card is showing right now.
