# mcontrol

Extracted from `admin_management`.

See [`research/2026-04-26-minecraft-and-docker-control-panels/`](research/2026-04-26-minecraft-and-docker-control-panels/README.md) for the panel-landscape research that informs the build direction, and [`docs/decisions.md`](docs/decisions.md) for the decisions register that follows from it.

UI uses [`AbstractNucleus/design`](https://github.com/AbstractNucleus/design) as the design palette — warm paper, rust accent, monospaced throughout.

## Local development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env  # then edit .env with real values
uv run uvicorn mcontrol.main:app --reload --port 8000
```

Visit `http://localhost:8000/` for the home page and `http://localhost:8000/healthz` for a status check.

Run tests:

```bash
uv run pytest -v
```

Lint:

```bash
uv run ruff check .
```

Re-pull the AbstractNucleus design tokens:

```bash
./scripts/sync_design.sh
```

## Deployment

The default deployment shape is Docker + Caddy, with Caddy obtaining a Let's Encrypt cert via Cloudflare DNS-01 over the tailnet — see [`docs/patterns/tailnet-https-via-cloudflare.md`](docs/patterns/tailnet-https-via-cloudflare.md).

```bash
docker compose up -d --build
```

Pre-requisites on the host:
- `mcontrol.noelkleen.com` DNS A record (gray cloud) pointing at the host's tailnet IP.
- `CF_API_TOKEN` env var with `Zone:DNS:Edit` scope on `noelkleen.com`.
- Tailscale running on the host.

The container exposes :8000 internally; Caddy fronts it on :80 / :443.
