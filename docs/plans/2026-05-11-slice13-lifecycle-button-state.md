# Slice 13 — Lifecycle buttons: state-aware disable + accent

> Lean plan: scope contract + state table. The slice 12 plan deferred
> lifecycle context-disabling and the lifecycle-aware `--accent` to a
> follow-up; this is that follow-up.

## Goal

The three lifecycle buttons on `/servers/<name>` reflect the server's
current state. Operator can't fire `start` on a `running` server or
`restart` on an `exited` one — those buttons render `disabled`. The
`--accent` colour moves to the action that is unambiguously the next
step given state (Start when stopped, Stop when running). After a
lifecycle action lands, the buttons re-render in lock-step with the
state pill via an HTMX out-of-band swap, so the surface stays consistent
without a page reload.

## Scope contract

| | |
|---|---|
| State source | `server.state` (string) — already populated by discovery and lifecycle handlers. Docker's standard values (`created`, `running`, `paused`, `restarting`, `removing`, `exited`, `dead`) plus our own `scaffolding` and `unknown`. |
| State → view function | Pure function `lifecycle_state.view(state) -> {start_disabled, stop_disabled, restart_disabled, accent}` in a new module `mcontrol/lifecycle_state.py`. Single source of truth — routes and templates consume it. |
| Template shape | New partial `_lifecycle_buttons.html` (just the three buttons + wrapper). `server_detail.html` swaps the inline buttons block for `{% include %}`. The partial wraps in `<div id="lifecycle-buttons" class="lifecycle-row__buttons">`. |
| HTMX swap | Lifecycle routes return the state pill (primary swap to `#state-pill`) AND the rebuilt lifecycle-buttons partial with `hx-swap-oob="true"` on its wrapper. Single response, two swap targets. |
| Accent assignment | Stop cluster (`created`/`exited`/`dead`) → Start accent. Running cluster (`running`/`paused`) → Stop accent. Transient (`restarting`) → no accent, all disabled. `scaffolding` → no accent, all disabled (the server isn't ready yet; the migrate / health-banner surface drives operator next-step here). `unknown` → no accent, none disabled (recovery posture — if we don't know, don't get in the operator's way). |
| Disabled matrix | See table below. |
| CSS | No new tokens. Reuse existing `.btn--primary` for accent and the existing `.btn[disabled]` / `.btn:disabled` rules for the disabled look. Lifecycle row CSS unchanged. |
| Decision register | New entry **033**. Slice 12 plan called this out as a deferred follow-up; the entry pins the state-table contract. |
| Out of scope | New states. Auto-refresh of lifecycle buttons on a timer (the state pill itself isn't polled either; only post-action swaps update it — same posture). Unpause as a distinct route (Docker `unpause` isn't currently exposed; the operator can `restart` to recover a paused container). Mid-flight transient state (button shows `running` accent immediately, even while Docker is still spinning up — same as the state pill today). Cancel-action affordance. Healthz / discovery code. |

## State table (single source of truth)

| State (`server.state`) | Start | Stop | Restart | Accent |
|---|---|---|---|---|
| `created` | enabled | disabled | disabled | Start |
| `exited` | enabled | disabled | disabled | Start |
| `dead` | enabled | disabled | disabled | Start |
| `running` | disabled | enabled | enabled | Stop |
| `paused` | disabled | enabled | enabled | Stop |
| `restarting` | disabled | disabled | disabled | — |
| `scaffolding` | disabled | disabled | disabled | — |
| `unknown` (or unrecognised) | enabled | enabled | enabled | — |

`paused` rationale: Docker `start` on a paused container is a no-op; `unpause` is the right call but isn't currently exposed as a route. Treat `paused` like `running` — Stop / Restart available. Restart will kill+restart the container, which is the practical recovery path for an accidentally-paused server.

`unknown` rationale: discovery returns `unknown` when the Docker daemon is unreachable or the container has been removed externally. The operator deserves all three buttons to attempt recovery; the route handlers themselves will surface real failures (404 / 500). Don't pre-block.

`scaffolding` rationale: the server isn't ready to run. The migrate card / health banner is the operator's next-step surface for these rows, not the lifecycle buttons.

## File-level changes

- **New** `src/mcontrol/lifecycle_state.py` — single `view(state: str) -> dict` function. Tested in isolation.
- **New** `src/mcontrol/templates/_lifecycle_buttons.html` — renders the three-button wrapper, consuming `server.name` and the `lifecycle` dict from context. Supports an `oob` flag that adds `hx-swap-oob="true"` on the wrapper for post-action swaps.
- **Edit** `src/mcontrol/templates/server_detail.html` — replace inline button block with `{% include "_lifecycle_buttons.html" %}`. The eyebrow + outer `lifecycle-row` wrapper stay.
- **Edit** `src/mcontrol/routes/server.py` — compute `lifecycle = lifecycle_state.view(state)`, pass into context.
- **Edit** `src/mcontrol/routes/lifecycle.py` — `_pill_and_buttons` helper builds a combined response: state pill (primary swap) + lifecycle-buttons partial (OOB). Each route returns the helper.
- **New** tests — `tests/test_lifecycle_state.py` (pure state mapping); plus extensions to `tests/test_server_detail.py` and `tests/test_lifecycle.py` for disabled + accent + OOB-swap assertions.
- **Edit** `docs/decisions.md` — append decision 033.

## Verification

1. `uv run pytest -v` green.
2. `uv run ruff check .` green.
3. Real-browser smoke via `preview_*`:
   - On a `running` server: Start is disabled, Stop carries `.btn--primary`, Restart is plain.
   - Click Stop → state pill flips to `exited`; buttons swap so Start is enabled + accent, Stop and Restart disabled.
   - Click Start → state pill flips to `running`; buttons swap back the other way.
4. No regression: existing lifecycle tests still pass; the state pill still arrives at `#state-pill` as `outerHTML`.

## Decision linkage

- Honours: 016 (no bundler — Jinja conditional only), 030 (healthz unchanged), 032 (Claude theme — reuse `.btn--primary` and existing `:disabled` styling).
- Records: decision 033 (state-aware lifecycle controls).

## PR shape

Single PR off `slice13/lifecycle-button-state`. Five small commits map to:
1. Decision register + plan.
2. `lifecycle_state.view()` module + test.
3. Partial + `server_detail` wiring.
4. Lifecycle routes return OOB swap.
5. Smoke + cleanup.
