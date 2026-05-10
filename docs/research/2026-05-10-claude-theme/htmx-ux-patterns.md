# HTMX + Jinja UX patterns for mcontrol

Opinionated reference for the Claude-themed admin panel. Assumes the existing
patterns: `every Ns` polling cards, GET-returns-modal confirms swapped into
`#modal`, `HX-Redirect` on success, HTMX SSE for log/console, type-name
confirms, inline-edit cards. Each section recommends one pattern; alternatives
are listed only when the trade-off is real.

Conventions used below:
- "partial" = a Jinja fragment rendered without the base layout, returned
  directly to an `hx-target`.
- "OOB" = `hx-swap-oob`, HTMX's out-of-band swap.
- All CSS uses CSS custom properties (`--accent`, `--danger`, etc.) so the
  theme can be retuned in one place.

---

## 1. Loading states

### Buttons (in-flight indicator)

HTMX adds the `htmx-request` class to the element that triggered the request
(or `hx-indicator` target) for the duration of the request. The canonical
pattern: disable the button, swap its label for a spinner, keep its width
stable so the layout doesn't jump.

```css
button[data-hx] {
  position: relative;
}
button[data-hx].htmx-request {
  pointer-events: none;
  color: transparent; /* hide label, keep width */
}
button[data-hx].htmx-request::after {
  content: "";
  position: absolute;
  inset: 0;
  margin: auto;
  width: 1em; height: 1em;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  color: var(--fg); /* spinner colour, since label is transparent */
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
```

Use `data-hx` (or just rely on `[hx-post], [hx-get], [hx-delete]`) so the
selector targets HTMX-driven buttons only. Don't put the spinner on plain
form-submit buttons that do full-page loads — those get the browser's
loading affordance for free.

### Poll cards (no flicker)

`hx-trigger="every 5s"` with the default `innerHTML` swap will visibly redraw
the card every cycle, even when the content is identical. Two fixes, ranked:

**Recommended:** use the View Transitions API via HTMX 2.x:

```html
<div id="resources-card"
     hx-get="/cards/resources"
     hx-trigger="every 5s"
     hx-swap="outerHTML transition:true">
  ...
</div>
```

The transition is a one-frame crossfade, which masks the redraw without an
explicit animation. Falls back gracefully on browsers without transitions.

**Optional, if the card is expensive to render:** filter on the client with
`htmx:beforeSwap` and skip the swap when the new HTML matches the old:

```js
document.body.addEventListener('htmx:beforeSwap', (e) => {
  const target = e.detail.target;
  if (target.dataset.lastHash === hash(e.detail.serverResponse)) {
    e.detail.shouldSwap = false;
  } else {
    target.dataset.lastHash = hash(e.detail.serverResponse);
  }
});
```

Don't bother with this unless the card has measurable jank. The transition
swap covers 95% of cases.

---

## 2. Optimistic / pending UI for destructive actions

### Lifecycle Start/Stop/Restart

Server transitions (`docker start`, `docker stop`) take 2–10 seconds. The
state pill should immediately switch to a **pending** state on click, not
wait for the next poll tick.

Recommended pending palette: amber (`--warning`, e.g. `#d97706`), with a
small spinner inside the pill. Keep the pill the same shape and size as the
running/exited variants so it doesn't reflow.

```html
<!-- pending pill -->
<span class="state-pill state-pill--pending">
  <span class="state-pill__spinner"></span>
  starting...
</span>
```

Two ways to drive it:

1. **Server-side:** the action endpoint sets a transient state in the docker
   label or in-memory cache, and the next poll returns "starting"/"stopping".
   Cleanest, but requires the polling tick to fire before the user sees the
   change (up to 5s lag).
2. **Optimistic swap:** the action button has `hx-swap="outerHTML"
   hx-target="#state-pill"` and the action endpoint returns a pending pill
   immediately, then the next poll picks up the real state.

Pick **(2)**. The user clicked Stop; the UI should acknowledge inside 200ms.

### Delete

Yes, gray out the row and disable its actions until the redirect lands.
Easiest: the confirm endpoint returns a `<tr>` (or `<li>`) replacement with
`aria-busy="true"` and a pending class, then the `HX-Redirect` carries the
user away.

```css
[aria-busy="true"] {
  opacity: 0.5;
  pointer-events: none;
  filter: grayscale(0.5);
}
```

If for some reason there's no redirect (e.g. inline trash purge), the row
gets removed by `hx-swap="outerHTML swap:200ms"` so the gray-out blends into
the dismissal animation.

---

## 3. Success-flash messaging

One global flash region, populated via OOB swap. The action endpoint
includes the flash in its response alongside whatever else it returns; HTMX
finds the `hx-swap-oob` element and routes it to `#flash`.

```html
<!-- in base.html -->
<div id="flash" aria-live="polite"></div>
```

```html
<!-- in the action response -->
<div id="flash" hx-swap-oob="innerHTML">
  <div class="flash flash--success" role="status">
    Server "survival" started.
  </div>
</div>
```

Auto-dismiss with pure CSS — no `setTimeout`, no JS:

```css
.flash {
  animation: flash-in 200ms ease-out, flash-out 400ms ease-in 3.6s forwards;
}
@keyframes flash-in  { from { opacity: 0; transform: translateY(-8px); } }
@keyframes flash-out { to   { opacity: 0; transform: translateY(-8px);
                              visibility: hidden; } }
```

The `forwards` keeps the element invisible after the animation; the next
flash overwrites the innerHTML and restarts the animation. Total visible
time: ~3.8s, which lands cleanly inside the "4s" target.

Don't use `setTimeout` to remove the node — it leaks if the user navigates
away mid-flash, and CSS handles the lifecycle for free.

---

## 4. Confirmation modal patterns

### Keep the current pattern

GET `/confirm/...` returns a modal partial, swapped into `#modal`. POST
executes. Success returns `HX-Redirect` (or an OOB flash + content swap).
**Keep this.** It's the right pattern for HTMX:

- The confirm UI is a server concern (it knows the entity name, dependent
  resources, "are you sure?" copy), so server-rendering it keeps logic in
  one place.
- The modal partial can include hidden fields, CSRF tokens, and dynamic
  detail (e.g. "this will delete 12 backups") without client logic.
- It composes with the rest of the HTMX flow — no separate JS routing layer.

Alternatives, only when warranted:

- **Inline confirm** (button morphs into "Are you sure? Yes / Cancel"):
  fine for low-stakes idempotent toggles. Don't use for delete.
- **Native `<dialog>` with hardcoded content:** appropriate when the
  confirm message is fully static and doesn't need server data.

### Type-name confirms

The user types the server name to enable the Delete button. Best done with
**a tiny inline `<script>` in the partial**, not `hx-disabled-elt`.

`hx-disabled-elt` only disables during the in-flight request, not based on
arbitrary client predicates. You'd be misusing it.

```html
<!-- modal partial -->
<form hx-delete="/servers/survival" hx-target="body">
  <p>Type <code>survival</code> to confirm:</p>
  <input name="confirm" autocomplete="off" autofocus>
  <button type="submit" disabled>Delete forever</button>
  <script>
    (() => {
      const form = document.currentScript.closest('form');
      const input = form.querySelector('input[name=confirm]');
      const btn   = form.querySelector('button[type=submit]');
      const want  = 'survival';
      input.addEventListener('input', () => {
        btn.disabled = input.value !== want;
      });
    })();
  </script>
</form>
```

15 lines, no framework, scoped to the partial. The script auto-runs on swap
(HTMX evaluates inline scripts in swapped content by default).

### Native `<dialog>` in 2026

Pros:
- Free focus trap, free ESC-to-close, free `::backdrop` pseudo-element.
- `showModal()` handles the inert-the-rest-of-the-page contract correctly.
- Keyboard semantics that screen readers recognise.

Cons:
- Closing via the backdrop click requires one line of JS (it's not built in).
- Animating open/close needs `@starting-style` or the `closedby` attr (still
  patchy in older browsers, but baseline-good in 2026).

**Recommendation: migrate.** Replace the custom `#modal` div with a
`<dialog id="modal">` and call `showModal()` in an `hx-on::after-swap`
handler:

```html
<dialog id="modal" hx-on::after-swap="this.showModal()"></dialog>
```

```js
// one-time, in app.js — close on backdrop click
document.getElementById('modal').addEventListener('click', (e) => {
  if (e.target.id === 'modal') e.target.close();
});
```

Removes 30+ lines of focus-trap and overlay CSS. Worth doing as part of the
theme refresh.

---

## 5. Form validation feedback

### Server-side (the default)

Return the form partial with inline error messages, swapped into the form's
`outerHTML`:

```html
<form hx-post="/servers" hx-target="this" hx-swap="outerHTML">
  <label>
    Name
    <input name="name" value="{{ form.name.value }}" aria-invalid="{{ 'true' if form.name.errors else 'false' }}">
    {% if form.name.errors %}
      <span class="field-error">{{ form.name.errors[0] }}</span>
    {% endif %}
  </label>
  ...
</form>
```

Use `aria-invalid` rather than a class — it's the semantic hook, and CSS can
target it directly:

```css
input[aria-invalid="true"] { border-color: var(--danger); }
```

Don't try to be clever with per-field OOB swaps. Re-rendering the whole form
is cheap, keeps state consistent, and avoids the "old error still visible
after fix" bug.

### Client-side (cheap wins)

Use HTML5 attributes to catch obvious mistakes before the round-trip:

- `required` for non-empty.
- `pattern="[a-z0-9-]+"` for slug-style names.
- `minlength` / `maxlength`.
- `type="email"`, `type="url"` where applicable.

Style with `:user-invalid` (not `:invalid`, which fires before the user has
interacted):

```css
input:user-invalid { border-color: var(--danger); }
```

Don't replicate server validation in JS. The server is the source of truth;
client-side is just the latency optimisation.

---

## 6. Empty states

Structure for each empty state: **icon + headline + 1–2 sentences + single
CTA.** No illustrations.

```html
<div class="empty-state">
  <svg class="empty-state__icon" aria-hidden="true">...</svg>
  <h2 class="empty-state__title">No servers yet</h2>
  <p class="empty-state__body">
    Create your first Minecraft server to get started.
    Each server runs in its own Docker container.
  </p>
  <a class="btn btn--primary" href="/servers/new">Create a server</a>
</div>
```

Per page:

| Page    | Icon          | Headline              | Body                                                                   | CTA                |
|---------|---------------|-----------------------|------------------------------------------------------------------------|--------------------|
| Home    | server stack  | "No servers yet"      | "Create your first Minecraft server to get started."                   | "Create a server"  |
| Players | players       | "No players online"   | "Players will appear here once someone joins a running server."        | (none — observer)  |
| Trash   | trash can     | "Trash is empty"      | "Deleted servers are kept here for 30 days before being purged."       | (none — terminal)  |

Notes:
- Players and Trash empty states are observational — no CTA. Don't invent
  one to satisfy the template.
- Icons: use a single Heroicons-style outline set, sized 48–64px,
  `currentColor`, `opacity: 0.4`. They're decorative; `aria-hidden="true"`.
- Don't use the empty state for transient loading — that's a different
  thing (skeleton or spinner).

---

## 7. Status pills / state indicators

**Recommended: solid pill with leading dot.** One pattern, applied
consistently. Six states map to a fixed palette:

| State       | Pill colour       | Dot      | Notes                              |
|-------------|-------------------|----------|------------------------------------|
| running     | `--success` solid | static   | Green-ish.                         |
| exited      | `--muted` solid   | static   | Neutral grey, not red.             |
| restarting  | `--warning` solid | pulsing  | Amber. Pulse via CSS animation.    |
| paused      | `--info` solid    | static   | Blue.                              |
| dead        | `--danger` solid  | static   | Red. Operator action required.     |
| pending\*   | `--warning` solid | spinner  | Optimistic transient (see §2).     |

\* "pending" is a UI-only state, not a docker state.

```html
<span class="pill pill--running">
  <span class="pill__dot"></span>
  running
</span>
```

```css
.pill {
  display: inline-flex; align-items: center; gap: 0.4em;
  padding: 0.2em 0.7em;
  border-radius: 999px;
  font-size: 0.85em; font-weight: 500;
  background: var(--pill-bg); color: var(--pill-fg);
}
.pill__dot {
  width: 0.5em; height: 0.5em; border-radius: 50%;
  background: currentColor;
}
.pill--running    { --pill-bg: color-mix(in oklab, var(--success) 18%, transparent); --pill-fg: var(--success); }
.pill--exited     { --pill-bg: color-mix(in oklab, var(--muted)   18%, transparent); --pill-fg: var(--muted);   }
.pill--restarting { --pill-bg: color-mix(in oklab, var(--warning) 18%, transparent); --pill-fg: var(--warning); }
.pill--paused     { --pill-bg: color-mix(in oklab, var(--info)    18%, transparent); --pill-fg: var(--info);    }
.pill--dead       { --pill-bg: color-mix(in oklab, var(--danger)  18%, transparent); --pill-fg: var(--danger);  }
.pill--restarting .pill__dot { animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.3; } }
```

Why solid (tinted) pill, not outline/ghost: at glance-distance, fill reads
faster than border. Ghost pills are fine for low-priority metadata
("v1.20.4") but state needs visual weight.

Why dot + label, not icon + label: dots scale to any pill size, work in
monochrome, and don't need an icon library lookup.

---

## 8. Data-table patterns

**Recommended: `<table>` for the home server list and the trash list.**

The home list is genuinely tabular: name, state, players, RAM, uptime,
actions. Each column is the same kind of value across rows — that is what
`<table>` is for. You get:

- Free row striping via `tr:nth-child(even)`.
- Free header semantics (`<th scope="col">`) for screen readers.
- Free column-alignment via `text-align` on `<th>`.
- Easy to add `<thead>`-based sortable hooks later.

Responsive trade-off is real but solvable. Two options:

1. **Card-on-mobile via CSS:** at narrow widths, set `table, tbody, tr, td`
   to `display: block` and use `data-label` attributes for pseudo-headers.
   Ugly markup, but works.
2. **Hide non-essential columns at narrow widths:** keep name, state,
   actions; drop players/RAM/uptime below 640px. Simpler, recommended.

```css
@media (max-width: 640px) {
  .server-list .col-players,
  .server-list .col-memory,
  .server-list .col-uptime { display: none; }
}
```

Use flex-row `<ul>` only when:
- The data isn't tabular (e.g. activity feed, log entries).
- Each "row" needs vertical content (sub-list, expanded panel).

Neither applies to home or trash. Use tables.

---

## 9. Polling poll-cards: freshness indicator

Polling silently is the worst failure mode — the operator can't tell
whether the panel is up-to-date or frozen. Add a small "updated Ns ago"
caption to each polling region.

Two implementations, by complexity:

**Server-rendered timestamp + client-side ticker.** The card includes a
`<time>` with the current UTC timestamp; a single page-level interval
updates the relative-time text every second.

```html
<!-- inside the polling card -->
<footer class="card__footer">
  <time class="freshness" datetime="{{ now.isoformat() }}">just now</time>
</footer>
```

```js
// app.js, runs once
setInterval(() => {
  document.querySelectorAll('.freshness').forEach(el => {
    const ts = new Date(el.getAttribute('datetime'));
    const s = Math.round((Date.now() - ts) / 1000);
    el.textContent = s < 5 ? 'just now'
                   : s < 60 ? `updated ${s}s ago`
                   : `updated ${Math.floor(s/60)}m ago`;
  });
}, 1000);
```

When the card is swapped (every 5s by HTMX), the `datetime` attribute
resets, the relative-time text snaps back to "just now". If polling stalls
(network drop, server hung), the counter keeps climbing — visibly.

Add a "stale" threshold: if the gap exceeds 2× the poll interval, paint the
freshness label in `--warning`:

```css
.freshness[data-stale="true"] { color: var(--warning); }
```

Set `data-stale` in the same setInterval. The visual cue is the whole point
of the freshness indicator — without staleness colouring, it's just decoration.

---

## 10. Focus management

When a modal partial swaps into `#modal`, focus must land on the first
interactive element (or the dialog itself, for screen readers).

Easiest: `hx-on::after-swap` on the modal container, calling `.focus()` on
the first input:

```html
<dialog id="modal"
        hx-on::after-swap="
          this.showModal();
          (this.querySelector('[autofocus], input, button, select, textarea, a')
            || this).focus();
        "></dialog>
```

If you stay on the custom `#modal` div instead of `<dialog>`, you lose the
free focus trap — you'll need to install one (or wear the bug). This is
half the reason §4 recommends migrating to `<dialog>`.

For non-modal swaps (form re-render with errors), focus the first invalid
field:

```html
<form hx-on::after-swap="this.querySelector('[aria-invalid=true]')?.focus()">
  ...
</form>
```

Restore focus on close: `<dialog>` does this automatically. With a custom
modal, stash `document.activeElement` before opening and `.focus()` it on
close.

---

## Cross-cutting principles

- **Server-render everything you can.** HTMX rewards keeping logic on the
  server. Client JS only for: focus, freshness ticker, type-name disable,
  optional swap-debounce.
- **One pattern per problem.** Don't mix outline pills and solid pills.
  Don't mix `setTimeout` flashes and CSS-animation flashes. Pick one and
  apply it everywhere.
- **No skeletons, no shimmer.** The actions are fast (sub-second) or slow
  (multi-second lifecycle). Fast doesn't need a skeleton; slow needs a real
  pending state (§2).
- **`aria-live`, `aria-busy`, `aria-invalid`, `role="status"`.** These are
  the four ARIA attributes you actually need. Use them; skip the rest.
- **Test offline-ish behaviour.** Kill the server, watch the freshness
  counter climb, verify the panel signals stale. That's the smoke test for
  this whole layer.
