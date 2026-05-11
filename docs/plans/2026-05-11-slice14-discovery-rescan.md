# Slice 14 — Discovery rescan affordance

> Lean plan. The slice 3 plan parked "Rescan" as a follow-up. Decision
> 033 (slice 13) re-flags the gap: DB state drifts from real container
> state until the next app restart. This slice closes it.

## Goal

Operator drops a new directory into `SERVER_BASE_PATH`, or
`docker start`s a container outside the panel, and a single click on
**Rescan** reflects it without restarting the app container. The button
lives on the home page header next to "New server".

## Scope contract

| | |
|---|---|
| Trigger surface | A `btn--ghost` "Rescan" button on the home page header (right side, alongside "New server"). HTMX-driven. |
| Route | `POST /rescan`. Calls `discovery.run_discovery(Path(settings.server_base_path))`. On success: `204 No Content` with `HX-Refresh: true` header (HTMX reloads the page; the freshly-loaded `GET /` reflects the new rows). On Docker failure: discovery already handles the unreachable case by returning `state="unknown"` (decision 003 / `docker_client.container_states_by_name`); rescan inherits that posture and still succeeds. On filesystem failure (base path missing): `503` with a flash. |
| Empty-state copy | The current empty-state on home.html says "Drop a directory into `{SERVER_BASE_PATH}` and **restart the panel**." Update to "Drop a directory and **rescan**" — point the operator at the new button instead of `docker compose restart app`. |
| Idempotency | `discovery.run_discovery` is already idempotent (decision 021 — non-destructive of `dir` / `container_name`; only `state` refreshes). Rescan inherits that contract. The route doesn't need an extra lock. |
| HTMX vs full-page | HTMX: 204 + `HX-Refresh: true`. Non-HTMX (curl / no-JS): 303 → `/`. Single handler distinguishes via the `HX-Request` header. |
| Decision register | New entry **034**. Pins "discovery is also operator-triggerable, not just startup." |
| Out of scope | Auto-rescan on a timer (decision 021's posture is operator-triggered). Rescan from `/servers/<name>` (slice 14 ships the home-page entry-point; per-server rescan would be a separate decision about per-server state refresh). Progress / streaming feedback (single-host scope; discovery is fast). Toast / flash on success (page reload IS the feedback; the new rows appear). |

## Files

- **Edit** `src/mcontrol/routes/home.py` — append `rescan` handler.
- **Edit** `src/mcontrol/templates/home.html` — add Rescan button + update empty-state copy.
- **Edit** `docs/decisions.md` — append decision 034.
- **New** `tests/test_rescan.py` — covers: handler calls discovery, HTMX returns 204+`HX-Refresh`, non-HTMX returns 303 → `/`, button is rendered on the home page header.

## Verification

1. `uv run pytest -v` green.
2. `uv run ruff check .` green.
3. Post-merge smoke on bserver after redeploy:
   - Drop a new directory into `~abstract/servers/minecraft/`.
   - Visit panel → no new row yet.
   - Click "Rescan" → page reloads, new row appears.
   - `docker stop atm10` from a shell → click "Rescan" → state pill on home row flips to `exited`.

## Decision linkage

- Honours: 003 (tailnet-only), 011 (no app-level user — single-operator), 016 (no bundler), 021 (idempotent discovery, non-destructive of operator edits), 033 (state-aware lifecycle — Rescan refreshes the source data those buttons read from).
- Records: decision **034** (operator-triggered discovery via `POST /rescan`).
