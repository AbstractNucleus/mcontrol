# Anthropic / Claude visual language — research reference

**Date:** 2026-05-10
**Purpose:** Inform a Claude-flavoured theme for the mcontrol web panel.
**Confidence convention:** Tokens marked **[observed]** are pulled from a primary Anthropic source. **[best-effort]** = inferred from a primary source plus reasonable defaults. **[third-party]** = public reverse-engineering, sanity-check only.

## TL;DR — what makes something feel "Anthropic"

Three things, in order:

1. **A warm off-white surface** (`#FAF9F5` family) instead of pure white, paired with a near-black text colour that is _not_ pure black (`#141413`). This single substitution does most of the work.
2. **Soft, slightly desaturated terracotta orange** as the only saturated accent (`#D97757`). Used sparingly — should be the brightest pixel on the screen.
3. **Generous radii (8–12 px), hairline borders (0.5 px), barely-there shadows.** No heavy drop shadows, no neon focus rings, no purple-to-pink gradients.

The marketing site adds an editorial **Tiempos** serif over a slightly creamier ground. The app surface is more neutral. The recommended palette below leans app-flavoured (more usable for a dense control panel).

## 1. Color palette

### 1.1 Anthropic brand core (cross-surface)

These are the named brand colours from Anthropic's public brand-guidelines skill. **[observed]**

| Role | Hex | Notes |
|---|---|---|
| Brand dark | `#141413` | Primary text. Not pure black. |
| Brand light | `#FAF9F5` | Off-white "paper" — the signature warm ground. |
| Mid gray | `#B0AEA5` | Warm-leaning gray; muted text, dividers. |
| Light gray | `#E8E6DC` | Subtle backgrounds, separators on light. |
| Accent — Orange | `#D97757` | Primary brand accent. Terracotta / dusty clay. |
| Accent — Blue | `#6A9BCC` | Secondary brand accent. Quiet, dusty. |
| Accent — Green | `#788C5D` | Tertiary brand accent. Olive / sage. |

The gray ramp has a tiny yellow/green warmth — Anthropic neutrals are explicitly _not_ blue-cool.

### 1.2 App-surface tokens — authoritative semantic system

Pulled verbatim from `claude.com/docs/connectors/building/mcp-apps/design-guidelines`. **[observed]**

#### Backgrounds

| Token | Light | Dark |
|---|---|---|
| `--color-bg-primary`     | `#FFFFFF` | `#30302E` |
| `--color-bg-secondary`   | `#F5F4ED` | `#262624` |
| `--color-bg-tertiary`    | `#FAF9F5` | `#141413` |
| `--color-bg-inverse`     | `#141413` | `#FAF9F5` |
| `--color-bg-info`        | `#D6E4F6` | `#253E5F` |
| `--color-bg-danger`      | `#F7ECEC` | `#602A28` |
| `--color-bg-success`     | `#E9F1DC` | `#1B4614` |
| `--color-bg-warning`     | `#F6EEDF` | `#483A0F` |

Light: `primary` = white, `tertiary` = warm cream `#FAF9F5` (page background). Convention is _white panels on warm cream_, not the other way round. Dark mode flips: `primary` = `#30302E` (mid-gray-brown), `tertiary` = `#141413` (deepest near-black). Dark mode is intentionally low-contrast and warm.

#### Text

| Token | Light | Dark |
|---|---|---|
| `--color-text-primary`   | `#141413` | `#FAF9F5` |
| `--color-text-secondary` | `#3D3D3A` | `#C2C0B6` |
| `--color-text-tertiary`  | `#73726C` | `#9C9A92` |
| `--color-text-inverse`   | `#FFFFFF` | `#141413` |
| `--color-text-info`      | `#3266AD` | `#80AADD` |
| `--color-text-danger`    | `#7F2C28` | `#EE8884` |
| `--color-text-success`   | `#265B19` | `#7AB948` |
| `--color-text-warning`   | `#5A4815` | `#D1A041` |

#### Borders (hairlines)

All neutral borders are translucent so they pick up surface tint underneath.

| Token | Light (over `#1F1E1D`) | Dark (over `#DEDCD1`) |
|---|---|---|
| `--color-border-primary`   | 40% | 40% |
| `--color-border-secondary` | 30% | 30% |
| `--color-border-tertiary`  | 15% | 15% |
| `--color-border-disabled`  | 10% | 10% |

#### Semantic borders & rings

| Token | Light | Dark |
|---|---|---|
| `--color-border-info`    | `#4682D5` | `#4682D5` |
| `--color-border-danger`  | `#A73D39` | `#CD5C58` |
| `--color-border-success` | `#437426` | `#599130` |
| `--color-border-warning` | `#805C1F` | `#A87829` |
| `--color-ring-primary`   | `#141413 @ 70%` | `#FAF9F5 @ 70%` |

Focus rings = same near-black/near-white as text at 70% opacity. **No separate focus blue. The brand orange is NOT used as a focus ring.**

### 1.3 Recommended palette to ship for mcontrol

```css
:root {
  /* Surface */
  --bg-page:      #FAF9F5;
  --bg-surface:   #FFFFFF;
  --bg-sunken:    #F5F4ED;
  --bg-inverse:   #141413;

  /* Text */
  --fg-primary:   #141413;
  --fg-secondary: #3D3D3A;
  --fg-muted:     #73726C;
  --fg-inverse:   #FFFFFF;

  /* Hairlines (translucent — pick up surface tint) */
  --border-strong: rgba(31, 30, 29, 0.40);
  --border-medium: rgba(31, 30, 29, 0.30);
  --border-soft:   rgba(31, 30, 29, 0.15);

  /* Brand accent — use sparingly, one place per screen */
  --accent:        #D97757;
  --accent-hover:  #C5613F;
  --accent-soft:   #F4DDD1;

  /* Semantic */
  --info-bg:    #D6E4F6; --info-fg:    #3266AD; --info-border:    #4682D5;
  --success-bg: #E9F1DC; --success-fg: #265B19; --success-border: #437426;
  --warning-bg: #F6EEDF; --warning-fg: #5A4815; --warning-border: #805C1F;
  --danger-bg:  #F7ECEC; --danger-fg:  #7F2C28; --danger-border:  #A73D39;

  --ring: rgba(20, 20, 19, 0.70);
}

/* dark via [data-theme="dark"] (explicit) */
[data-theme="dark"] {
  --bg-page:      #141413;
  --bg-surface:   #30302E;
  --bg-sunken:    #262624;
  --bg-inverse:   #FAF9F5;

  --fg-primary:   #FAF9F5;
  --fg-secondary: #C2C0B6;
  --fg-muted:     #9C9A92;
  --fg-inverse:   #141413;

  --border-strong: rgba(222, 220, 209, 0.40);
  --border-medium: rgba(222, 220, 209, 0.30);
  --border-soft:   rgba(222, 220, 209, 0.15);

  --accent:        #D97757;
  --accent-hover:  #E08B6F;
  --accent-soft:   #3A241B;

  --info-bg:    #253E5F; --info-fg:    #80AADD; --info-border:    #4682D5;
  --success-bg: #1B4614; --success-fg: #7AB948; --success-border: #599130;
  --warning-bg: #483A0F; --warning-fg: #D1A041; --warning-border: #A87829;
  --danger-bg:  #602A28; --danger-fg:  #EE8884; --danger-border:  #CD5C58;

  --ring: rgba(250, 249, 245, 0.70);
}
```

Borders are translucent on purpose — warmth comes from the surface bleeding through. Don't substitute opaque grays. Dark-mode ground `#141413` is intentionally not pure black.

## 2. Typography

| Surface | Heading | Body | Mono |
|---|---|---|---|
| anthropic.com (marketing) | Styrene B | Tiempos Text | varies |
| claude.ai (chat app) | Styrene B | Styrene B | system mono |
| MCP-apps tokens | "Anthropic Sans" | "Anthropic Sans" | `ui-monospace` |

Styrene/Tiempos/"Anthropic Sans" are licensed/proprietary. We use open fallbacks.

### Recommended type stack

```css
:root {
  --font-sans: "Inter Tight", "Söhne", "Inter", -apple-system,
               BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;

  --font-mono: ui-monospace, "JetBrains Mono", "Fira Code",
               SFMono-Regular, Menlo, Consolas, monospace;
}
```

**Inter Tight** (not regular Inter) tracks Styrene B's slightly-condensed proportions. No serif accent for the panel — claude.ai's chat surface is sans throughout.

### Type scale (verbatim from MCP-apps tokens)

| Role | Size | Line-height |
|---|---|---|
| text-xs | 12 | 1.4 |
| text-sm | 14 | 1.4 |
| text-md (body) | 16 | 1.4 |
| text-lg | 20 | 1.25 |
| heading-md | 16 | 1.4 |
| heading-lg | 20 | 1.25 |
| heading-xl | 24 | 1.25 |
| heading-2xl | 28 | 1.1 |
| heading-3xl | 36 | 1.0 |

Weights: 400 / 500 / 600 / 700. No 300 — light weights are not part of the Claude voice.

### Letter-spacing

- Body: none.
- Display headings (28+): -0.01 em to -0.02 em (slightly tight).
- Eyebrows / all-caps labels: +0.04 em.

## 3. Components

### Radius scale (verbatim) **[observed]**

| Token | Value | Use |
|---|---|---|
| --radius-xs   | 4 px  | tags, code-block inline |
| --radius-sm   | 6 px  | inputs |
| --radius-md   | 8 px  | buttons, cards |
| --radius-lg   | 10 px | larger cards, dialogs |
| --radius-xl   | 12 px | hero panels |
| --radius-full | 9999  | avatars, pills |

**Buttons are 8 px** — soft but not bubbly.

### Buttons

- **Primary:** `--bg-inverse` ground, `--fg-inverse` text, no border, 8 px radius. There is no orange primary by default in claude.ai — but for a single-app panel that wants Anthropic flavour, putting orange on the most-important CTA per screen is right; just don't repeat it three times on the same screen.
- **Secondary:** transparent ground, 0.5 px `--border-medium`, `--fg-primary` text. Hover: `--bg-sunken` ground.
- **Ghost:** transparent ground, no border, `--fg-secondary` text. Hover: `--bg-sunken` ground.
- **Destructive:** `--danger-fg` text, `--danger-border` border, transparent. Confirmed-destructive: solid `--danger-border` ground, white text.
- Padding: `8px 14px` default, `6px 10px` small, `12px 18px` large.
- Min height: 32 / 36 / 44.

### Inputs

- Resting: 0.5 px `--border-medium`, `--bg-surface` ground, 6 px radius.
- Hover: border to `--border-strong`.
- Focus: 2 px outline `--ring`, 2 px offset, no border colour change.
- Invalid: border `--danger-border`, ring `--color-ring-danger`.
- Disabled: `--bg-sunken`, `--fg-muted`, no border.

### Cards & elevation

Default cards: **no shadow** — 1-step-lighter background (`--bg-surface` over `--bg-page`) with optional `--border-soft` hairline. Reserve shadows for things that float over content.

```
--shadow-sm: 0 1px 3px 0 rgba(0,0,0,0.10), 0 1px 2px -1px rgba(0,0,0,0.10);
--shadow-md: 0 4px 6px -1px rgba(0,0,0,0.10), 0 2px 4px -2px rgba(0,0,0,0.10);
--shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.10), 0 4px 6px -4px rgba(0,0,0,0.10);
```

### Dialogs

- Centered, 12 px radius, `--bg-surface` ground, `--shadow-lg`.
- Backdrop: `rgba(20, 20, 19, 0.40)` light / `rgba(20, 20, 19, 0.65)` dark.
- Subtle blur (`backdrop-filter: blur(4px)`) is on-brand; heavy blur is not.
- Padding 24 px; header/body/footer separated by 16 px gaps, not hairlines.

### Empty states

claude.ai: **text-only**. Never illustrated characters, never colourful spot illustrations. One line of `--fg-secondary` body + one secondary button, centered. Mimic this.

## 4. Motion & feedback

(Anthropic doesn't publish motion tokens — these are **[best-effort]**.)

| Token | Value | When |
|---|---|---|
| --motion-fast | 120 ms | hover, focus, press |
| --motion-base | 200 ms | toggles, accordion |
| --motion-slow | 320 ms | modal in, drawer in |
| --motion-ease | `cubic-bezier(0.2, 0.8, 0.2, 1)` | "soft out" — claude.ai feel |
| --motion-ease-in | `cubic-bezier(0.4, 0, 1, 1)` | modal/dropdown out |

Avoid: bounces, springs, parallax. Anthropic motion is calm and short.

### Focus ring

```css
:focus-visible {
  outline: 2px solid var(--ring);
  outline-offset: 2px;
  border-radius: inherit;
  transition: outline-color var(--motion-fast) var(--motion-ease);
}
```

Single ring, `outline` (not `box-shadow`), 2 px solid, 2 px offset. Colour is 70%-opacity near-black/white — picks up surface tint, works on every background. **Never orange.**

### Loading

claude.ai uses a 3-dot pulse, not a spinner. For indeterminate states: 8 px dots, 4 px gap, 0.3→1.0→0.3 opacity, 1.4 s cycle, 0.16 s stagger.

Determinate progress: 2 px hairline bar in `--accent` over `--bg-sunken` track. No glossy gradient.

## 5. Spacing

4 px base unit:

| Token | px |
|---|---|
| space-1 | 4 |
| space-2 | 8 |
| space-3 | 12 |
| space-4 | 16 |
| space-5 | 20 |
| space-6 | 24 |
| space-8 | 32 |
| space-10 | 40 |
| space-12 | 48 |
| space-16 | 64 |

Conventions:

- Card padding: 16–24 px. 24 is more Anthropic.
- Stack siblings: 8 tight, 12 default, 16 loose.
- Section gutters (marketing-flavoured): 64–96.
- Form fields: 8 between label and input, 16 between fields.

When in doubt, add padding, not borders.

## 6. Quick decisions for mcontrol

If you only do five things:

1. **Page is `#FAF9F5`, cards are `#FFFFFF`.** Single move buys 60% of the Anthropic feel.
2. **Body text is `#141413` over `#FAF9F5`, in Inter Tight at 16/22.** Not pure black, not pure white.
3. **One terracotta `#D97757` accent per view.** On the most-important CTA. Everywhere else stays neutral.
4. **8 px button radius, 0.5 px translucent borders, no shadows on cards.** Use a one-step-lighter background for inline elevation.
5. **Focus rings `rgba(20, 20, 19, 0.70)`, 2 px outline, 2 px offset.** Never orange.

## Sources

Primary (Anthropic-published):

- `claude.com/docs/connectors/building/mcp-apps/design-guidelines` — authoritative semantic-token system. All `color-*`, `font-*`, `border-radius-*`, `shadow-*` values pulled verbatim.
- `github.com/anthropics/skills/blob/main/skills/brand-guidelines/SKILL.md` — official brand colours.
- `platform.claude.com/cookbook/coding-prompting-for-frontend-aesthetics` — published opinion on font choices, accent strategy, "AI slop" avoidance.

Secondary (cross-checked):

- `type.today/en/journal/anthropic` — Commercial Type's writeup confirming Styrene B + Tiempos Text for marketing.
- `github.com/motgenror/claude-css` — third-party userstyle (used for token-naming pattern only, not hex values).
