# Dark + Light Mode Patterns for mcontrol

Reference for implementing theme switching in a server-rendered Jinja + handwritten-CSS + HTMX app, no JS bundler. Opinionated; pick one path per section and move on.

## 1. Toggle UX: tri-state (system / light / dark)

**Decision: tri-state, default "system".**

What claude.ai does: tri-state. The settings panel exposes "System", "Light", "Dark" as a radio group. New users land on "System", which honours the OS-level `prefers-color-scheme`. Once the user picks Light or Dark explicitly, that choice sticks across reloads and devices (claude.ai persists server-side via the account; we'll persist client-side — see section 2).

For a single-operator panel like mcontrol, the temptation is to skip "system" and just give a binary toggle. Resist it. The cost of a third state is one extra icon and one extra branch in the toggle handler; the benefit is that the operator who runs a dark-themed OS by day and a light-themed laptop by night gets the right thing automatically without ever opening the panel's settings. "System" is the correct default because it's the lowest-surprise option — the panel matches the rest of the operator's environment.

**Trade-off:** binary is simpler to implement (no "auto" state to reason about, no `matchMedia` listener for live OS theme changes). Tri-state costs ~10 extra lines of JS and one extra icon. Worth it.

## 2. Persistence: localStorage + inline `<head>` script

**Decision: localStorage holds the user choice; an inline `<head>` script applies `data-theme` before stylesheets evaluate.**

Cookie-only is tempting because the server could render the right theme on the first byte — but it forces every request through a cookie round-trip and conflates "operator preference" with "session state". `prefers-color-scheme`-only loses the user's explicit override across reloads. localStorage + inline head script is the modern static-site pattern (used by MDN, Tailwind docs, GitHub's docs site, shadcn/ui starter, every Astro/Next theme template) and it's what we want.

The flash of wrong theme ("FOUC" / "FART" / "flash of inaccurate render of theme") happens when the stylesheet computes against the default `:root` colours, paints, and *then* a deferred script flips `data-theme`. The fix: a synchronous inline script in `<head>`, **before** the stylesheet `<link>`, that reads localStorage and sets `data-theme` on `<html>` before the first paint.

### Canonical inline script

Place this **immediately after `<meta charset>` and before any `<link rel="stylesheet">`** in the base Jinja template:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <script>
      // Theme bootstrap. Runs before stylesheet to prevent flash.
      // Reads stored choice ("light" | "dark" | "system" | null).
      // Resolves "system" / null via prefers-color-scheme.
      // Sets data-theme="light" or data-theme="dark" on <html>.
      (function () {
        try {
          var stored = localStorage.getItem("theme");
          var resolved = stored;
          if (!stored || stored === "system") {
            resolved = window.matchMedia("(prefers-color-scheme: dark)").matches
              ? "dark"
              : "light";
          }
          document.documentElement.setAttribute("data-theme", resolved);
        } catch (_) {
          // localStorage blocked (private mode, etc.) — fall through to CSS @media.
        }
      })();
    </script>
    <link rel="stylesheet" href="{{ url_for('static', filename='app.css') }}">
    <!-- ... -->
```

Notes on the snippet:

- The IIFE keeps the global namespace clean.
- `try/catch` covers private-browsing modes that throw on `localStorage` access — when it fails, the CSS `@media (prefers-color-scheme: dark)` fallback (section 6) takes over, so the user still gets a sensible theme.
- We resolve `"system"` to a concrete `"light"` / `"dark"` so all our CSS only needs two branches (`:root` + `[data-theme="dark"]`), not three. The toggle UI separately remembers the user's *intent* (`"system"`).
- The stylesheet `<link>` comes *after* the script, so by the time the browser parses the CSS, `data-theme` is already set and the right variables apply on first paint.

### Toggle handler (loaded later, deferred is fine)

```html
<script defer src="{{ url_for('static', filename='theme-toggle.js') }}"></script>
```

```js
// theme-toggle.js
(function () {
  var KEY = "theme";
  var media = window.matchMedia("(prefers-color-scheme: dark)");

  function apply(intent) {
    var resolved = intent === "system" || !intent
      ? (media.matches ? "dark" : "light")
      : intent;
    document.documentElement.setAttribute("data-theme", resolved);
  }

  function set(intent) {
    if (intent === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, intent);
    apply(intent);
    document.dispatchEvent(new CustomEvent("themechange", { detail: intent }));
  }

  // Live-update when OS theme changes and user is on "system".
  media.addEventListener("change", function () {
    if (!localStorage.getItem(KEY)) apply("system");
  });

  // Wire up the toggle button(s).
  document.querySelectorAll("[data-theme-set]").forEach(function (el) {
    el.addEventListener("click", function () {
      set(el.getAttribute("data-theme-set"));
    });
  });
})();
```

### CSP implications

Inline scripts require either `script-src 'unsafe-inline'` or a per-page nonce/hash. For a single-operator panel this is a minor concern — but the right answer is a **nonce**, not `unsafe-inline`:

```python
# Flask-side, per-request nonce
from secrets import token_urlsafe
@app.before_request
def _csp_nonce():
    g.csp_nonce = token_urlsafe(16)

@app.after_request
def _csp_header(resp):
    resp.headers["Content-Security-Policy"] = (
        f"default-src 'self'; "
        f"script-src 'self' 'nonce-{g.csp_nonce}'; "
        f"style-src 'self'; "
        f"img-src 'self' data:;"
    )
    return resp
```

```html
<script nonce="{{ g.csp_nonce }}">
  /* theme bootstrap as above */
</script>
```

If we end up using `script-src 'self'` only and refusing inline scripts entirely, we lose this pattern and accept a brief FOUC. Not worth it — use the nonce.

## 3. CSS variable architecture

**Decision: two layers. Primitives at the bottom, semantic tokens on top. Components only reference semantic tokens.**

### Primitive layer (raw scale, theme-agnostic)

```css
:root {
  /* Neutral scale */
  --gray-50:  #fafafa;
  --gray-100: #f4f4f5;
  --gray-200: #e4e4e7;
  --gray-300: #d4d4d8;
  --gray-400: #a1a1aa;
  --gray-500: #71717a;
  --gray-600: #52525b;
  --gray-700: #3f3f46;
  --gray-800: #27272a;
  --gray-900: #18181b;
  --gray-950: #09090b;

  /* Accent (claude orange-ish; substitute project colour) */
  --accent-500: #d97757;
  --accent-600: #c2410c;
  --accent-100: #fef3c7;

  /* Status hues */
  --green-500: #22c55e;
  --amber-500: #f59e0b;
  --red-500:   #ef4444;
  --blue-500:  #3b82f6;
}
```

### Semantic layer (the only thing components reference)

```css
:root {
  --surface:           var(--gray-50);
  --surface-elevated:  #ffffff;
  --surface-sunken:    var(--gray-100);
  --text-primary:      var(--gray-900);
  --text-muted:        var(--gray-500);
  --text-inverse:      var(--gray-50);
  --accent:            var(--accent-600);
  --accent-fg:         #ffffff;
  --border:            var(--gray-200);
  --border-strong:     var(--gray-300);
  --success:           var(--green-500);
  --warning:           var(--amber-500);
  --danger:            var(--red-500);
  --info:              var(--blue-500);
  --focus-ring:        var(--accent-500);
  --shadow-sm:         0 1px 2px rgb(0 0 0 / 0.06);
  --shadow-md:         0 4px 12px rgb(0 0 0 / 0.08);
}

[data-theme="dark"] {
  --surface:           var(--gray-950);
  --surface-elevated:  var(--gray-900);
  --surface-sunken:    #000000;
  --text-primary:      var(--gray-50);
  --text-muted:        var(--gray-400);
  --text-inverse:      var(--gray-900);
  --accent:            var(--accent-500);   /* lighter accent on dark */
  --accent-fg:         var(--gray-950);
  --border:            var(--gray-800);
  --border-strong:     var(--gray-700);
  --focus-ring:        var(--accent-500);
  --shadow-sm:         0 1px 2px rgb(0 0 0 / 0.4);
  --shadow-md:         0 4px 12px rgb(0 0 0 / 0.5);
}
```

### Why two layers

A single semantic layer means every dark-mode tweak ("the muted text needs to be one step lighter") is a hex-code edit, and you lose the ability to verify the palette is internally consistent. A primitive scale gives you that consistency for free.

A primitive-only system (components use `--gray-700` directly) means every theme switch requires touching every component — exactly the thing CSS variables are supposed to fix.

**Rule for component CSS:** if you find yourself typing `var(--gray-` anywhere outside the semantic-token block, stop and add a semantic token. Components reference *meaning* (`--text-muted`), not *value* (`--gray-500`).

## 4. Accessibility

- **Contrast.** WCAG AA: body text >= 4.5:1, large text (>= 18pt or 14pt bold) >= 3:1, UI component boundaries and graphical objects >= 3:1. Verify each `--text-*` against each `--surface-*` it can land on, in both themes. Use a contrast checker on the final hex values, not vibes. The dark-mode `--text-muted` is the usual offender — `--gray-400` on `--gray-950` is ~7:1, fine; `--gray-500` on `--gray-900` is ~4.6:1, borderline.
- **Focus ring.** Always visible, distinct on both surfaces, never removed without replacement. Use `:focus-visible` (not `:focus`) to avoid showing the ring on mouse clicks while keeping it for keyboard nav:

  ```css
  :focus-visible {
    outline: 2px solid var(--focus-ring);
    outline-offset: 2px;
    border-radius: 2px;
  }
  ```

  The `--focus-ring` token must contrast >= 3:1 against every surface it can appear on. The accent works in both themes here.
- **Reduced motion.** Honour `prefers-reduced-motion: reduce` for theme-transition animations specifically (see below) and any other transitions/animations:

  ```css
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
      scroll-behavior: auto !important;
    }
  }
  ```

- **Icon-only toggle trap.** A button whose only content is `<svg>...</svg>` has no accessible name. Always:

  ```html
  <button
    type="button"
    data-theme-set="dark"
    aria-label="Switch to dark theme"
    aria-pressed="false">
    <svg aria-hidden="true" focusable="false">...</svg>
  </button>
  ```

  Update `aria-label` and `aria-pressed` when the state changes (the `themechange` handler does this). For tri-state, model it as a radiogroup of three buttons with `role="radio"` and `aria-checked`, or as a `<select>` — the radiogroup gives better keyboard semantics.

## 5. Toggle button placement

**Decision: top-right of the page chrome, in the header/navbar. Tri-state with sun / moon / monitor icons. Default visible icon = the *currently resolved* theme.**

Top-right is canonical because every major web app puts it there (claude.ai, GitHub, Linear, Vercel, every docs site). Operators don't read the manual; they look top-right.

For tri-state, two patterns:

1. **Single button that cycles** light → dark → system → light. Cheaper to render, but the user has to click up to twice to land on a known state, and the icon has to convey both *current* and *next*.
2. **Three radio buttons** (sun / moon / monitor) in a small segmented control. Slightly more chrome, but every state is one click away and the current state is obvious.

Use option 2. It's three icons in a 96px-wide segmented control, fits the header fine, and is what claude.ai's settings panel does (just inline rather than tucked in a modal).

Icon set: lucide-icons `sun` / `moon` / `monitor` (or any equivalent — `feather`, `tabler`, etc.). Sun/moon for light/dark is universal; monitor (or `laptop`, or `settings`) for "follow system".

## 6. `prefers-color-scheme` fallback in CSS

**Decision: `:root` defines light. `[data-theme="dark"]` defines dark. `@media (prefers-color-scheme: dark)` defines dark **only when `data-theme` is unset**, as a JS-disabled / localStorage-blocked fallback.**

The shape:

```css
/* 1. Light is the default. */
:root {
  --surface: #fafafa;
  --text-primary: #18181b;
  /* ... */
}

/* 2. Explicit dark mode (set by the head script). */
[data-theme="dark"] {
  --surface: #09090b;
  --text-primary: #fafafa;
  /* ... */
}

/* 3. Fallback: when JS is off and user prefers dark, follow OS. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme]) {
    --surface: #09090b;
    --text-primary: #fafafa;
    /* ... same as [data-theme="dark"] */
  }
}
```

The `:not([data-theme])` selector is critical — without it, the `@media` block would override `[data-theme="light"]` for users who explicitly chose light on a dark-OS machine.

To avoid duplicating the dark-mode block, factor it out:

```css
:root {
  color-scheme: light;
  /* light tokens */
}

@mixin dark-tokens {
  /* (in plain CSS, copy-paste; in any preprocessor, mixin) */
}

[data-theme="dark"] {
  color-scheme: dark;
  /* dark tokens */
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme]) {
    color-scheme: dark;
    /* dark tokens (duplicated in plain CSS — acceptable) */
  }
}
```

Plain handwritten CSS will duplicate the dark block. That's fine — it's ~30 lines and changes rarely. The alternative (CSS custom-property toggling via `light-dark()`) is Baseline 2024 but not yet broadly safe; revisit in 2027.

## 7. Image / icon theming

- **SVG icons:** author them with `fill="currentColor"` and/or `stroke="currentColor"` (no hardcoded colours), then style via the parent's `color`. One asset, themes for free.

  ```html
  <button class="icon-btn" aria-label="Refresh">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" stroke-width="2" aria-hidden="true">
      <path d="..."/>
    </svg>
  </button>
  ```

  ```css
  .icon-btn { color: var(--text-muted); }
  .icon-btn:hover { color: var(--text-primary); }
  ```

- **Logos that need a true light/dark variant** (multi-colour artwork, branded marks): ship two files, switch via CSS `display`, never via JS swap. JS swap costs a paint and flashes during the toggle; CSS switch is instant.

  ```html
  <picture class="logo">
    <img class="logo-light" src="/static/logo-light.svg" alt="mcontrol">
    <img class="logo-dark"  src="/static/logo-dark.svg"  alt="" aria-hidden="true">
  </picture>
  ```

  ```css
  .logo-dark { display: none; }
  [data-theme="dark"] .logo-light { display: none; }
  [data-theme="dark"] .logo-dark  { display: inline; }
  ```

  (The `alt` on the dark variant is empty + `aria-hidden` so screen readers don't read "mcontrol" twice.)

- **Bitmap screenshots / dashboard illustrations:** if you have them, the `<picture>` element with `media="(prefers-color-scheme: dark)"` works for the OS preference but doesn't pick up `[data-theme]`. For a single-operator panel, ship one variant; if you must theme bitmaps, use the same display-toggle pattern.

## 8. Common pitfalls

- **`color-scheme`.** Set it on `:root`. This tells the UA that form controls, scrollbars, and the default canvas should use the matching native dark/light treatment. Without it, `<input>` and `<select>` render with light-mode UA defaults inside a dark page. Costs zero, fixes a class of bugs.

  ```css
  :root                    { color-scheme: light; }
  [data-theme="dark"]      { color-scheme: dark;  }
  ```

- **System fonts.** `font-family: system-ui` resolves to wildly different fonts (San Francisco on macOS, Segoe UI on Windows, Roboto/whatever on Linux). Inter on macOS Safari renders heavier than Inter on Linux Chrome because of antialiasing differences. Pick one of:
  1. Self-host one webfont (Inter, IBM Plex, JetBrains Mono) and accept the ~30 KB cost.
  2. Use the modern fallback stack: `system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` and design for the variance.

  For mcontrol, option 2 is fine — single-operator panel, not a brand surface.

- **Scrollbar theming (Chromium).** Default scrollbars are jarring in dark mode. Use the modern `scrollbar-color` and `scrollbar-width` (Firefox + Chromium 121+) before reaching for `::-webkit-scrollbar`:

  ```css
  :root {
    scrollbar-color: var(--gray-300) transparent;
    scrollbar-width: thin;
  }
  [data-theme="dark"] {
    scrollbar-color: var(--gray-700) transparent;
  }
  ```

  `::-webkit-scrollbar` is still needed for finer control on older Chromium; skip it unless a specific scrollbar is ugly enough to justify the bytes.

- **Theme-switch transition.** Don't animate `background-color` on `*` — it causes a slow ripple across the page and ironically makes the switch *feel* slower. Either no transition (snappy, what claude.ai does) or a very short one (`transition: background-color 120ms` on specific surfaces). Skip transitions entirely under `prefers-reduced-motion`.

- **HTMX swaps inheriting theme.** Because `data-theme` lives on `<html>`, every fragment HTMX swaps in inherits it via CSS variables — no extra plumbing needed. Don't try to pass theme state through `hx-vals`; it's already available via the cascade.

- **Server-rendered `aria-pressed` / `aria-checked`.** The Jinja template doesn't know which theme is active (the cookie path would, but we deliberately chose localStorage). So the initial `aria-checked` values are wrong until the toggle handler runs. Two fixes:
  1. Keep `aria-checked="false"` on all three buttons in markup; the toggle handler updates the right one on `DOMContentLoaded`.
  2. Render the segmented control inside a small `<noscript>` fallback that hides it (the toggle is useless without JS anyway).

- **Print styles.** Force light tokens for print. Most users print to white paper, dark mode on paper is wasteful and unreadable:

  ```css
  @media print {
    :root, [data-theme="dark"] {
      --surface: #ffffff;
      --text-primary: #000000;
      /* ... */
    }
  }
  ```
