# Team Vocabulary Thread — Job Results

Worktree: /root/lp-team-vocab | Branch: fix/team-vocabulary
DB: /root/picks.hermes.db | Backend: :8098

---

## Job 1 — team_codes.py + positions + tests
**Commit:** `fe9d6a1`
**Files:** backend/team_codes.py (214 lines), backend/test_team_codes.py (307 lines), docs/espn-position-codes-2026-07-27.json
**Pytest:** 50 passed, 0 failed
**Position URL:** `sports.core.api.espn.com/v2/sports/football/leagues/nfl/positions?limit=100` — 200, 74 positions, 67 unique abbreviations
**Aliases kept:** 9/9 (all targets in canonical set)
**Aliases dropped:** none

---

## Job 2 — Migration
**Commit:** (data operation, no code change)
**Dry run:** 14,937 rows across 14 table/column targets
**Apply:** 14,937 rows rewritten, `verify` confirmed every NFL team code is one of the 32
**Gate — board diff:** IDENTICAL
**Baseline:** 522 rows, 32 teams, 511 with team_weeks
**After:** 522 rows, 32 teams, 511 with team_weeks

---

## Job 3 — Delete team_weeks derivation
**Commit:** `2c9cb52` (+14/-26, nfl_offseason.py only)
**Changes:**
- Deleted `_TEAM_ALIASES` dict
- Deleted `_normalize_team()` function
- Replaced call sites with `normalize("nfl", ...)` / `normalize_optional("nfl", ...)`
- Replaced team_weeks derivation: `player_game_logs` → `nfl_schedule` (UNION ALL home/away)
- Added `from team_codes import normalize, normalize_optional`
**Gate — board diff:** IDENTICAL

---

## Job 4 — Normalize at ingest boundaries
**Commit:** `e40be76` (+184/-10, 8 files)
**Files changed:**
- `ingest_nfl_schedule.py` — switched off private ESPN_ALIASES, now calls `normalize("nfl", ...)`
- `ingest_nfl_weekly_stats.py` — normalize team/opponent at write boundary
- `ingest_nfl_pbp_logs.py` — normalize posteam/defteam/home_team/away_team
- `ingest_nfl_depth_charts.py` — normalize team
- `ingest_mlb_logs.py` — normalize team/opponent with `normalize("mlb", ...)`
- `ingest_mlb_pitcher_logs.py` — normalize team/opponent with `normalize("mlb", ...)`
- `ingest_nhl_logs.py` — normalize team/opponent with `normalize("nhl", ...)`
- `test_ingest_team_vocabulary.py` — 20 tests, data-integrity guard
**Pytest:** 65 passed, 5 skipped (MLB/NHL not yet migrated)
**NFL data-integrity:** all 14 team-bearing columns clean
