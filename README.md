# mcontrol

Extracted from `admin_management`.

See [`research/2026-04-26-minecraft-and-docker-control-panels/`](research/2026-04-26-minecraft-and-docker-control-panels/README.md) for the panel-landscape research that informs the build direction, and [`docs/decisions.md`](docs/decisions.md) for the decisions register that follows from it.

UI is a Claude-flavoured theme (decision 032) with full dark + light mode support — warm cream `#FAF9F5` page in light mode, near-black `#141413` in dark mode, terracotta `#D97757` accent, Inter-Tight body type with mono kept for code/log/RCON. Tokens live in `src/mcontrol/static/tokens.css`. The reference notes that informed the palette are at [`docs/research/2026-05-10-claude-theme/`](docs/research/2026-05-10-claude-theme/).

## Local development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env  # then edit .env with real values
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

## Deployment

The tracked `docker-compose.yml` runs only the `app` service. TLS termination happens upstream at aserver-nginx, not inside this repo — see [decision 019](docs/decisions.md#019-tls-termination-at-aserver-nginx-not-in-repo-caddy). The container exposes `:8000` internally; bind it to a host LAN port through a per-host `docker-compose.override.yml` (gitignored) and reverse-proxy to it from the upstream nginx.

Bring up the app:

```bash
docker compose up -d --build
```

Pre-requisites:
- An upstream HTTPS terminator on the tailnet that reverse-proxies to this container's LAN port. The canonical setup for `mcontrol.noelkleen.com` is aserver-nginx with a Let's Encrypt cert renewed via certbot's Cloudflare DNS-01 plugin (see [`docs/patterns/tailnet-https-via-cloudflare.md`](docs/patterns/tailnet-https-via-cloudflare.md) for the conceptual pattern — the doc's Caddy examples translate one-for-one to nginx + certbot).
- `mcontrol.noelkleen.com` DNS A record (gray cloud) pointing at the terminator host's tailnet IP.
- Tailscale running on both the terminator host and the app host.
- A `.env` populated from `.env.example` (Supabase URL + service-role key + `SERVER_BASE_PATH`).

Local dev without a terminator: bind the app port directly to `127.0.0.1:8000` via an override file and visit `http://localhost:8000/`. There is intentionally no out-of-the-box self-terminating shape — see decision 019 for why.
