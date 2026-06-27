# TASK — `<PropChart>` component (the prop visualization)

Build the prop visualization every prop site has (props.cash / PrizePicks / Underdog) and
ours is missing: a **bar chart of a player's last N games for a stat, with the prop line drawn
across it**, so hit rate reads at a glance. Today we only show a retrospective ✅/❌ after the
game — this replaces that with a decision-useful chart.

## What it looks like
```
Jayson Tatum — Points        Line 27.5      L10: 7/10 over      Proj 29.4
   ▆        █
   ▆  ▅  █  ▆  ▅  ▆  █  ▆  █  ▆
 ──┼──┼──┼──┼──┼──┼──┼──┼──┼──┼──  ← 27.5 line
   31 24 33 28 26 22 35 29 30 27
  vs MIA  BOS  ...                  (most recent on the right)
```
- One bar per game (most recent on the right). Bar height = the stat value.
- A horizontal line at the prop `line`. Bars **at/above the line = hit (over)** → one color
  (e.g. emerald); **below = miss (under)** → muted/red. (If the prop side is `under`, invert
  the hit coloring.)
- Labels: the line value, hit-rate for the selected window (e.g. "7/10 over"), and the projection.
- Show the value under/in each bar; opponent on hover or a small label.

## Data contract — `GET /api/props/history` (I'm building this in parallel)
Build against this shape now (mock it until the endpoint lands, then swap to live):
```json
{
  "player_id": 3984,
  "player": "Jayson Tatum",
  "team": "BOS",
  "league": "nba",
  "market": "points",
  "line": 27.5,
  "side": "over",
  "projection": 29.4,
  "hit_rate": { "l5": 0.6, "l10": 0.7, "l20": 0.65, "season": 0.62 },
  "games": [
    { "date": "2026-06-20", "value": 31, "opponent": "MIA", "home": true,  "hit": true },
    { "date": "2026-06-18", "value": 24, "opponent": "PHI", "home": false, "hit": false }
    // ... most-recent-first; render left→right oldest→newest
  ]
}
```
- `hit` is already computed server-side (value vs line, respecting `side`). Don't recompute.
- `games` is most-recent-first; reverse for left→right oldest→newest display.

## Component API
```tsx
<PropChart data={PropHistory} window="l10" />   // window: 'l5'|'l10'|'l20'|'season'
```
- Add a small L5 / L10 / L20 / Season toggle that re-slices the displayed games + hit-rate label.
- Pure presentational component; fetch happens in the parent (or accept a `propId`/params and fetch).
- Graceful empty state if `games` is empty ("no game history yet").

## Where it goes
1. **Props · Lines tab** — replace the per-row ✅/❌ outcome with this chart (expandable row or a
   detail panel). This is the primary placement.
2. Reusable later on the **Player page** and **Game detail** (same component) — just build it standalone.

## Constraints
- Dev only: frontend :3095, backend :8095 (`LP_DB_PATH=data/picks.dev.db`). Do NOT touch prod or deploy.
- Branch off `analytics-backbone` (e.g. `feat/prop-chart`). No AI/Claude attribution on commits.
- Match the app's existing visual language (dark zinc theme, tabular-nums, the app's font — NOT
  monospace; see the tennis-card lesson). Keep it clean and restrained.
- Verify the actual RENDER on the tunnel (a real MLB prop with history), not just that data loads.
  Use a date with props, e.g. `/props` for an MLB game today, or a player with logs.
