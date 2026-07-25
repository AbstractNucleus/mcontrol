# deploy/

What bserver needs to run mcontrol. `compose.yml` here gets copied to
`/home/abstract/deploy/mcontrol/` and lives next to a `.env`.

The server holds no source and no build cache — it pulls the image that
`.github/workflows/publish-image.yml` publishes to `ghcr.io`.

## One-time setup

The order matters. A package's visibility cannot be set before the package
exists, and the package does not exist until the workflow has run once.

**1. Push to `main`.** `publish-image.yml` runs and creates
`ghcr.io/abstractnucleus/mcontrol`.

**2. Wait for the run to go green.** `gh run watch`

**3. Check the package is publicly pullable.** bserver holds no registry
credentials, so it can only pull anonymously. On the first publish this came
out public on its own — but check rather than assume, because a private
package is the one failure that stops the pilot dead:

```
TOK=$(curl -s "https://ghcr.io/token?scope=repository:abstractnucleus/mcontrol:pull&service=ghcr.io" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOK" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  https://ghcr.io/v2/abstractnucleus/mcontrol/manifests/latest
```

The `Accept` header is not optional. buildx publishes an OCI image index, and
without a header advertising that type the registry answers `404` for a tag
that is live and public — a false negative that sends you to the settings
page for no reason.

`200` means bserver can pull. If you ever see `403`, the package is private:

<https://github.com/users/AbstractNucleus/packages/container/mcontrol/settings>
→ Danger Zone → Change visibility → Public.

Prefer that over `docker login ghcr.io` on bserver. The repo is already
public so a private image hides nothing, while a PAT would sit in plaintext
at `/home/abstract/.docker/config.json` on a host that today stores no
credentials and has no credential helper. There is no `gh api` shortcut
unless you first run `gh auth refresh -s write:packages`.

**4. Stage the deploy directory.** Copy the existing `.env` across rather
than retyping it — the live values are already correct and retyping them is
how they drift.

```
ssh bserver
mkdir -p /home/abstract/deploy/mcontrol
cp /home/abstract/repos/mcontrol/.env /home/abstract/deploy/mcontrol/.env
echo 'TAG=latest' >> /home/abstract/deploy/mcontrol/.env
```

Then copy `compose.yml` from this directory to
`/home/abstract/deploy/mcontrol/compose.yml`.

**5. Cut over.** Only now:

```
cd /home/abstract/deploy/mcontrol
docker compose pull
docker compose up -d --wait
```

`--wait` blocks until the healthcheck passes, so a broken image fails at your
prompt instead of crash-looping quietly behind nginx.

## The .env

Reference only — step 4 copies the real one. Do not hand-write these.

| Key | Notes |
|---|---|
| `TAG` | `latest`, or `sha-<short commit>` to pin a build |
| `SUPABASE_URL` | shared supabase-server |
| `SUPABASE_SERVICE_ROLE_KEY` | server-side only |
| `SERVER_BASE_PATH` | **`/home/abstract/servers/minecraft`** on bserver |
| `HOST_BIND_IP` | `100.124.22.82`, the tailscale IP nginx reaches |

`SERVER_BASE_PATH` is the dangerous one. It is both sides of the bind mount
*and* the directory `discovery.py` walks to register servers. Set it one level
too high and mcontrol writes junk rows into the production Supabase table,
stops refreshing state on the real servers, and scaffolds new ones into the
wrong directory — all without erroring.

## Deploy

```
cd /home/abstract/deploy/mcontrol
docker compose pull
docker compose up -d --wait
```

## Rollback

Every build is tagged `sha-<short commit>`. Set `TAG` in the server's `.env`
to an earlier one and run the same two commands. No rebuild, no checkout.

To find the tag, read the workflow run — the summary prints every tag it
pushed:

```
gh run list --workflow publish-image.yml
gh run view <run-id>
```

`docker image ls` on bserver is not a reliable source: only tags that have
actually been pulled to that host appear, which on day one is just `latest`.

## The old checkout

`/home/abstract/repos/mcontrol` still exists and its `docker-compose.yml`
claims the same compose project name (`mcontrol`). Running the old
`git pull && docker compose -p mcontrol up -d --build` there will rebuild
from source and silently replace the pulled image, in place, with no error —
undoing the migration while looking perfectly healthy.

`HOSTS.md` and the `/deploy` skill must be updated to point here before that
old path is retired.

## Keeping this file in step

`compose.yml` here and `docker-compose.yml` at the repo root describe the same
service two ways — one pulls, one builds. Change a port or add a service in
one and you must mirror it in the other. They are in the same repo so the diff
shows up in the same review.
