# SPEC — World Cup player props on the Props page (2026-07-15)

Status: **spec / not started.** Author hand-off from the team-stats session.

## Goal
Add **World Cup (soccer) player props** to `/props`, alongside the existing MLB props — so the
Props page isn't MLB-only during the World Cup window.

## Current architecture (what exists today)
- **Source:** `backend/bovada_scraper.py` scrapes Bovada player-prop markets.
- **Storage:**
  - `prop_games(id, league, date, home, away, espn_event_id, final_home, final_away)` — currently
    only `league='mlb'` rows exist.
  - `props(id, game_id, player_id, market, line, side, source, captured_at, odds, odds_captured_at)`.
  - `prop_results(prop_id, …)` — settlement outcomes.
- **Linkage:** `backend/link_prop_games.py` matches scraped games → ESPN events and props → `player_id`.
- **Settlement:** `backend/settle_props.py` / `settlement.py` grade props against player game logs.
- **Endpoints:** `backend/routers/props.py` — `/api/props`, `/api/props/player/{id}/history`,
  `/api/props/history`, `/api/props/stats`.
- **Frontend:** `pages/props.tsx` — consumes `/api/props`; markets/history are implicitly
  baseball-shaped today.
- **WC data we already have:** ESPN WC endpoints exist (`espn.wc_*`, `/api/wc/knockout`,
  `/api/wc/standings`) for schedule/scores/bracket. **We do NOT currently ingest WC player rosters
  or per-player soccer box-score stats.**

## Gap analysis (what WC props need that doesn't exist)
1. **Odds source for WC markets.** Bovada does carry World Cup player props (goals, shots, shots on
   target, assists, cards). Need to extend `bovada_scraper.py` to hit the soccer/World Cup event
   paths and normalize soccer markets. (Alternative: a dedicated odds API — decision below.)
2. **`prop_games` for WC.** Insert `league='wc'` rows linked to ESPN WC `espn_event_id`
   (reuse the WC schedule we already fetch). Group-vs-knockout gating already handled by
   `espn.wc_is_knockout()`.
3. **Player identity.** WC soccer players are **not** in our players table / game-log store today.
   Either (a) build a WC roster ingest from ESPN soccer, or (b) match props to players by
   name+team without a full roster. Linkage (`link_prop_games.py`) must learn soccer.
4. **Soccer markets + settlement.** New market vocabulary (goals, shots_on_target, assists,
   shots, cards, passes). Settlement needs **per-player soccer box-score stats** — an ingest we
   don't have. Without it, WC props can be **display-only lines** (no auto-grading) initially.
5. **Frontend.** `pages/props.tsx` needs a league filter/section for WC and soccer-aware
   market labels + history rendering (the per-game history view assumes counting stats).

## Proposed approach (phased, lowest-risk first)
- **Phase 1 — display-only WC lines (ship first):**
  Extend `bovada_scraper.py` to pull WC player props → insert `prop_games(league='wc')` + `props`
  rows (source='bovada'), linked to ESPN WC events. Match players by name (no roster ingest yet;
  `player_id` nullable or a lightweight soccer-player table). Add a **WC filter** to `pages/props.tsx`
  and soccer market labels. **No settlement** yet — lines + odds only. This gets WC props visible
  fast and reuses the whole existing pipeline.
- **Phase 2 — settlement:** ingest ESPN per-player soccer box scores (goals/shots/assists/cards)
  into a soccer game-log store; wire `settle_props.py` to grade WC markets; backfill `prop_results`.
- **Phase 3 — analytics/model:** once settled history exists, extend `analytics/` (EV/CLV) and any
  projection model to soccer markets.

## Open decisions (need the user)
1. **Odds source:** extend Bovada scraper (reuses everything, but Bovada soccer market shapes differ
   and scraping is brittle) **vs** a paid odds API (cleaner, costs money). *Recommend: Bovada Phase 1.*
2. **Settlement now or later:** ship **display-only** (Phase 1) first, or block on building the
   soccer box-score ingest for grading? *Recommend: display-only first.*
3. **Player identity:** name-match (fast, fuzzy) vs a real ESPN soccer roster ingest (robust, more
   work). *Recommend: name-match Phase 1, roster ingest in Phase 2 with settlement.*
4. **Market scope for Phase 1:** which markets to surface first — recommend **goals, shots on
   target, assists** (highest liquidity/interest); defer cards/passes.
5. **Timing:** is the World Cup currently in a window with Bovada props posted? (The trading watcher
   already tracks WC series — confirm props are live before investing.)

## Rough effort
- Phase 1: ~1–2 focused sessions (scraper extension + prop_games/props wiring + frontend filter/labels).
- Phase 2 (settlement): larger — new soccer box-score ingest + grading + backfill.

## Scope guardrails for whoever implements
- Reuse the existing props schema/pipeline; do **not** fork a parallel props system.
- Keep MLB props untouched (regression-check `/api/props` still returns MLB rows).
- `league='wc'` everywhere so it filters cleanly and can't leak into MLB queries.
