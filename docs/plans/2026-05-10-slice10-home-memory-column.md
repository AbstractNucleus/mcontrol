# Slice 10 — Home-page memory column

> Lean plan: contract + PR. The code is the source of truth — this doc is the napkin sketch.

## Goal

Operator opens `/` and sees, per row, how much memory each running server is using against its cgroup cap — without clicking into each detail page. Same motivation as decision 009 / slice 9: the budget knob writes `mem_limit` and `-Xmx`, but until now the only live readout lived behind a per-server click. This was slice 9's deferred "home-page resource column" item (resolution #7 — deferred on first-byte cost grounds). The cost is now paid concurrently, which makes the column tractable.

## Scope contract

| | |
|---|---|
| Surface | One new `Memory` cell per row in the existing home-page server list, next to the existing state pill. No other columns. |
| Numbers shown | `<used> / <limit> GiB (NN%)` when the container is running; `—` otherwise. Bytes render via the existing `resources.format_bytes` (base-1024); for typical Minecraft cap sizes that resolves to GiB. |
| Stats source | `resources.read_container_stats(container_name)` — the same function the detail-page card uses. No duplication of the cgroup-v1/v2 fallback math. |
| Disk | None. Slice 9's resolution #7 deferred this column on the grounds that "six servers each triggering a stats call + scandir on every home render" was a meaningful first-byte hit. So: stats only, no scandir. |
| Concurrency | All N stats calls run via `asyncio.gather(..., return_exceptions=True)` — total render latency is one slow stats round-trip, not six serial ones. An exception on one row degrades that row to `—` without taking down the page. |
| Refresh model | Render-time only. No HTMX poll on the home column for this PR. The detail page card remains the polled surface for in-flight memory diagnosis. |
| Container resolution | `db.container_name_for(row)` per decision 021 — re-pointed rows read the right container. |
| Caption derivation | Live stats result, not the DB `state` column. Match slice 9's resolution #12: the DB state can lag (or be "unknown" wholesale during a daemon outage). Container-not-running and daemon-unreachable both render as `—` — no per-row caption distinguishing them; the home page is for glance, not diagnosis. |
| Caching | None. Same posture as the detail-page card. |
| Path-safety | N/A — no filesystem access this slice. |

## Routes

No new routes. `GET /` is unchanged in shape; only its render-time work grows.

## Modules

```
src/mcontrol/
  routes/home.py            # gather stats concurrently, decorate each row with a memory string.
  templates/home.html       # one new cell per row.
  static/app.css            # one small layout rule for the new cell.
```

No new module. The two reused functions (`read_container_stats`, `format_bytes`) already live in `resources.py` and need no changes.

## Test contract

`tests/test_home.py` gains a `fake_stats` fixture that monkeypatches `resources.read_container_stats` to a configurable per-container responder, mirroring `tests/test_server_resources.py`'s pattern. New test asserts the home route tolerates a stats-failure on one row without 500'ing the whole page: one row's responder raises, another returns `{"status": "ok", ...}`, the page renders 200 with `—` for the failing row and the live numbers for the other.

Existing home tests get the fixture wired in by default (responder returns `{"status": "unreachable"}` for any container) so they don't accidentally hit a real Docker socket and so the new column's `—` output doesn't break their existing assertions.

## Decisions register impact

**No new decision.** This slice expands an existing surface; the trade-offs (no scandir, no poll) are already covered by slice 9's plan resolution #7 ("deferred until felt need; the home column is a render-cost concern, not a capability concern"). Slice 9's resolutions #12 (caption from live stats) and #4 (auto-poll model on the detail card) carry over unchanged — this slice just declines to opt into the poll on the home surface.

This slice acts on:

- **006** Direct `/var/run/docker.sock` mount — same engine-API stats path as slice 9.
- **009** Single memory-budget knob — this slice surfaces the cap on the operator's landing page, so the OOM-context diagnosis loop starts before the click into a detail page.
- **016** FastAPI + Jinja + HTMX — render-time only; no HTMX surface this PR.
- **021** Per-server `container_name` override — stats lookup goes through `db.container_name_for(row)`.

## Deferred / out-of-scope

Hard out-of-scope; do not pull in:

- **CPU column on the home page.** Stats payload includes it; a CPU number on the landing page is not the felt need (decision 009 / slice 9 explicitly framed memory-vs-cap as the visibility gap).
- **Disk column on the home page.** Slice 9 resolution #7 deferred scandir on the home page; nothing changed.
- **HTMX poll on the home column.** Render-time is enough for the glance use case; the detail-page card stays the polled diagnosis surface.
- **History / time-series.** Slice 9 deferral.
- **Network / block IO.** Slice 9 deferral.
- **Per-row caption distinguishing "not running" vs "daemon unreachable".** The detail-page card's caption already does this; the home cell is one column wide and reads as `—` either way.
