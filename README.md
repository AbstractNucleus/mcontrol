# mcontrol

A lightweight web panel for managing a fleet of [itzg/minecraft-server](https://docker-minecraft-server.readthedocs.io/)-style Minecraft servers on a single Docker host.

mcontrol sits a thin Minecraft-aware UI over plain `docker compose`. No daemon agents, no per-server custom images, no opaque database of "eggs" or "templates". Each Minecraft server is a directory on disk with a `docker-compose.yml` and a bind-mounted `server/` folder. The panel reads, scaffolds, and edits those directories directly.

## What it does

- **Server lifecycle**: start / stop / restart with state-aware buttons and Docker-backed health, including a "starting" state that probes the listener port before reporting healthy.
- **Live RCON console**: SSE-backed terminal that auto-connects on page load and reads the RCON password from `server.properties`.
- **Live log stream**: tail container logs via SSE without polling.
- **File browser**: read-only tree + CodeMirror editor (JSON / YAML / TOML / XML syntax highlighting), multi-file upload with drag-drop, rename/move with destination picker, single-file download, bulk delete and move, full-text search across `server/` with Ctrl/Cmd+P.
- **New-server scaffolding**: generate a working `docker-compose.yml` + `start_server.sh` for a fresh server in one form submit; no per-server Dockerfile.
- **Player roster**: DB-backed player list with Mojang UUID lookup, per-server whitelist / ops membership, and an Import button to ingest existing `whitelist.json` / `ops.json`.
- **Resource visibility**: CPU %, memory, and disk usage per server, plus per-row memory on the home page.
- **Discovery**: operator-triggered fleet rescan that picks up new server directories without restarting the panel.
- **Trash & tombstones**: delete-server flow renames to a `.tombstone-` prefix so the row is recoverable; trash page lists tombstones with per-row Delete-now and bulk Empty-trash (7-day default).
- **Legacy-server migration**: one-way migrate card for servers that were running before mcontrol existed (itzg-image shape to mcontrol scaffold shape).
- **Health probe**: `GET /healthz` returns a deep per-subsystem JSON (Supabase + Docker socket + bind-mount); 503 on any subsystem degraded.
- **Theme**: dark / light / system toggle persisted to `localStorage`.

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

## Deployment

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
