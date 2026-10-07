# Spec: a light/dark toggle for the site

Written 2026-10-07 for Micah. Status: not started.

## What exists now

The site is dark only. There is no light theme and nothing to switch to.

- The dark look is written straight into the pages as fixed Tailwind grays: `bg-zinc-900`,
  `bg-zinc-800`, `text-zinc-500`, `border-zinc-800` and similar. About 3,300 uses across 109 files in
  `components/` and `pages/`.
- The only dark-mode rule that follows the visitor's system setting is a leftover from the Next.js
  starter template in `styles/Home.module.css` (`@media (prefers-color-scheme: dark)`), and it only
  touches a couple of starter classes.
- A small set of named colors already exists: `--lp-bg #0f0f11`, `--lp-panel #18181b`,
  `--lp-border #27272a`, `--lp-text #e5e5e5`, `--lp-muted #9ca3af`, `--lp-brand #22c55e`.

## Why a toggle needs more than a button

A button can only change colors that are written as a choice. Today "dark" is not a choice, it is
what every component says. So the work is to turn the fixed grays into named roles, give each role a
dark value and a light value, and only then add the button.

Think of it as paint labels. Today each wall is painted a specific gray. To repaint the house with
one switch, every wall is first relabeled "wall", "trim", "text", and the label says which gray to use.
Relabeling changes nothing you can see. The switch then changes what each label means.

## Step 1: define the roles (small)

Create one set of CSS variables, defined twice: once for dark (the current values, so nothing changes)
and once for light.

| Role | Dark (today) | Light (starting point, from the games-list mockup) |
|---|---|---|
| background | `#0f0f11` | `#ffffff` |
| panel (cards, sheets) | `#18181b` | `#f2f2f4` |
| raised panel / hover | `#27272a` | `#e8e8ec` |
| border | `#27272a` | `#e4e4e7` |
| text | `#e5e5e5` | `#111214` |
| muted text | `#9ca3af` | `#707177` |
| faint text | `#52525b` | `#b0b0b5` |
| brand | `#22c55e` | `#16a34a` (darker, so it reads on white) |

Dark values apply by default and when the theme attribute is `dark`. Light values apply when the
attribute is `light`. Tailwind is told to read the roles (extend `theme.colors` in
`tailwind.config`), so a class like `bg-panel` means "the panel color of the current theme".

## Step 2: relabel the components (large, mechanical)

Replace each fixed gray with its role. The mapping is one to one:

| Now | Becomes |
|---|---|
| `bg-zinc-900` | `bg-panel` |
| `bg-zinc-800` | `bg-raised` |
| `border-zinc-800`, `border-zinc-700` | `border-line` |
| `text-zinc-100`, `-200`, `-300` | `text-ink` |
| `text-zinc-400`, `-500` | `text-muted` |
| `text-zinc-600` | `text-faint` |

Rules for this step:
- In dark mode the site must look identical. Compare before and after on the main pages.
- Do it with a script, then read the diff. Do not do it by hand.
- Anything that is not a plain gray (team colors, charts, the green accent, gradients, images) is left
  alone, then reviewed page by page for contrast in light mode.
- Do it in slices (one folder per commit) so a bad slice can be reverted alone.

## Step 3: the toggle (small)

- A sun/moon button in the header. It sets `data-theme="light"` or `"dark"` on the page root and saves
  the choice in the browser (wrapped so a blocked storage never breaks the page).
- First visit follows the visitor's system setting; after that their choice wins.
- A few lines in `_document` run before the page paints, so a light-theme visitor never sees a dark
  flash.

## Check before shipping

- Screenshot every main page in both themes, at phone width and desktop width.
- Contrast: body text and muted text readable on both backgrounds.
- Images and logos with baked-in dark backgrounds (the starter `invert` filter on the logo, any
  white-on-transparent marks) look right in light mode.
- Production gets a normal release; the dev site gets it first.

## Open decisions for Micah

1. Ship light mode across the whole site, or start with the games list only?
2. Keep the green `#22c55e` brand in light mode, or use the darker `#16a34a` for readability?
3. Default for first-time visitors: follow their system, or always start dark?

## Who does it

Step 1 and 3 are an hour of work. Step 2 is the long one; it suits Codex or pi with a screenshot
check per page.
