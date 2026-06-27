# SPEC — Next phases (2026-06-27)

Build spec for the next implementation pass. Author: handoff (low-context session). **Nothing here is
implemented yet.** Priority order is as written: **P1 = NBA in the matchups tab**, **P2 = Stats-page leagues**,
then P3 remaining milestone UI, then P4 UFC rankings.

Backend is now split (see `AGENTS.md §0`): add endpoints to the matching `backend/routers/*.py`, not to
`sports_service.py`. Shared helpers/DB live in `backend/_core.py`. Dev backend :8095 with
`LP_DB_PATH=data/picks.dev.db`; frontend :3095 proxies to it. **Verify every endpoint with real data, not a
200** (per AGENTS guiding principle + `feedback_verify_deliverable_before_peripheral`).

Ground-truth data already available:
- `player_game_logs` — per-game logs, **all 4 leagues incl. NBA via ESPN box scores** (the spine NBA matchups
  needs; no Bovada dependency).
- `player_stats` — season aggregates (NBA/NFL/NHL advanced metrics refreshed via `derive_player_stats.py`).
- `team_game_stats` + `/api/{league}/strength` + `/api/{league}/team-stats` — team-level data.
- Existing endpoints: `/api/player/{id}/matchups`, `/api/players/search`, `/api/player/{id}/stats`,
  `/api/{league}/strength`, `/api/{league}/standings`, `/api/{league}/team-stats`.

---

## P1 — NBA in the Matchups tab (props page)

### Current state (verify before building)
- The Matchups tab is on the props page (`pages/props.tsx`) and renders player-vs-opponent splits from
  `GET /api/player/{id}/matchups` (router: `players.py`, helper logic resolves logs from `player_game_logs`).
- It was built MLB-first (Bovada-driven slate). NBA players have per-game logs in `player_game_logs` (ESPN),
  but the matchups view does not surface NBA — either the slate/player list feeding the tab is MLB-only, the
  market→stat map has no NBA markets, or the splits query filters by league and NBA returns empty.

### Target
Matchups tab works for NBA exactly like MLB: pick an NBA player → see their per-game performance split by
opponent (and home/away), with the same chart/columns the MLB view uses.

### Backend work
1. **`GET /api/player/{id}/matchups` must return NBA splits.** Confirm the query reads `player_game_logs`
   keyed by `players.id` and is league-agnostic. NBA stat keys live in the log `stats` JSON (pts/reb/ast/etc.).
   Add NBA market/stat mappings wherever MLB ones exist (the `_MARKET_STAT_KEY` map in `_core.py` and any
   per-league stat extraction the matchups path uses).
2. **Player feed for the tab.** Whatever populates the Matchups player picker must include NBA players that
   have logs (search via `/api/players/search` already returns NBA; ensure the tab isn't filtered to MLB or to
   players that have an open Bovada prop).
3. **Opponent resolution.** NBA logs need `opponent` + `home_away` populated (MLB logs got this in the Jun-27
   ingest fix). Verify NBA ingest (`ingest_nba_logs.py`) writes opponent/home_away; backfill if missing.

### Backend acceptance criteria
- [ ] `curl :8095/api/player/{nba_id}/matchups` returns ≥1 opponent split with real numbers for a known NBA
      player (e.g. a current-season high-minutes guard), not `[]` and not a 500.
- [ ] Response shape is identical to the MLB matchups response (same keys) so the frontend needs no per-league
      branching.
- [ ] Splits are grouped by opponent and include game count + the stat averages the MLB view shows; home/away
      split present.
- [ ] No Bovada/prop dependency in the NBA path (NBA has no Bovada props — it must work off logs alone).

### Frontend acceptance criteria
- [ ] On `pages/props.tsx` Matchups tab, an NBA player can be selected and the splits render with the same
      component/columns as MLB (no empty state for a player who has logs).
- [ ] League is visible/selectable so the user knows they're looking at NBA; switching player league works.
- [ ] Mobile: table/chart does not overflow (reuse the PropChart mobile fix from P3 if shared).
- [ ] Verified on the :3095 tunnel with a real NBA player showing real opponent splits (screenshot-level proof).

---

## P2 — Stats page: leagues → player stats + team stats

### Current state (verify)
- `pages/stats.tsx` exists (~8.4 KB). Today it shows a limited stats surface (per earlier milestones it was the
  "Stats" tab; the entity-UX plan renames it to "Leagues" in Phase 4).

### Target
Stats page becomes a **league browser**: a league selector (NBA / NFL / NHL / MLB, + others that have data) that
displays, for the chosen league, **(a) player stats** (leaderboard / sortable table from `player_stats`) and
**(b) team stats** (standings + team aggregates from `strength` / `team-stats`). Two sub-views (Players | Teams)
under each league.

### Backend work
1. **Player leaderboard endpoint** — `GET /api/{league}/leaders?stat=<key>&limit=N` (add to `players.py` or a
   new `stats` router). Reads `player_stats` for the league/current season, sorts by the requested stat,
   returns name/team/stat columns. Provide a sensible default stat per league (pts for NBA, etc.) and the full
   per-game/per-season column set the table shows.
2. **Team stats endpoint** — reuse `/api/{league}/strength` (win%/diff/streak/last10) and
   `/api/{league}/team-stats` for team aggregates. If a combined per-league team table is cleaner, add
   `GET /api/{league}/teams` returning the merged standings + key team stats.
3. **League list** — expose which leagues actually have player+team data (so the selector only shows populated
   leagues). Can derive from `player_stats` distinct leagues + `espn.LEAGUES`.

### Backend acceptance criteria
- [ ] `curl :8095/api/{league}/leaders` returns a sorted, non-empty leaderboard with real values for each of
      NBA, NFL, NHL, MLB (the four with logs/stats).
- [ ] Team endpoint returns every team in the league with standings + the displayed stat columns, no nulls
      where data exists.
- [ ] Empty/off-season leagues return a clean empty list (not a 500) and are excludable from the selector.
- [ ] Stat keys returned match what the frontend table renders (no "stat exists in UI but backend never sends it").

### Frontend acceptance criteria
- [ ] Stats page has a league selector; choosing a league shows **Players** and **Teams** sub-views.
- [ ] Players view = sortable leaderboard table (click a player → their `/player/[id]` page, reusing existing
      player page).
- [ ] Teams view = standings + team stats table for that league.
- [ ] Follows `AGENTS.md` Layout rules (content-only JSX, no shell re-creation); two-tone theme consistent with
      other pages.
- [ ] Verified on tunnel: all four leagues render real player + team data; mobile does not overflow.

---

## P3 — Remaining milestone UI (smaller, do alongside)

From `docs/CONTEXT-2026-06-27.md` "Open / next" + `docs/PLAN-entity-ux-restructure.md`:
- [ ] **Remove WC dead click** — 1-line in `components/Scores/GameCard.tsx` `hasDetail` (WC has no real detail
      page → dead click). Gate NHL too if still flaky off-season.
- [ ] **NBA "edge" on the game page** — NBA has projections but no Bovada props; show projected lines in the
      edge slot (the prop-module position) instead of leaving it empty for NBA games.
- [ ] **PropChart mobile-responsive** — `components/Props/PropChart.tsx` SVG overflows on narrow screens; scale
      to container width (viewBox / responsive width) instead of x-scroll.
- [ ] **Phase 4** — rename "Stats" tab to "Leagues" (this is the P2 page).
- [ ] **Phase 5** — remove the Analytics tab (EV all-zero / CLV empty per M7 audit; not user-ready).
- [ ] **Per-page projection-vs-line badge** — small badge showing projection vs the posted line where both exist.
- [ ] **Props page: do NOT refactor** (owner said leave it).

---

## P4 — UFC rankings (weight class + pound-for-pound)

### Target
A UFC standings/rankings view broken down **by weight class**, plus a **pound-for-pound (P4P)** board. Content
is effectively a copy of ufc.com/rankings (the official rankings table).

### Backend work
1. **Data source.** ufc.com publishes rankings as 13 boxes (P4P men, P4P women, + each weight class) with a
   champion + 15 ranked contenders. Options, in order of preference:
   - Scrape `https://www.ufc.com/rankings` (server-rendered HTML; parse each `view-grouping` block → division
     name, champion, ranked list). Build `backend/ufc_rankings.py` (stdlib `urllib` + a light HTML parse, same
     dependency-free style as `espn_client.py`). Cache to a table `ufc_rankings(division, rank, fighter,
     fighter_id, change, captured_at)` so the request path never hits ufc.com live.
   - If scraping is brittle, ESPN has `/api/.../ufc` — check whether it exposes rankings; otherwise a small
     hand-maintained JSON seed is acceptable for v1 (rankings change weekly, not daily).
2. **Endpoint** — `GET /api/ufc/rankings` → `{ pound_for_pound: [...], divisions: [{ division, champion,
   ranked: [{rank, fighter, change}] }] }`. Add to `games.py` (UFC already lives there via `/api/ufc/...`) or a
   small `ufc` router.
3. **Ingest cadence** — a weekly refresh job (cron/manual) repopulating the table; never scrape on the request path.

### Backend acceptance criteria
- [ ] `curl :8095/api/ufc/rankings` returns P4P (men + women) and every weight-class division, each with a
      champion and up to 15 ranked fighters, matching ufc.com at capture time.
- [ ] Request path reads the cached table only (no live ufc.com call per request).
- [ ] Fighter names resolve cleanly; division labels match UFC's (Flyweight … Heavyweight, Women's divisions, P4P).

### Frontend acceptance criteria
- [ ] A UFC rankings view (likely under the Stats/Leagues page UFC tab, or the UFC standings slot) shows each
      weight class as its own ranked list with the champion highlighted, plus a P4P board.
- [ ] Matches ufc.com ordering; "rank change" arrows optional for v1.
- [ ] Two-tone theme + Layout rules; mobile stacks cleanly.
- [ ] Verified on tunnel against the live ufc.com rankings page (spot-check 2-3 divisions).

---

## Cross-cutting

- **Tests stay deferred** until these phases land (retro decision). When they land, cover projections / EV-CLV /
  identity-resolution first.
- **All work on `analytics-backbone`**, dev DB only, prod held until owner says deploy.
- Resolve player identity by ID, never by name (`AGENTS.md` spine rule).
