# Fix — mcontrol.noelkleen.com aserver vhost stale upstream

**Status:** broken. `https://mcontrol.noelkleen.com/` returns **502 Bad Gateway**.
**Root cause:** aserver's nginx vhost still upstreams to the pre-2026-04-30 LAN IP. Same shape as the supabase-server `api`/`studio` recovery on 2026-04-30 (see `~/code/supabase-server/docs/recoveries/2026-04-30-api-tls-tailnet-flip.md`); mcontrol was flagged as an out-of-scope side casualty in that recovery and never fixed.

## Diagnosis (from the supabase-server agent's audit, 2026-05-02)

aserver `/etc/nginx/sites-available/mcontrol.conf` upstreams to:

```
proxy_pass http://192.168.26.233:8003;
```

Both pieces are wrong:

- **`192.168.26.233`** is the pre-2026-04-30 bserver LAN IP. bserver currently has `192.168.26.232` (LAN, DHCP-volatile) and `100.124.22.82` (tailnet, stable). Decision 003 (`docs/patterns/tailnet-https.md` in the supabase-server repo) makes the tailnet IP the canonical host-bind target.
- **`:8003`** has no listener on bserver right now. The closest match in `docker ps` is `deploy-frontend-1` bound on `192.168.26.232:3001 -> 3000/tcp`, which may or may not be the mcontrol UI — operator confirmation needed.

The local `mcontrol/docker-compose.yml` only `expose:`s port 8000 from the `app` service (no host port binding). Whatever is currently running as `deploy-frontend-1` doesn't come from this compose file at root — likely deployed from a `~/repos/mcontrol/deploy/` (or similar) compose on bserver that's diverged from the local repo.

**Confirm the right port + container before applying the fix.** SSH bserver and look at `~/repos/mcontrol/` (or wherever your deployment lives) for the compose that produced `deploy-frontend-1`, and decide:

1. Should mcontrol's UI bind on `100.124.22.82:8003` (matching the existing aserver vhost), `100.124.22.82:3001` (matching the currently-running container), or some other port?
2. Should the deployment compose be aligned with the local repo, or is the deployed version intentionally newer/different?

The choice determines what port number to substitute below.

## Fix (two parts — bserver-side then aserver-side)

### Part 1 — bserver: bind the mcontrol UI on the tailnet IP

In whatever `.env` controls the mcontrol deployment (likely `~/repos/mcontrol/.env` or `~/repos/mcontrol/deploy/.env` on bserver), set the host-bind IP variable to bserver's tailnet IP:

```bash
BSERVER_LAN_IP=100.124.22.82      # misleading name, post-2026-04-30 it holds the tailnet IP
# add BSERVER_TS_IP=100.124.22.82 if your compose references it
```

If the compose file uses a literal IP rather than an env var, edit it to use `${BSERVER_LAN_IP}:<your-port>:<container-port>`. Match the port you decided on above.

Then:

```bash
ssh bserver
cd <path-to-mcontrol-deploy>
docker compose up -d --force-recreate
ss -tlnp | grep ':<your-port> '    # confirm 100.124.22.82:<your-port> is now listening
```

### Part 2 — aserver: update the nginx vhost upstream

Replace the stale upstream with the tailnet IP and the port you settled on. Substitute `<your-port>`:

```bash
ssh aserver
sudo sed -i.bak \
  's|http://192\.168\.26\.233:8003|http://100.124.22.82:<your-port>|g' \
  /etc/nginx/sites-available/mcontrol.conf
sudo grep proxy_pass /etc/nginx/sites-available/mcontrol.conf   # sanity check
sudo nginx -t && sudo systemctl reload nginx
```

If you used a different port on the bserver side, adjust the `sed` accordingly. Rollback if anything looks wrong:

```bash
sudo cp /etc/nginx/sites-available/mcontrol.conf.bak /etc/nginx/sites-available/mcontrol.conf
sudo systemctl reload nginx
```

## Verify

From any tailnet device:

```bash
curl -sk -o /dev/null -w '%{http_code}\n' https://mcontrol.noelkleen.com/
```

Expect a real status code from the app (200 / 302 / 401 — whatever mcontrol returns at `/`), not 502.

If still 502: `ssh aserver "sudo tail -20 /var/log/nginx/error.log"` will show the upstream the request actually tried — usually it's the bserver-side bind that didn't take.

## Optional cleanup (post-fix)

While you're in there, consider:

- **Bringing the deployed mcontrol on bserver back in line with the local repo** (or vice versa). The current divergence — local `docker-compose.yml` shows only `app:8000`, deployed container is `deploy-frontend-1:3000` — will keep biting whenever someone tries to reason about what's running.
- **Renaming `BSERVER_LAN_IP` → `BSERVER_HOST_BIND_IP`** at some quiet moment, with a follow-up env-var update on bserver. Inherited misleading name from the supabase-server repo's recovery.
- **Locking `mcontrol.conf` to listen on `<aserver-tailnet-ip>:443` only** if mcontrol is meant to be tailnet-only (per decision 003). The supabase-server repo's `docs/patterns/tailnet-https.md` is the canonical template.

## Reference

- `docs/patterns/tailnet-https.md` (in the `supabase-server` repo) — canonical pattern for new tailnet-only vhosts. Use this template if you ever rebuild mcontrol's vhost from scratch.
- `docs/recoveries/2026-04-30-api-tls-tailnet-flip.md` (in the `supabase-server` repo) — the original incident; "Out-of-scope side casualties" section listed mcontrol explicitly as needing this fix.
