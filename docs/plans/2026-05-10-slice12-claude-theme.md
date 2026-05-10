# Slice 12 — Claude-flavoured theme; dark + light; full surface coverage

> Lean plan: contract + token table + per-template checklist. End-to-end
> visual refining pass on the panel; supersedes decision 002. The code is
> the source of truth — this doc is the napkin sketch.

## Goal

Operator opens the panel in any browser and the surface reads as
Anthropic-flavoured: warm cream `#FAF9F5` page in light mode, near-black
`#141413` in dark mode, terracotta `#D97757` accent on one CTA per screen,
Inter Tight body type, mono kept for code/log/RCON. Tri-state theme
toggle (system / light / dark) lives top-right in the page chrome and
persists per-browser via `localStorage`. Every template has a deliberate
styling pass — including `/players` and `/trash`, which today render as
unstyled HTML because their CSS classes were never written. Custom
`404` / `500` pages replace the FastAPI default trace pages. Closes the
"warm-paper-and-rust monospaced" surface that decision 002 set up.

## Scope contract

| | |
|---|---|
| Visual identity | Claude-flavoured. Source: `docs/research/2026-05-10-claude-theme/anthropic-visual-language.md`. Palette / type / radii / focus-ring pulled verbatim from `claude.com/docs/connectors/building/mcp-apps/design-guidelines`. |
| Token architecture | Two layer. **Primitives** (raw hex, e.g. `--hex-cream-100: #FAF9F5`) live in `tokens.css` for reference but aren't consumed directly. **Semantic** layer (`--bg-page`, `--fg-primary`, `--accent`, `--ring`, …) is what every component consumes. Defined twice — `:root` for light, `[data-theme="dark"]` for dark. `@media (prefers-color-scheme: dark)` block handles the JS-off case. |
| Theme toggle | Tri-state segmented control: System / Light / Dark. SVG sun-moon-monitor icons. Lives top-right of the page chrome. State stored in `localStorage` under key `theme`. Inline `<head>` script bootstraps the `data-theme` attribute on `<html>` before stylesheets to prevent FOUC. Toggle handler is a single deferred `theme.js` file. |
| Type stack | Body/UI: `Inter Tight, Inter, -apple-system, system-ui, sans-serif`. Mono: `ui-monospace, JetBrains Mono, Consolas, monospace`. No serif accent. Ship via system stack — no font-loading round-trip; if Inter Tight isn't installed, the OS humanist sans is the fallback (San Francisco / Segoe UI). |
| Type scale | 12 / 14 / 16 / 20 / 24 / 28 / 36 px. Body 16/22.4 (line-height 1.4). Display headings 28/30.8 (line-height 1.1). Eyebrows 12 px tracked +0.04 em uppercase. |
| Radius scale | 4 / 6 / 8 / 10 / 12 px. Buttons 8 px. Inputs 6 px. Cards 8–10 px. Dialogs 12 px. Pills `--radius-full`. |
| Focus rings | `outline: 2px solid var(--ring); outline-offset: 2px;`. `--ring` is `rgba(20,20,19,0.70)` light / `rgba(250,249,245,0.70)` dark. Single ring, no inner ring. **Never orange** — orange is identity. |
| Borders | Translucent — `rgba(31,30,29, X%)` light / `rgba(222,220,209, X%)` dark, where X is 15 / 30 / 40 for soft / medium / strong. Picks up surface tint, works on every background. |
| Cards | One-step-lighter background (`--bg-surface` over `--bg-page`) is the default elevation. No shadow. Reserve shadows for popovers and dialogs only. |
| Motion | `--motion-fast: 120ms`, `--motion-base: 200ms`, `--motion-slow: 320ms`. Ease: `cubic-bezier(0.2, 0.8, 0.2, 1)`. `prefers-reduced-motion` collapses everything to 1 ms. |
| State pill | Coloured dot + label. Six states — `created`, `running`, `restarting`, `paused`, `exited`, `dead`. Maps to semantic colour tokens. `restarting` pulses; everything else is static. |
| Lifecycle controls | Three buttons stay (Start / Stop / Restart) — context disabling lands on a follow-up slice. Buttons styled as ghost / tonal; the active action picks up `--accent`. |
| Empty states | Every page that can be empty gets a deliberate empty-state design — icon + headline + 1–2 sentences + optional CTA. Home / players / trash / per-server-files / per-server-players covered. |
| Error pages | Custom `404.html` and `500.html` replace FastAPI's default JSON / trace surface. Same chrome as the rest of the panel; a single back-to-home CTA. |
| Surface coverage | Every `.html` under `templates/` has a deliberate styling pass. Audit identifies two unstyled pages (`/players`, `/trash`) — gap closes here. |
| Decision register | New entry **032**. Marks decision **002** as `Superseded by 032`. |
| Out of scope | New routes, new features beyond visual / UX polish. Bundler / Tailwind / shadcn (decision 016). Auth UI (decision 011). Route-shape changes (operator muscle memory). Healthz JSON shape (decision 030). Docker / aiodocker code. Supabase schema. |

## Token table (semantic layer, both modes)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg-page` | `#FAF9F5` | `#141413` | page background |
| `--bg-surface` | `#FFFFFF` | `#30302E` | cards, table rows, inputs |
| `--bg-sunken` | `#F5F4ED` | `#262624` | code wells, log/RCON streams, search bar, hover |
| `--bg-inverse` | `#141413` | `#FAF9F5` | tooltips, inverted callouts |
| `--fg-primary` | `#141413` | `#FAF9F5` | body text, headings |
| `--fg-secondary` | `#3D3D3A` | `#C2C0B6` | secondary copy |
| `--fg-muted` | `#73726C` | `#9C9A92` | captions, eyebrows, placeholders |
| `--fg-inverse` | `#FFFFFF` | `#141413` | text on `--bg-inverse` and on `--accent` |
| `--accent` | `#D97757` | `#D97757` | identity / one primary CTA per screen |
| `--accent-hover` | `#C5613F` | `#E08B6F` | hover/press of accent button |
| `--accent-soft` | `#F4DDD1` | `#3A241B` | accent badge ground |
| `--success-bg` | `#E9F1DC` | `#1B4614` | success flash ground |
| `--success-fg` | `#265B19` | `#7AB948` | success flash text, running-state pill |
| `--warning-bg` | `#F6EEDF` | `#483A0F` | warning flash ground |
| `--warning-fg` | `#5A4815` | `#D1A041` | warning text, restarting-state pill |
| `--danger-bg` | `#F7ECEC` | `#602A28` | danger flash ground, delete-zone bg |
| `--danger-fg` | `#7F2C28` | `#EE8884` | danger text, exited-state pill, delete buttons |
| `--info-bg` | `#D6E4F6` | `#253E5F` | info flash ground |
| `--info-fg` | `#3266AD` | `#80AADD` | info flash text |
| `--border-soft` | `rgba(31,30,29,0.15)` | `rgba(222,220,209,0.15)` | hairline dividers |
| `--border-medium` | `rgba(31,30,29,0.30)` | `rgba(222,220,209,0.30)` | input borders, card outlines |
| `--border-strong` | `rgba(31,30,29,0.40)` | `rgba(222,220,209,0.40)` | hover state of `--border-medium` |
| `--ring` | `rgba(20,20,19,0.70)` | `rgba(250,249,245,0.70)` | focus outline |

Plus a small primitive layer (`--hex-*`) referenced only inside the semantic block — never directly by components. Components that need to deviate add a new semantic token.

## Type / radius / spacing tokens

```css
--font-sans: "Inter Tight", "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
--font-mono: ui-monospace, "JetBrains Mono", "Fira Code", SFMono-Regular, Menlo, Consolas, monospace;

--fs-xs:  12px;
--fs-sm:  14px;
--fs-md:  16px;   /* body default */
--fs-lg:  20px;
--fs-xl:  24px;
--fs-2xl: 28px;
--fs-3xl: 36px;

--lh-tight: 1.1;
--lh-snug:  1.25;
--lh-base:  1.4;

--radius-xs:   4px;
--radius-sm:   6px;
--radius-md:   8px;
--radius-lg:   10px;
--radius-xl:   12px;
--radius-full: 9999px;

--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;
--space-12: 48px;
--space-16: 64px;

--motion-fast: 120ms;
--motion-base: 200ms;
--motion-slow: 320ms;
--ease: cubic-bezier(0.2, 0.8, 0.2, 1);
```

## Theme bootstrap

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script>
      (function () {
        try {
          var stored = localStorage.getItem("theme");
          var resolved = stored;
          if (!stored || stored === "system") {
            resolved = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
          }
          document.documentElement.setAttribute("data-theme", resolved);
        } catch (_) { /* localStorage blocked → CSS @media kicks in */ }
      })();
    </script>
    <link rel="stylesheet" href="/static/tokens.css">
    <link rel="stylesheet" href="/static/app.css">
    <script src="/static/theme.js" defer></script>
    ...
  </head>
```

`theme.js` (small, deferred):

- Reads stored `intent` from `localStorage`; defaults to `system`.
- Wires up the segmented-control radio buttons to call `apply(intent)` and persist.
- Listens to `matchMedia("(prefers-color-scheme: dark)").addEventListener("change", …)` and re-applies if intent is `system`.

## Per-template checklist

Every file under `src/mcontrol/templates/` gets a deliberate styling pass.

- [ ] `base.html` — chrome (logo + version + tri-state theme toggle); `<main>` wraps `_topnav.html`; inline theme-bootstrap script.
- [ ] `_topnav.html` — segmented links Servers / Players / Trash with current-page emphasis. Replace home.html's inline `home-header__nav` block.
- [ ] `home.html` — server table (running first, alphabetic within state); state pill (dot+label); memory column; empty state; the "New server" CTA picks up `--accent`.
- [ ] `server_detail.html` — page-back link, server name as h1, health-banner (when present), lifecycle row, resources card, bindings card, players card, files pane, log + console panes, variables/migrate, regenerate diff, delete zone.
- [ ] `_state_pill.html` — coloured dot + label, six states.
- [ ] `_resources_card.html` — Memory bar (used / limit + %) reordered to the top because it's the primary failure mode operators watch; CPU + Disk underneath; "updated 5 s ago" caption.
- [ ] `_bindings_card.html` + `_bindings_form.html` — summary view with Edit affordance; form view with input borders consuming `--border-medium`.
- [ ] `_variables_card.html` + `_variables_form.html` — definition list; form variant.
- [ ] `_regenerate_diff.html` — `<details>` per file; mono font; sticky scroll.
- [ ] `_migrate_card.html` — legacy intro + form. Disabled state when running.
- [ ] `_delete_confirm.html` — danger-zone framed in `--danger-border`; type-name confirm.
- [ ] `_log_pane.html` + `_console_pane.html` — sunken-bg pre, mono, autoscroll. Console input picks up `--accent` Send button.
- [ ] `_health_banner.html` — danger-flavoured banner.
- [ ] `_server_players_card.html` — table with checkbox toggles; flash messages.
- [ ] `_player_remove_modal.html` — modal panel with cascade-confirm wording.
- [ ] `players.html` + `_players_main.html` — currently unstyled; closes the gap. Roster table + Add form + Import affordance + empty state.
- [ ] `trash.html` + `_trash_*.html` — currently mostly unstyled; closes the gap. List + Empty-trash CTA + per-row Delete-now + modals + empty state.
- [ ] `_file_*.html` — file tree, file view, popover menus, conflict banners, upload conflict, search results, dir picker, action forms. Sunken bg for the tree and view; popover styled like a card with shadow.
- [ ] `new_server.html` — form layout matches `_variables_form.html`'s shape.
- [ ] `404.html` (NEW) — chrome + centered "Not found" + back-to-home button.
- [ ] `500.html` (NEW) — chrome + centered "Something went wrong" + back-to-home button.

## UX changes beyond pure styling

These ride along; each is a clearly-better pattern than what's there today.

1. **Resources card reordered: Memory first.** The used/limit + percent is the operator's primary failure mode (OOM kills); CPU and Disk move below. Same data, just the row order.
2. **Empty states everywhere.** Home / players / trash / per-server-files / per-server-players each get an icon + headline + sentence + optional CTA. No more bare paragraph fallbacks.
3. **State pill: dot + label.** Replaces the bare-text state in the home table. Coloured dot encodes state at a glance; label keeps it readable in monochrome / screen reader contexts.
4. **One CTA per screen picks up `--accent`.** Home: "New server". Players: "Look up + add". Trash: "Empty trash". Server detail: the action that's most likely next given state (e.g. "Start" when stopped, "Stop" when running) — but to avoid scope creep on lifecycle logic, this slice picks "Start" by default and the accent moves to the active action button only on hover/press; the lifecycle-aware accent is a follow-up.
5. **Theme toggle in chrome.** Tri-state segmented control top-right of `base.html`'s header. Persists per browser.
6. **Custom 404 / 500.** Default FastAPI surface is operator-hostile.
7. **Players page: real layout.** Was rendering as unstyled HTML. Roster table, add form, import affordance, empty state.
8. **Trash page: real layout.** Was partially styled — the empty-state and the topnav rendered, but the populated list and the Empty-trash button had no rules. Closed.
9. **Top-nav consolidation.** Decision 031 left `home.html` with an inline `home-header__nav` block while `players.html` and `trash.html` use `_topnav.html`. Slice 12 swaps home.html's inline nav for the partial — single source of truth.
10. **Inline-script theme bootstrap.** No flash of wrong theme on first paint, even before `theme.js` parses.

## PR sequence

Slice 12 ships as a single comprehensive PR off `slice12/claude-theme`. Cohesion is the constraint: every page must remain renderable at every commit, and split-PRs that retheme `tokens.css` without simultaneously updating component CSS would leave intermediate states broken. Inside the PR, commits map to the per-template checklist above so review can step through component-by-component if wanted.

Future split exit ramp: if a follow-up wants to add a new theme variant or a new top-level page, it ships against the new token system without re-litigating the architecture.

## Verification

1. `uv run pytest -v` green.
2. `uv run ruff check .` green.
3. Real-browser smoke via `mcp__Claude_Preview__preview_*`:
   - `/`, `/servers/<one>`, `/servers/new`, `/players`, `/trash`, `/notfound` → all 200 / 404 with the right surface.
   - Toggle switches: System / Light / Dark cycle without page reload.
   - Both modes: every page visually OK, no unstyled elements, focus rings visible on every interactive element.
   - HTMX swap targets still work: lifecycle Start, resources poll, file tree expand, players toggle, variables Edit/Save, delete confirm, trash modal.
4. Healthz: `curl /healthz` still 200 with the existing JSON shape (decision 030).
5. Public smoke after deploy: `curl -sS https://mcontrol.noelkleen.com/healthz` → 200; `/`, `/servers/<one>`, `/players`, `/trash` → 200.

## Decision linkage

- Supersedes: 002 (UI palette: AbstractNucleus/design).
- Honours: 003 (tailnet-only), 011 (no app-level user — toggle pref is per-browser localStorage), 016 (no bundler — handwritten CSS), 019 (TLS at aserver-nginx), 020 (pin Docker images — unaffected), 030 (healthz shape unchanged).
- Records: decision 032 (Claude theme).
