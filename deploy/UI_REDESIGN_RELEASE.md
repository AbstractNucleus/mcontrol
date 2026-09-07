# Workspace redesign release checks

This change preserves FastAPI, Jinja, HTMX, CodeMirror, mutation URLs, file conflict protection, and the existing database schema. No database migration is required. Browser layout v2 migrates Console/Files/Players preferences into the shared v3 workspace; configuration panels now live in Settings. Cancel does not write preferences. Static assets carry a content digest to avoid mixing old JavaScript with new templates after an image update.

## Before publishing

- Run `uv run pytest -v` and `uv run ruff check .`.
- Install Chromium with `uv run playwright install chromium`, then run `MCONTROL_BROWSER_TESTS=1 uv run pytest tests/browser -v` (PowerShell: `$env:MCONTROL_BROWSER_TESTS='1'`). These tests launch an isolated mock process and temporary server files.
- Review `.localdev/ui-review/` screenshots of the fixed dark interface at 390, 768, 1280, and 1920 pixels. Confirm no horizontal page overflow, readable server names, and an immediately visible editor when selecting a file.
- Test lifecycle writes, player mutations, failed saves, conflict handling, and deletion only against fixtures. Browser tests include controlled HTTP 502 responses, a stalled request, reconnection, and stale-content recovery. These reproduce the observed failure symptoms; they do not establish the original upstream 502 cause.
- Check keyboard navigation, focus restoration, non-drag layout controls, reduced motion, and phone targets. Automated contrast checks sample semantic text/background pairs; they are not a full WCAG certification.

## Publish and install when the release is approved

1. Record the current image ID and `org.opencontainers.image.revision` label on bserver. Read-only inspection on September 7, 2026 found `mcontrol-app-1` healthy at revision `00e103912c97b3c78f5f072585fab04179d5d893`.
2. Push the reviewed commit to `main`. Wait for `.github/workflows/publish-image.yml` to succeed and record its exact `sha-<short>` tag. Verify that GHCR allows the host to pull the image anonymously.
3. In `/home/abstract/deploy/mcontrol` on bserver, preserve the configured `.env` and set `TAG` to that published SHA tag. Run:

   ```sh
   docker compose pull
   docker compose up -d --wait
   docker compose ps
   docker inspect mcontrol-app-1 --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
   ```

4. Check `/healthz` and open https://mcontrol.noelkleen.com. Read-only smoke checks: fleet filtering, a running and stopped server, five-second telemetry, independent disk refresh, existing file viewing, roster, Settings, and fixed dark appearance under either operating-system color scheme. Verify the revision matches the intended commit. Do not run test mutations on live servers.

## Rollback

Set `TAG` to the previously recorded published SHA tag in `/home/abstract/deploy/mcontrol/.env`, then repeat `docker compose pull` and `docker compose up -d --wait`. Verify `/healthz` and the image revision. No source checkout or on-host build is involved. Dashboard v2 storage is retained, so older images can still read their prior preferences.

The implementation task prepares this release; it does not publish or replace the live image.
