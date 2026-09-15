# mcontrol

A lightweight web panel for managing a fleet of [itzg/minecraft-server](https://docker-minecraft-server.readthedocs.io/)-style Minecraft servers on a single Docker host.

mcontrol sits a thin Minecraft-aware UI over plain `docker compose`. No daemon agents, no per-server custom images, no opaque database of "eggs" or "templates". Each Minecraft server is a directory on disk with a `docker-compose.yml` and a bind-mounted `server/` folder. The panel reads, scaffolds, and edits those directories directly.

## What it does

- **Server lifecycle**: start / stop / restart with state-aware buttons and Docker-backed health, including a "starting" state that probes the listener port before reporting healthy. Start creates the container from the server's compose file when it does not exist yet.
- **Shared workspace**: configurable Console, Players, and Files panels with adjustable widths and heights, Save/Cancel, and temporary focus mode. Layouts are shared across servers in this browser and migrate from dashboard v2. Configuration lives in Settings.
- **Console**: independent log and command connections, search, severity filters, wrapping, pause-follow, and Jump to latest. Commands wait for a connection; rejected text stays in the input.
- **File browser**: read-only tree + CodeMirror editor (JSON / YAML / TOML / XML syntax highlighting), multi-file upload with drag-drop, rename/move with destination picker, single-file download, bulk delete and move, full-text search across `server/` with Ctrl/Cmd+P.
- **New-server scaffolding**: generate a working `docker-compose.yml` + `start_server.sh` for a fresh server in one form submit; no per-server Dockerfile. The form picks a Java version (17 / 21 / 25) and turns RCON on in `server.properties`.
- **Player roster**: DB-backed player list with Mojang UUID lookup, per-server whitelist / ops membership, and an Import button to ingest existing `whitelist.json` / `ops.json`.
- **Resource visibility**: observed status, CPU, memory, uptime, and freshness every five seconds while visible. Disk refreshes independently every minute. Failed requests retain prior content with stale feedback and Retry after a 12-second deadline. The fleet supports status filters.
- **Discovery**: operator-triggered fleet rescan that picks up new server directories without restarting the panel.
- **Deleted servers**: deletion renames the directory to `.deleted-<name>-<unix-ts>/`. Recover manually by renaming it back, then rescanning. Empty trash selects directories older than seven days; cleanup only runs when requested and confirmed.
- **Legacy-server migration**: one-way migrate card for servers that were running before mcontrol existed (itzg-image shape to mcontrol scaffold shape).
- **Health probe**: `GET /healthz` returns a deep per-subsystem JSON (Supabase + Docker socket + bind-mount); 503 on any subsystem degraded.
- **Interface**: inspired by [Beautiful UI](https://www.beautifului.dev/), with a fixed dark appearance, live fleet summary cards, status filters, and rounded workspace panels. A mobile drawer, stacked fleet cards, and a single-view file browser/editor adapt the workspace to phones.

### Modpacks with a start script

When creating a server, enter the pack's Linux `.sh` filename in **Custom start
script**, for example `run.sh`, instead of supplying a server jar. After creation,
copy the extracted server pack into the server's `server/` folder, keeping its
folders intact. The script path is relative to that folder.

mcontrol runs the script with Bash from `server/`. Keep the generated
`start_server.sh`; it launches the pack's script. If the pack uses that same
filename, rename the pack's script and enter its new name in the form.
Windows `.bat` scripts cannot be used in the Linux container.

The selected Java version and container memory limit still apply. Set the Java
heap and JVM flags in the pack's script or its settings file, leaving room within
the container limit for memory outside the heap. The form's JVM extra arguments
apply only to jar startup. Scripts that need additional programs require those
programs to be available in the runtime image.

You can change the script path later in **Variables**. Clear it and select a
server jar to return to jar startup.

## Who it's for

You self-host Minecraft servers in Docker on a single box and want:
- A panel that doesn't impose its own server-image abstraction (no daemons, no eggs).
- Source you can read end-to-end in an afternoon (~6k lines of Python + Jinja + HTMX).
- A file browser that edits the same files you'd edit over SSH.
- A roster system that works without an external auth provider.

mcontrol is **not** a multi-tenant control panel. There's no user/role system; anyone who can reach the panel can do everything. Run it behind your own auth (Tailscale, Cloudflare Access, basic auth at the reverse proxy, etc.).

## Architecture

- **Backend**: FastAPI + Jinja2 + HTMX (server-rendered, minimal client JS).
- **Storage**: Supabase (Postgres + service-role key) for the servers table, player roster, and tombstones.
- **Docker integration**: `aiodocker` against `/var/run/docker.sock`; per-server compose files live on disk under `SERVER_BASE_PATH/<name>/`.
- **Frontend**: HTMX for interaction, CodeMirror (vendored) for the file editor, no bundler.

## Local development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SERVER_BASE_PATH
uv run uvicorn mcontrol.main:app --reload --port 8000
```

Visit `http://localhost:8000/` for the home page. `http://localhost:8000/healthz` returns 200 with per-subsystem JSON when DB, Docker socket, and base path are all reachable; 503 otherwise.

Run tests:

```bash
uv run pytest -v
```

Lint:

```bash
uv run ruff check .
```

Tests mock out Supabase and the Docker socket; you do not need either available to run the suite.

Browser regression checks start an isolated `dev_mock` process with temporary server files:

```bash
uv run playwright install chromium
MCONTROL_BROWSER_TESTS=1 uv run pytest tests/browser -v
```

PowerShell: set `$env:MCONTROL_BROWSER_TESTS='1'` before the pytest command. Screenshots are saved to `.localdev/ui-review/`. Tests cover the fixed dark interface from 390 to 1920 pixels under either operating-system color scheme, layout migration/cancellation, dirty editors, failed saves, retry recovery, connection state, and keyboard access. Additional cases check dark rendering with saved light preferences, blocked storage, and JavaScript disabled, plus the roster, server creation, trash confirmations, short-screen sidebar controls, static asset loading, and fleet filters during an in-flight refresh.

## Deployment

The hosted instance pulls a GHCR image using `deploy/compose.yml`; follow [deploy/README.md](deploy/README.md) and the [redesign release checks](deploy/UI_REDESIGN_RELEASE.md). The root compose file below is for builds from source.

The tracked `docker-compose.yml` runs only the `app` service. The container exposes `:8000` internally and binds to `${HOST_BIND_IP:-127.0.0.1}:8003` on the host. Terminate TLS at an upstream reverse proxy (nginx, Caddy, Traefik, etc.) and `proxy_pass` to that host:port.

```bash
docker compose up -d --build
```

Pre-requisites:
- A Supabase project (the schema lives in a separate migration outside this repo).
- An upstream reverse proxy that terminates TLS and reverse-proxies to `HOST_BIND_IP:8003`.
- A `.env` populated from `.env.example`.
- Your own access control in front of the panel. See "Who it's for" above.

The container needs `/var/run/docker.sock` and the host's `SERVER_BASE_PATH` bind-mounted read-write so it can manage per-server containers and scaffold/edit files.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev loop, route-adding pattern, and project conventions.

## License

MIT. See [LICENSE](LICENSE).
