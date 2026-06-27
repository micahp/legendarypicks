# TASK — Finish the PropChart (v1 draft → done)

The PropChart (`components/Props/PropChart.tsx`) is a working first draft. Take it to "done".
All changes are FRONTEND (PropChart.tsx + pages/props.tsx). The `/api/props/history` endpoint
already returns everything you need — do the filtering client-side from `data.games`.

## 1. Filters — home/away + vs-opponent
The history response's `games[]` now include `home` (bool) and `opponent` (abbrev — populated
since the opponent backfill). Add small toggles that re-slice the displayed games + recompute the
hit-rate label client-side:
- **Venue:** All / Home / Away (filter `g.home`)
- **vs Opponent:** a toggle to show only games where `g.opponent === <the prop's game opponent>`
  if known, else a dropdown of opponents present in the data. (Keep it simple — All / vs-opp.)
These sit alongside the existing L5/L10/L20/Season window toggle.

## 2. Non-chartable markets — clear empty state (not "no data")
Pitcher props now chart, but composite markets (`total_hits,_runs_and_rbis`) and unmapped ones
return `{stat_key: null, games: []}` or an `error`. Right now that looks broken. Instead:
- If the history response has no `stat_key` / empty games, show a tidy inline message like
  **"Chart not available for this market yet"** (not a bare "no data"), OR don't render the
  expand affordance for those rows. Pick whichever is cleaner in the Lines list.

## 3. Projection marker on the chart
The response has `projection` (a number). Draw it on the chart as a distinct marker — e.g. a
dashed horizontal line or a labeled dot — visually separate from the solid **prop line**, so you
can see model-vs-line at a glance. Label it "Proj 2.1".

## Definition of done
- A batter prop (e.g. Freddie Freeman total_bases) shows: venue + vs-opp filters that change the
  bars/hit-rate, the prop line AND a distinct projection marker, and the L5/L10/L20/Season toggle.
- A composite/unmapped market shows the clean "not available" state, not a broken-looking empty.
- Verify the actual render on the tunnel (Props → Lines → expand), not just that it builds.

## Constraints
- Frontend only. Branch off `analytics-backbone` (e.g. `feat/propchart-finish`). Dev only
  (frontend :3095, backend :8095). No AI/Claude attribution. Match the app's visual language.
