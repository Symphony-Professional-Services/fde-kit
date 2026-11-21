---
name: symphony-ui-design
description: Symphony Design System (SDS Core UI) tokens for building any Symphony UI - extension apps, MCP app UIs, bot web consoles, dashboards and React apps. Ships a vendored symphony-tokens.css (light, dark and condensed, generated from the SDS Core UI Figma file), a Tailwind/shadcn preset, a host-theme helper and a token audit script. Use when building or restyling a Symphony UI, choosing colors, fonts, spacing or radius, auditing an app for hardcoded styles, or when an app does not look like Symphony.
---

# Symphony UI design

Every Symphony UI uses **one token file generated from the SDS Core UI Figma file**, not hex values typed from memory. If you are about to write a color, font or spacing literal, stop and use a token.

This skill covers the visual layer: color, type, spacing, radius, elevation and theming. For reviewing a screen or flow (hierarchy, states, accessibility, handoff), use `ux-design`. For UI copy (voice, capitalization, punctuation, terminology), use `ux-writing`. Run all three when building a Symphony interface end to end.

## Prerequisites

This skill needs a shell-capable agent and `python3` (standard library only). Copying the vendored assets and running `token_audit.py` need nothing else. Re-syncing from Figma also needs a Figma personal access token in `FIGMA_PAT`, or a path to it in `FIGMA_PAT_FILE`.

## Required workflow

> **Bundled Files in This Portable Runtime Copy (`template-mcp`)**:
> This directory ships the runtime assets and verifier needed by `template-mcp` and scaffolded repositories:
> - `assets/symphony-tokens.css` (Layer-1 SDS Core UI v1.0.0 token stylesheet)
> - `assets/symphony-theme.js` (Host theme & density sync helper)
> - `scripts/token_audit.py` (Zero-dependency token & contrast auditor)
> - `references/tokens.json` (Resolved light/dark token catalog)
>
> Maintainer-only upstream token-generation files (`scripts/sync_figma.py`, `scripts/build_tokens.py`, `tokens/semantic-map.json`, `assets/tailwind-preset.cjs`, `assets/symphony-tokens-legacy.css`, `references/ai-studio-delta.md`, `references/fde-patterns.md`) live in the canonical `ai-skills` repository rather than inside downstream MCP servers.

1. **Vendor the tokens.** Copy from this skill's `assets/` into the app's static folder:
   - `symphony-tokens.css` (always)
   - `symphony-theme.js` (only for pages the host does not theme, see "Theme and density")
   - `tailwind-preset.cjs` *(upstream `ai-skills` — React/Tailwind apps)*
   - `symphony-tokens-legacy.css` *(upstream `ai-skills` — only while migrating older variable names)*

   Load `symphony-tokens.css` **before** the app's own CSS. Never edit the vendored copy.
2. **Style with semantic tokens only**: `var(--background)`, `var(--foreground)`, `var(--accent)`, `var(--space-3)`... Use `--sds-*` primitives only for chart series or brand illustrations.
3. **Run the audit before calling UI work done:**
   ```bash
   python3 <this-skill>/scripts/token_audit.py <app-ui-dir>
   ```
   It reports raw color literals (with the SDS replacement), legacy variable names, undefined `var(--x)`, a missing or outdated vendored token file, and `alert/confirm/prompt` calls. Warn-only by default, `--strict` exits non-zero.
4. **Check it renders** in light **and** dark, spacious **and** condensed, and screenshot both themes.

## Semantic tokens (v1.0.0)

Source: Figma "❖ SDS Core UI". **figma** = role stated in the Figma style description. **inferred** = chosen following the same pattern, pending confirmation from design.

| Token | Light | Dark | Source | Use for |
|---|---|---|---|---|
| `--background` | White `#FFFFFF` | Graphite/90 `#141618` | figma | Page canvas |
| `--surface` / `--muted` | Graphite/05 `#F1F1F3` | Graphite/80 `#27292C` | figma | Panels, toolbars, side areas |
| `--card` | White | Graphite/80 | inferred | Cards (with `--shadow-1`) |
| `--popover` | White | Graphite/80 | figma | Menus, popovers (with `--shadow-2`) |
| `--foreground` | Graphite/80 `#27292C` | Graphite/05 `#F1F1F3` | figma | Body text, headings |
| `--foreground-secondary` | Graphite/60 | Graphite/20 | inferred | Secondary copy |
| `--muted-foreground` | Graphite/50 `#717681` | Graphite/40 `#8F959E` | figma/inferred | Labels, timestamps, captions |
| `--border` | Graphite/20 | Graphite/70 | inferred | Dividers, card outlines |
| `--input` | Graphite/40 | Graphite/50 | figma/inferred | Form control borders, icons (3:1) |
| `--accent` / `--ring` / `--info` | Electricity UI/50 `#0277D6` | Electricity UI/40 `#2996FD` | figma | Links, active tab, selection, focus, icons |
| `--accent-subtle` | Electricity UI/05 | Electricity UI/80 | inferred | Selected row, info banners |
| `--primary` (+`-hover`, `-foreground`) | Electricity UI/50 + white | same | inferred | Primary button **fill** (white label holds 4.5:1) |
| `--destructive` (+`-foreground`) | Red/50 + white | same | inferred | Destructive button fill |
| `--destructive-text` | Red/50 `#DD342E` | Red/40 `#FF5D50` | figma | Error text, icons, borders |
| `--success` / `--warning` (+`-subtle`) | Green/50, Yellow/50 | Green/40, Yellow/30 | inferred | Status dots and text |
| `--secondary` | Graphite/10 | Graphite/70 | inferred | Secondary buttons, segmented controls, row hover |
| `--overlay` | black 80% | black 80% | figma | Modal backdrop |
| `--shadow-1/2/3` | Figma Elevation 1-3 | Figma Elevation 1-3 | figma | Card, menu, modal |

**`#0098FF` is not an SDS color.** Brand Electricity is `#008EFF` (logos and marketing only). Product UI blue is Electricity UI/50 on light and UI/40 on dark.

Other tokens:
- **Type:** `--font-sans` is the platform system font. Figma's UI styles are Segoe UI, falling back to `-apple-system`/system-ui. `--font-mono` is SF Mono, then ui-monospace. Do **not** load Inter or other web fonts. Graphik LC is the licensed brand face for marketing only. Sizes come from Figma `Windows/*`: `--text-{h1,h2,h3,h4,body,small,xs}-{size,line,weight}`, for example body 14/20, h1 18/24 600, small 12/16, xs 11/16.
- **Spacing:** `--space-1`..`--space-7` = 4, 8, 16, 24, 32, 48, 64px (Figma S1-S7, 8px base). Under `.condensed`, S3 and up drop by 4px.
- **Radius:** `--radius-xs` 3px (badges), `--radius-sm` 4px (inputs), `--radius-md` 8px (cards, menus; inferred), `--radius-pill` (buttons: SDS buttons are full pills).
- **Controls:** `--control-sm/md/lg` = 24/32/40px button heights.

Full resolved values: `references/tokens.json`. Every Figma color is also available as `--sds-<ramp>-<step>`, for example `--sds-graphite-90` and `--sds-electricity-ui-40`.

## Theme and density

- **Inside a Symphony extension app view**, the ADK's `connectView()` puts `light|dark` and `spacious|condensed` on `<body>` and follows the client's theme changes. The token CSS keys off those classes, so there is nothing else to do. Do not hardcode a dark canvas.
- **Pages the host does not theme** (standalone pages, local previews): include `symphony-theme.js`. It reads `?theme=`, `?id=<app>_<theme>`, a same-origin parent's `currentThemeName` and `postMessage({type:'themeChange'})`, and falls back to `prefers-color-scheme`.
- **React/Tailwind:** use the preset (`darkMode: ["class"]`) and toggle `.dark` from the host theme.

## Stack rules

- **CSS variables first.** Vanilla apps use `symphony-tokens.css` directly.
- **React apps:** Tailwind + shadcn/ui + Radix + Lucide. The preset keeps shadcn names (`bg-background`, `text-muted-foreground`, `bg-primary`), so shadcn components work unchanged. Spacing keys `1`..`7` are SDS steps, not Tailwind's 0.25rem scale.
- Never hardcode hex. For tints use the `-subtle` tokens, not arbitrary opacity (`/80`, `rgba(...)`).
- Icons are Lucide only.
- Every data component has a loading state.
- Touch targets are at least 40px (`--control-lg`) on tablet and mobile.
- Never use `window.alert/confirm/prompt` in an embedded app. Sandboxed cross-origin iframes block them, so use a DOM modal (`--overlay` backdrop, `--popover` + `--shadow-3`) and toasts.
- **Copy and capitalization follow `ux-writing`.** Don't restate those rules here. Known open question: `ux-writing` makes buttons all uppercase, while the SDS Core UI button components use sentence case labels. Confirm with design before changing either.

## Changing tokens (they will evolve)

| Change | Do |
|---|---|
| Figma styles changed | `python3 scripts/sync_figma.py`, then `python3 scripts/build_tokens.py` |
| A role mapping should change (e.g. design confirms success = Green/40) | Edit `tokens/semantic-map.json` (set `source`, bump `version`), then `build_tokens.py` |
| Check outputs are current (CI) | `python3 scripts/build_tokens.py --check` |
| Roll out to apps | Re-copy `assets/`. The audit flags apps whose vendored copy is behind |

`build_tokens.py` fails when a mapped Figma style was renamed or deleted, or a contrast pair in `contrast_checks` drops below its minimum.

Figma variables (the designers' own role mapping) are not readable through the REST API without the Enterprise-only `file_variables:read` scope. Until they are, the semantic map is maintained by hand and the `inferred` rows are the ones to confirm with design.

## References

- [`references/tokens.json`](./references/tokens.json): every resolved token, both themes, with its Figma source (bundled here).
- Upstream `ai-skills` references *(not bundled in portable MCP copies)*: `references/ai-studio-delta.md` and `references/fde-patterns.md`.
