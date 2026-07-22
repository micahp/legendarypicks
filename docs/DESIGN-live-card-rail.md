# Live Card Design — "Broadcast Rail"

## Problem

Two components on the scoreboard share a generator-GPT aesthetic that reads as cheap:

1. **LiveNow** (`pages/scores.tsx`) — red-bordered box (`border-red-500/20 bg-red-500/[0.04]`), pulsing dot, nested card at 70% opacity
2. **LiveDiscounts** (`components/LiveDiscounts.tsx`) — amber-bordered box (`border-amber-500/20 bg-amber-500/[0.04]`), DiscountCards at `bg-zinc-900/70`

The pattern: a colored translucent wrapper around a card that's itself semi-transparent. Two nested opacity hacks. Feels like a form validation error, not a sports dashboard.

The red is also off-brand — the site's language is zinc + emerald (ESPN dark).

## Principle

**Solid surfaces, one distinctive detail.** No opacity hacks, no colored wrappers. Differentiate through edge treatment, typography, and composition — not by wrapping a card in a colored ghost of itself.

## Variant A — Broadcast Rail

### LiveNow

```
┌─ 3px emerald breathing border-left (the "live" indicator)
│  Solid zinc-900 surface
│  Featured game: team abbrevs + display-scale scores (text-5xl)
│  Inline live chips: always visible, no toggle
│  Esports link: quiet right-aligned text
```

**What changes:**
- Kill all `red-*` classes
- No "LIVE NOW" label — the breathing left edge carries the signal
- `bg-zinc-900` solid (was `bg-red-500/[0.04]`)
- `border-red-500/20` → removed entirely (breathing bar replaces it)
- Featured game card: `bg-zinc-900` solid (was `bg-zinc-900/70`)
- Other live games: compact chips, always visible (kill the toggle)
- Esports: text link, not an emoji-button
- ListenLive stays as-is (already solid zinc-900/50, fine)

### LiveDiscounts

Same philosophy, adapted to a data widget (not a live broadcast):

```
┌─ 3px amber static border-left (functional tag, not breathing)
│  Solid zinc-900 surface
│  "⚡ Cheap quality, live" header — no background wrapper
│  DiscountCards: solid bg, keep internal colored badges
```

**What changes:**
- Kill `border-amber-500/20 bg-amber-500/[0.04]` wrapper
- Replace with solid zinc-900 + 3px static amber left edge
- DiscountCards: `bg-zinc-900` solid (was `bg-zinc-900/70`)
- Keep internal badges (emerald/amber/violet/rose) — they're functional classifiers, not decoration
- Header stays, just loses the colored background

## Typography

- Scores: JetBrains Mono, tabular-nums, tracking-tight
- Team names: Inter semibold
- Badges/meta: 10px uppercase, wide tracking

## CSS

```css
@keyframes breathe {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
.live-edge {
  border-left: 3px solid rgb(16 185 129 / 0.6);
  animation: breathe 2s ease-in-out infinite;
}
@media (prefers-reduced-motion: reduce) {
  .live-edge { animation: none; border-left-color: rgb(16 185 129 / 0.8); }
}
```

## Before / After

| | Before | After |
|---|---|---|
| LiveNow container | `border-red-500/20 bg-red-500/[0.04]` | `bg-zinc-900` + breathing emerald left edge |
| Featured game card | `bg-zinc-900/70` | `bg-zinc-900` solid (merged into container) |
| Other games | hidden behind toggle | compact inline chips, always visible |
| Live indicator | pulsing dot + "LIVE NOW" label | breathing edge bar (no label) |
| Esports | emoji-button | quiet text link |
| LiveDiscounts wrapper | `border-amber-500/20 bg-amber-500/[0.04]` | `bg-zinc-900` + static amber left edge |
| DiscountCards | `bg-zinc-900/70` | `bg-zinc-900` solid |

## Sketch

Mockup at `/root/legendarypicks/sketches/comparison.html` (center column = Variant A).
