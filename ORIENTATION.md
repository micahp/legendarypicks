# ORIENTATION — read this FIRST, then stop exploring

Onboarding order for any fresh context: **(1) this file → (2) AGENTS.md (rules) → (3) your task
handoff in `docs/`.** That's enough to start. Do NOT grep the whole repo to "get the lay" — it's mapped
here. Keep this file current when structure changes.

## What this is
**Legendary Picks** — a sports prediction & **prop-outcome data** product (live at legendarypicks.xyz).
Stack: **Next.js** UI (:3100) ↔ **FastAPI** backend (:8100) ↔ **SQLite** (`backend/data/picks.db`,
bind-mounted). Deployed via docker-compose behind nginx on this server (Contabo, St. Louis). Ops rules
+ deploy gotchas: AGENTS.md §6–9.

## Data plane (the architecture)
`sources → ingest scripts → SQLite (canonical) → FastAPI → Next.js UI`
- **Sources:** ESPN (games/rosters/boxscores/strength, all leagues), Bovada (prop lines), Statcast/
  nflverse/hoopR/nhle (advanced player stats).
- **Ingest is the only writer.** The request path NEVER calls a live source — it reads the DB. Heavy
  libs (pybaseball, nfl_data_py) live in `ingest_*.py` only.

## Backend (`backend/`)
- `sports_service.py` — the FastAPI app + ALL endpoints (`/api/{league}/games|strength|boxscore`,
  `/api/props`, `/props/slate`, `/props/player/{id}/performance`, `/player/{id}/stats`,
  `/props/stats`, `/predictions`). Stat handlers: `_get_{mlb,nba,nfl,nhl}_stats` (read player_stats).
- `espn_client.py` — ESPN data: `games()`, `roster()`, `boxscore()`, `team_strength()`.
- `bovada_scraper.py` — Bovada prop lines.
- `ingest_props.py / ingest_statcast.py / ingest_hoopR.py / ingest_nfl.py / ingest_nhl.py` — writers → DB.
- `data/picks.db` — SQLite (bind-mounted; never baked into the image).

## DB tables
- `players(id, name, team, league, espn_id …)` — **canonical player spine** (being extended with
  `mlbam_id/nfl_gsis_id/nhl_id/nba_id` — see SPEC-player-identity-spine.md). Surrogate `id` is the key.
- `props(id, game_id→prop_games.id, player_id→players.id, market, line, side, source, captured_at)`.
- `prop_games(id, league, date, home, away, espn_event_id, final_home, final_away)` — games have a real
  cross-source id (`espn_event_id`).
- `player_stats(player_id→players.id, player_name, league, stat_type, <league stat cols>)` — SEASON stats.
- `prop_results(prop_id, actual_value, hit, settled_at)` — **settlement output (currently empty).**
- others: `predictions, team_game_stats, roster_snap, strength_snap, scoring_plays, game_context`,
  and (new) `unresolved_players, name_alias`.

## Frontend
- `pages/`: `index.tsx` (landing), `scores.tsx` (scoreboard — `‹ date ›` nav, state-aware cards),
  `props.tsx` (the 5-tab prop product: Lines/Slate/Performance/Matchups/Model), `predict.tsx`,
  `game/[league]/[gameId].tsx` (game detail).
- `components/`: `Layout`, `Navbar`, `Scores/{GameCard,States}`.
- `services/sports.ts` — API client (base = relative `/api`; NEVER hardcode a host — AGENTS.md §6/§8).
- `next.config.js` — eslint/type unblock for builds + `/api`→backend rewrite (`API_PROXY_TARGET`).

## Run / deploy
- `docker compose up -d --build` (frontend 3100, backend 8100, loopback only; nginx fronts it).
- Build MUST compile before commit; verify pages RENDER DATA, not just 200 (AGENTS.md).

## Current state & what's a known hole (pointer — check latest docs/HANDOFF-* for specifics)
- LIVE; DB-backed stats for all leagues. **In progress:** player-identity spine (SPEC-player-identity-spine.md).
- **Known holes:** settlement pipeline not built (`prop_results=0`) → SPEC-settlement-pipeline.md;
  roster coverage <95% (identity spine fixes); ingestion not scheduled (still manual).
