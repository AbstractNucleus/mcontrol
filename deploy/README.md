# Deployment

The hosted app pulls `ghcr.io/abstractnucleus/mcontrol` using `deploy/compose.yml`. The repo-root `docker-compose.yml` builds from source for local development. Both use the Compose project name `mcontrol`; keep their ports and mounts consistent.

The configured host is `bserver`, with Compose files in `/home/abstract/deploy/mcontrol`. The existing address is https://mcontrol.noelkleen.com. Moving to `dash.noelkleen.com` is a separate deployment change.

## Host configuration

Copy `deploy/compose.yml` to the deployment directory and preserve the host's existing `.env`. A new host needs these values:

| Key | Purpose |
| --- | --- |
| `TAG` | Published `sha-<short commit>` tag; `latest` is also available |
| `SUPABASE_URL` | Supabase endpoint |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-side Supabase credential |
| `SERVER_BASE_PATH` | Minecraft server directory; `/home/abstract/servers/minecraft` on bserver |
| `HOST_BIND_IP` | Interface used by the reverse proxy; `100.124.22.82` on bserver |

`SERVER_BASE_PATH` must be the same absolute path inside and outside the container. Discovery scans its immediate subdirectories. Do not point it at a parent containing unrelated applications.

The app mounts that directory and `/var/run/docker.sock` read-write. It listens on container port 8000 and host port 8003. Terminate TLS and enforce access control at the upstream reverse proxy. The Supabase schema is maintained outside this repository.

## Publish and update

1. Run the checks in [CONTRIBUTING.md](../CONTRIBUTING.md), including browser checks for UI changes.
2. Push the reviewed commit to `main`. `.github/workflows/publish-image.yml` tests and publishes the Linux amd64 image. Record the exact `sha-<short commit>` tag from its run summary.
3. Confirm the host can pull the image. The current setup uses a public GHCR package and no registry credentials on bserver.
4. Record the running image revision and current `TAG` before updating:

   ```sh
   cd /home/abstract/deploy/mcontrol
   docker compose images
   docker inspect mcontrol-app-1 --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
   ```

5. Set `TAG` in the host's `.env` to the selected published tag, then run:

   ```sh
   docker compose pull
   docker compose up -d --wait
   docker compose ps
   ```

6. Verify `/healthz`, the image revision, and the app in the browser. For mcontrol, check fleet status, a running and stopped server, console connections, file viewing, roster, and Settings. Use fixtures for test writes rather than live servers.

`/healthz` checks Supabase, Docker, and the server-directory mount. A degraded subsystem returns 503. `--wait` reports a failed health check instead of silently leaving an unhealthy deployment.

## Rollback

Restore the previous published SHA tag in the host's `.env`, then repeat `docker compose pull` and `docker compose up -d --wait`. Verify health and revision again. No source checkout or build on the host is needed.

Find published tags in the workflow summary:

```sh
gh run list --workflow publish-image.yml
gh run view <run-id>
```

Local `docker image ls` only shows images already pulled to that host.

## First publish

The GHCR package exists only after the workflow has published once. Check anonymous pulling from a machine without registry credentials. If the package is private, its visibility is managed in [GitHub package settings](https://github.com/users/AbstractNucleus/packages/container/mcontrol/settings).

The container starts `/app/.venv/bin/uvicorn` directly. It does not install dependencies at startup.
