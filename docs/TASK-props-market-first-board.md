# TASK (Codex): rebuild the props Slate as a market-first board (props.cash / Underdog / PrizePicks)

Repo **/root/legendarypicks**, branch `dev`. Decision made 2026-07-17 (see the comparison artifact
`public/props-layout-comparison.html`): go the **market-first + chart** route, NOT the Bovada
game→category builder. The current Slate (`SlateTab` in `pages/props.tsx`: game → player → chips)
reads as a schedule, not a book. Replace it with a research board where the **prop line + its hit-rate
chart is the atom**.

## The board
Pick a **market (stat)** → a scannable list of **every player's line for that stat across today's
slate**, each row carrying the evidence:
- player · team · game (e.g. `Skubal · DET vs TEX`)
- the **line** + **O/U with odds**
- our **projection + edge** (from the Model tab data) when available
- an inline **`PropChart`** — the last-N bars vs the line with the L5/L10/L20 hit-rate. This component
  already exists: `components/Props/PropChart.tsx` (data from `GET /api/props/history`). Use it; do not
  rebuild it.
- **sortable** by hit-rate / edge / line.

Market picker = pills of the markets present in the current slate (derive from the data, or reuse
`LEAGUE_MARKETS` / `marketsForLeague`). Respects the existing League pills + the nearest-date default.

## Reuse (don't reinvent)
- `PropChart` + `PropHistory` (built), `GET /api/props/history`, `GET /api/props?league=&market=&date=`
  (already filterable), the Model/projection data, the existing dark/emerald visual language and
  `tabular-nums`. The Lines tab already renders player prop rows + PropChart on expand — this board is
  essentially that, but **market-led and full-slate** instead of search-led.

## Placement
Make this the **primary Slate view**. Keep the game→category grouping only as a secondary "by game"
toggle if cheap; the market board is the default. Don't touch the other tabs (Performance/Matchups/Model).

## Constraints
- Scope: `pages/props.tsx` (+ a small new component under `components/Props/` if it helps). Additive to
  the backend only if truly needed (the endpoints above should suffice).
- Match the app's visual language (dark zinc + emerald, the app font — NOT monospace; tabular-nums for
  numbers). Clean and restrained.
- **Verify the real render on the tunnel** (`http://127.0.0.1:3096/props`) with live data — MLB
  strikeouts and WC goalscorer both have props today; confirm rows + the PropChart draw, no console
  errors, no horizontal overflow at 390px.
- Do NOT commit or push (Claude owns git). Report a diff summary + the verify output.
