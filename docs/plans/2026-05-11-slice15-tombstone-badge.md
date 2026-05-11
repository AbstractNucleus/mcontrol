# Slice 15 — Topnav tombstone count badge

> Lean plan. Decision 031 punted "tombstone count badge" as a follow-up.
> Slice 15 ships it on the topnav (not just the home page) so it's
> visible everywhere.

## Goal

Operator sees `Trash 3` (or `Trash`) in the topnav from every page, so
they know at a glance whether trash is non-empty. No second request,
no flash-of-no-badge — server-rendered.

## Scope contract

| | |
|---|---|
| Surface | Topnav `Trash` link (every page that includes `_topnav.html`). Badge appears next to the label when count > 0; omitted when count == 0. |
| Data path | New cheap helper `tombstones.count(base)` — single `os.scandir`, no recursion, no disk-usage walk. Rendered via a Jinja global `tombstone_count(request)` registered in `main.py`. Per-render cost: ~ms at single-host scale, well below noise. |
| Decision register | New entry **035**. Pins the Jinja-global mechanism and the topnav placement. |
| Out of scope | Streaming/live updates of the badge. Per-page hint. Configurable threshold. Badge styling beyond what current tokens provide. |

## Files

- **Edit** `src/mcontrol/tombstones.py` — append `count(base)` helper.
- **Edit** `src/mcontrol/main.py` — register `tombstone_count` Jinja global in `create_app`.
- **Edit** `src/mcontrol/templates/_topnav.html` — call the global, render badge when non-zero.
- **Edit** `src/mcontrol/static/app.css` — `.topnav__badge` rule (small pill, accent-soft ground, accent fg, tabular numerals).
- **Edit** `docs/decisions.md` — decision 035.
- **New** `tests/test_topnav_badge.py` — covers `tombstones.count()` happy / empty / unparseable / missing-base, plus a topnav render test asserting badge presence/absence based on disk state.

## Verification

1. `uv run pytest -v` green.
2. `uv run ruff check .` green.
3. Post-merge smoke on bserver: visit `/` with zero tombstones → no badge; delete a server → visit `/` again → badge reads `1`; navigate to `/players` → same badge value.

## Decision linkage

- Honours: 026 (tombstones), 031 (empty-trash; this is the missing visibility surface), 032 (theme tokens — reuses `--accent-soft` and `--accent`).
- Records: decision **035** (topnav tombstone count badge).

## PR shape

Single PR off `slice15/tombstone-badge`.
