# TASK — Refresh NBA/NFL/NHL player_stats from per-game logs (current season)

## Why
The Performance tab + player-page advanced metrics read `player_stats` (season aggregates),
which are **stale + partial**: NBA = 525 players from a 2023 hoopR pull, NFL = 612 from 2024.
So most players show nothing. But we ALREADY have **current** per-game data in
`player_game_logs` (NBA full 2025-26, NFL 2024+2025, NHL 2025-26). Derive current-season
`player_stats` from those logs — no stale external source needed.

## Approach
A script (`backend/derive_player_stats.py`) that, per league (nba/nfl/nhl):
1. Reads `player_game_logs` for the latest season, grouped by `player_id`.
2. Aggregates the per-game JSON `stats` into the existing `player_stats` columns —
   **averages** for rate stats (pts, reb, pass_yds_g…), **sums** for counting stats
   (totals, tds), `games` = count, `season` = the season.
3. **Upserts into `player_stats` keyed on the SAME `player_id`** (from the log row — already
   resolved). NEVER create new players rows / NEVER match by name. (AGENTS.md §7 / IDENTITY-SPINE-STATE.)

## Column mapping (log key → player_stats column)
Check `player_stats` schema (`PRAGMA table_info(player_stats)`) and the existing ingests
(`ingest_nfl.py`, `ingest_hoopR.py`, `ingest_nhl.py`) for the exact columns. Roughly:
- **NBA:** PTS→pts, REB→reb, AST→ast, STL→stl, BLK→blk, TO→turnovers, 3PM→fg3m(sum),
  FGM/FGA→fgm/fga(sum), FTM/FTA(sum), MIN→minutes(avg), compute ts_pct, set source='derived'.
- **NFL:** passing_yards→pass_yds_g(avg), passing_tds→pass_td(sum), interceptions(sum),
  completions→cmp_g(avg), passing_epa(sum), carries→carries_g, rushing_yards→rush_yds_g,
  receptions(sum), receiving_yards→rec_yds_g, targets(sum), fantasy_points→fantasy_pts_g, etc.
- **NHL:** goals/assists/points/shots/plus_minus/pim/ppg/ppp/toi — sums/avgs as the columns expect.

## Definition of done
- An NBA player who is ONLY in the logs (e.g. a 2025-26 rookie not in the stale 2023 set) now
  returns current advanced metrics from `/api/player/{id}/stats?league=nba`.
- A 2024 NFL player likewise. Window/season reflects the current season, not 2023/2024-stale.
- No new `players` rows created; no name-based matching. Verify on the live tunnel
  (Props → Performance → search that player → metrics populate).

## Constraints
- Work in YOUR worktree `/root/lp-hermes`; branch off `origin/analytics-backbone`
  (`git fetch origin && git checkout -b feat/refresh-player-stats origin/analytics-backbone`).
- Dev only: `LP_DB_PATH=backend/data/picks.dev.db`. Do NOT touch prod. No AI/Claude attribution.
- Start your own dev server on a free port (e.g. 3096/8096) to verify — main :3095/:8095 is the orchestrator's.
