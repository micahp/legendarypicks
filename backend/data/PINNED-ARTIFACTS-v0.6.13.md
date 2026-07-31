# v0.6.13 re-cut — pinned source artifacts (Phase 0)

Recorded 2026-07-31 by the Reasonix goal loop (worktree /root/lp-v0613-recut, branch recut/v0.6.13, base 8793915).

## 1. ESPN 2026 player snapshot (ranks + projections)
- File: `backend/data/espn_2026_snapshot_page1.json`
- Source: `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/players?scoringPeriodId=0&view=kona_player_info`
- Request: `x-fantasy-filter` = `{"players":{"limit":3000,"sortDraftRanks":{"sortPriority":1,"sortAsc":true,"value":"STANDARD"}}}`
  (MUST be sent via urllib/python — a curl `-H` invocation returned ranks-less payloads in testing)
- Contents: 11,515 players; `draftRanksByRankType.PPR.rank` present; 2026 projection entry at
  `seasonId=2026, scoringPeriodId=0, statSourceId=1, statSplitTypeId=0` (e.g. CeeDee Lamb: PPR rank 9, appliedTotal 294.52, 40 stat keys)
- sha256: `bbae53447ba51e79b038683085dc2d8b998156b8e8e7102f0fb9b5e32f51f61e`

## 2. nflverse 2026 schedule
- File: `backend/data/nflverse_games_2026.csv`
- Source: `https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv`
- Contents: 2026 REG games = **272**; 2026 total rows = 272 (season is column 2; game_type column 3)
- sha256: `80468ea021f478582f19a9d906f16ddcec56a1b2f77c09b21d616bae1a0c0eab`

## 3. Team Stats source artifacts (NBA/NFL/NHL)
- Source of truth is the **live ESPN site API** — both `backfill_team_stats.py` and `backfill_team_parity.py` fetch from `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/...` (scoreboard + boxscore + teams endpoints), NOT local CSVs. There is no local artifact to pin.
- Smoke test 2026-07-31: `basketball/nba/teams` returns 30 teams.
- Endpoint patterns to pin during Phase 4 (approved windows only, responses cached as JSON):
  - `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD` (+ boxscore per game)
  - `https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=YYYYMMDD`
  - `https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates=YYYYMMDD`
- Approved windows (from goal-loop plan): NBA 2025-26 reg season; NFL 2025 reg season; NHL 2025-26 reg season. Runs ONLY against the disposable clone.

## 4. Disposable production clone
- File: `backend/data/rehearsal-v0.6.13.db` (copy of `/root/legendarypicks/backend/data/picks.db`, the production DB)
- **NOTE:** `/tmp` is ephemeral on this box (files vanish between commands), so the clone lives inside the worktree, NOT `/tmp`. All Phase 1–6 DB work targets this file via `LP_DB_PATH=/root/lp-v0613-recut/backend/data/rehearsal-v0.6.13.db`.
- Verified 2026-07-31: `PRAGMA quick_check` = ok; 35 tables; player_game_logs=142,749; players=29,859; nfl_adp=9,646.
- The only production-DB touch is this read-only `cp`. The clone is git-ignored/untracked and never pushed.

## Notes for later phases
- The stats entry for projections uses `stats` key (not `playerStats`); `statSplitTypeId=0` = projection, `=1` = weekly actuals.
- Plan doc: `/root/CODEX-V0.6.13-RECUT-PLAN-2026-07-29.md`; goal-loop plan: `docs/PLAN-v0.6.13-hermes-goal-loop.md`.
