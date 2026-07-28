# Team Vocabulary Thread — Job Results

Worktree: /root/lp-team-vocab | Branch: feat/dst-and-mock-draft
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

---

## Job 5 — Expand draft board to all positions (R5/B8)
**Commit:** `3c16d68`
**Draft board:** 522 → 1753 eligible players (removed skill-position restriction)
**Positions now visible:** all 67 ESPN NFL position codes including PK, LB, CB, DT, etc.
**Kicker data:** 42 active PKs now visible after ingest expansion

---

## Job 6 — Mark playoff rows (B10)
**Commit:** `ba4ae0b`
**Added:** `game_type` column to `player_game_logs` (REG/POST)
**Added:** `mark_playoff_game_types.py` migration script
**Result:** weeks 19-22 now marked POST, filtered out of availability queries explicitly

---

## Job 7 — Mock draft backend (M4, slice D)
**Commit:** `8bf1e7c`
**File:** backend/routers/nfl_mock_draft.py (642 lines)
**Endpoints:** pool (GET), create (POST), picks (POST), resume (GET), share (GET /public), list (GET)
**Pool:** 300 ranked players (QB/RB/WR/TE/PK), ADP-sorted, availability-aware
**Verified:** create → pick → resume → share full lifecycle, 12-team snake, pool returns correct data

---

## Job 8 — Snap counts table (M2)
**Commits:** `def15fa`, `e43ca6c`, `073e758`
**Table:** `nfl_snap_counts` — 20,627 rows for 2025, ALL positions, ALL weeks
**ingest_nfl_snap_counts.py:** dual-path — enriches game logs (skill players) + populates snap table (all players)
**_regular_season_aggregates:** presence from snap counts ∪ game logs, team_weeks from nfl_schedule (with fallback)
**Mock draft pool:** integrated M2 (snap counts + nfl_schedule for team weeks)
**Fix:** Brandon Aubrey 17 games (was 1), all kickers/defenders now show correct availability
**Pytest:** 80/81 passing (B5 pre-existing MLB failure, unrelated)

---

## Subagent delegation log

| Delegation | Task | Written | Committed |
|---|---|---|---|
| 76c2aec0 | team_codes.py | backend/team_codes.py, test_team_codes.py | fe9d6a1 |
| 3423d471 | normalize() boundaries | 8 ingest files | e40be76 |
| 3bd397f6 task-0 | team_weeks refactor | nfl_offseason.py | 2c9cb52 |
| 3bd397f6 task-1 | all-positions board | nfl_offseason.py, ingest | 3c16d68 |
| 95000bbf | Mock draft notes API | routers/nfl_draft_notes.py | (uncommitted) |
| 02b4513e | Mock draft engine (TS) | lib/mockDraft/engine.ts + tests | (uncommitted TS) |
| 64ed8792 | Mock draft UI (TS) | 7 component files | (uncommitted TS) |
| 3ea704c9 task-0 | D/ST stats ingest | ingest_nfl_dst.py, test_nfl_dst.py | (uncommitted) |
| 3ea704c9 task-1 | Mock draft backend M4 | routers/nfl_mock_draft.py | 8bf1e7c |

All subagents blocked from terminal — wrote code only, no runtime verification.

---

## Job 9 — Snap ingest NULL fix + game_type guard

### Fix 1 — ingest_nfl_snap_counts.py inverted NaN guard
**Commit:** `b3d2b29`
**Before:** 20,627 rows, 0 with non-NULL off_snaps/st_snaps (all NULL)
**After:** 20,627 rows, 20,627 with non-NULL off_snaps/st_snaps
**Root cause:** `continue` dropped from NaN guard — assignment body ran only for None/NaN values
**Also:** Changed INSERT OR IGNORE → ON CONFLICT DO UPDATE (idempotent re-runs)
**Cross-check:** Aubrey st_snaps wk1=8, wk2=15, wk3=6 — matches game-log stats JSON
**Board diff:** IDENTICAL (value columns only, presence unchanged)

### Fix 2 — nfl_offseason.py unguarded game_type read
**Commit:** `348ff2b`
**Before:** `AND game_type='REG'` hardcoded — 500s against unmigrated DBs (picks.dev.db)
**After:** guarded behind `_table_columns` check — matches every other schema read in the file
**Blocker status:** resolved — merge to dev no longer blocked

---

## Job 10 — D/ST players in mock draft pool

**Commit 1:** `9cab170` — add `DEF` to `_DRAFT_POSITIONS` (prerequisite, no-op alone)
**Commit 2:** (this commit) — query D/ST from `nfl_dst_stats`, derive `dst_rank`, append to pool

**Ranking:** SUM(fantasy_pts) from nfl_dst_stats 2025, descending. Column is `dst_rank`
(named distinct from `adp` — published D/ST ADP does not exist; 0/9,611 nfl_adp rows).

**Pool cap:** skill-player LIMIT reduced to `_POOL_CAP - dst_count` (268) so total stays 300.
D/ST land at #269–#300 — where defenses belong in a real draft.

### Before/after (measured, not expected)

| Position | Before | After |
|----------|--------|-------|
| RB       | 86     | 73    |
| WR       | 106    | 97    |
| TE       | 42     | 36    |
| QB       | 39     | 37    |
| PK       | 27     | 25    |
| **DEF**  | **0**  | **32** |
| **Total**| **300**| **300**|

### Verification

- **First D/ST:** #269 SEA D/ST (dst_rank=1, 164.0 pts), **Last:** #300 NYJ D/ST (dst_rank=32)
- **Lifecycle:** create → pick Josh Allen → pick SEA D/ST → resume: 2 picks, status=active ✓
- **Sanity:** all DEF have `adp: null, percent_owned: null`; no ADP pollution ✓
- **Regression:** draft board unchanged (1819 eligible, different surface, different code path)
