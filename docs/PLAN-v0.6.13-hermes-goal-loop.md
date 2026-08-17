Now I have complete knowledge of the codebase. Here is the plan.

---

# EXECUTABLE PLAN — v0.6.13 Re-Cut

## PREAMBLE: Current State

The `dev` branch (as of `8793915`) already has structural fixes for three of four audit blockers:
- **Blocker 1** (league-blind filter): Fixed — `_reg_season_game_filter` at `backend/routers/players.py:16` already checks `if league != "nfl": return ""`.
- **Blocker 4** (14-team persistence): Fixed — `append_picks` at line 601-606 reads `teams, rounds` from the draft row and validates dynamically.
- **player_stats uniqueness**: Fixed — `league_stats.py:93` reads `UNIQUE(player_id, league, season, stat_type)`.

What **remains** to be done falls into five categories:
1. Data that doesn't exist in production (2026 schedule, Team Stats, 2026 ESPN projections, cleaned MLB/NHL canonical stats)
2. API endpoints that don't expose fields already ingested (espn_ppr_rank from nfl_adp)
3. A new projection table/schema that doesn't exist yet
4. Frontend UI that doesn't show RK/PROJ columns or the 2026/2025 comparison
5. Full rehearsal + verification on a production clone

---

## PHASE 0 — ISOLATE AND PIN (0 database writes)

### Step 0.1 — Create clean worktree
```
git worktree add /root/lp-v0613-recut dev
cd /root/lp-v0613-recut
```
- **Touches:** new worktree at `/root/lp-v0613-recut`
- **DB touched:** none
- **Verify:** `git branch --show-current` → branch name (detached or `lp-v0613-recut`)

### Step 0.2 — Pin the ESPN response contract artifact
Fetch the live ESPN endpoint and save the response as a pinned JSON snapshot:
```
cd /root/lp-v0613-recut/backend
curl -s -H "x-fantasy-filter: {\"players\":{\"limit\":3000,\"sortDraftRanks\":{\"sortPriority\":1,\"sortAsc\":true,\"value\":\"STANDARD\"}}}" \
  "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/players?scoringPeriodId=0&view=kona_player_info" \
  -o data/espn_2026_snapshot_page1.json
```
- **Touches:** `backend/data/espn_2026_snapshot_page1.json`
- **DB touched:** none
- **Verify:** `python3 -c "import json; d=json.load(open('data/espn_2026_snapshot_page1.json')); print(len(d), 'players')"` → ~3000

Record the sha256 of the pinned snapshot for later audit:
```
sha256sum backend/data/espn_2026_snapshot_page1.json
```

### Step 0.3 — Pin the nflverse 2026 schedule artifact
```
cd /root/lp-v0613-recut/backend
curl -sL -o data/nflverse_games_2026.csv \
  "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
```
- **Touches:** `backend/data/nflverse_games_2026.csv`
- **DB touched:** none
- **Verify:** `grep -c "^2026," data/nflverse_games_2026.csv` → 272 (or close; count REG games)

### Step 0.4 — Pin the Team Stats source artifacts
For NBA (already on DEV), NFL (already on DEV), NHL (already on DEV) — identify and pin the exact CSV/parquet artifacts. These are the source files that `backfill_team_parity.py` and `backfill_team_stats.py` consume. Record their sha256 hashes.

- **Touches:** artifact paths documented in plan (not copied — references to existing DEV data)
- **DB touched:** none
- **Verify:** list artifacts with `sha256sum`

### Step 0.5 — Create the disposable production clone (CRITICAL — all DB work from here forward uses this)
```
cd /root/lp-v0613-recut/backend
cp data/picks.db /tmp/lp-v0613-rehearsal.db
sqlite3 /tmp/lp-v0613-rehearsal.db "PRAGMA quick_check"
```
- **Touches:** `/tmp/lp-v0613-rehearsal.db` (copy of production)
- **DB touched:** production DB READ ONLY (the `cp`), then the clone exclusively
- **Verify:** `PRAGMA quick_check` returns `ok`; `SELECT COUNT(*) FROM player_game_logs` → matches production

Export path for the rest of the plan:
```
export LP_DB_PATH=/tmp/lp-v0613-rehearsal.db
```
Every command from Phase 1 onward that touches the database targets this clone. Production DB is never written.

---

## PHASE 1 — APPLY AND VERIFY SCHEMA MIGRATIONS

### Step 1.1 — Apply missing v0.6.13 schema migrations to the clone
The v0.6.13 migrations already exist (commits `5886d1f`, `3e46097`, `465a626`). Apply them:
```
cd /root/lp-v0613-recut/backend
LP_DB_PATH=/tmp/lp-v0613-rehearsal.db venv/bin/python migrate_schema.py --apply
```
- **DB touched:** `/tmp/lp-v0613-rehearsal.db`
- **Verify:** `sqlite3 /tmp/lp-v0613-rehearsal.db "SELECT migration_id, applied_at FROM app_schema_migrations ORDER BY migration_id"` — lists all applied migrations

### Step 1.2 — Verify game_type column exists on the clone
```
sqlite3 /tmp/lp-v0613-rehearsal.db "SELECT name FROM pragma_table_info('player_game_logs') WHERE name='game_type'"
```
- **DB touched:** clone
- **Verify:** returns `game_type`

### Step 1.3 — Create the projection schema migration (NEW)
Create a new migration file for the projection table. Schema:
```sql
CREATE TABLE IF NOT EXISTS nfl_player_projections (
    player_id INTEGER NOT NULL,
    espn_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    scoring_period_id INTEGER NOT NULL DEFAULT 0,
    stat_source_id INTEGER NOT NULL DEFAULT 1,
    stat_split_type_id INTEGER NOT NULL DEFAULT 0,
    raw_projection_json TEXT NOT NULL,       -- full ESPN stat map
    projected_games INTEGER,
    -- position-relevant normalized fields
    pass_att REAL, pass_cmp REAL,
    pass_yds REAL, pass_td REAL,
    interceptions REAL,
    rush_att REAL, rush_yds REAL, rush_td REAL,
    receptions REAL, targets REAL,
    rec_yds REAL, rec_td REAL,
    fumbles REAL, fumbles_lost REAL,
    fg_att REAL, fg_made REAL,
    xp_att REAL, xp_made REAL,
    def_td REAL, def_int REAL, def_sack REAL, def_fumble_rec REAL,
    def_points_allowed REAL, def_yds_allowed REAL,
    -- Legendary Picks computed
    lp_ppr_projected_points REAL,
    -- provenance
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    payload_checksum TEXT,
    PRIMARY KEY (player_id, season)
)
```
This migration file goes in a new `backend/data/migrations/` directory.

- **Files touched:** New migration file, `migrate_schema.py` (register it)
- **DB touched:** clone
- **Verify:** `sqlite3 /tmp/lp-v0613-rehearsal.db ".schema nfl_player_projections"` → shows the table

### Step 1.4 — Create canonical player_stats uniqueness migration (if not present)
The `UNIQUE(player_id, league, season, stat_type)` constraint already exists in `league_stats.py:93` but may not have been applied to an existing table. Check:
```
sqlite3 /tmp/lp-v0613-rehearsal.db "SELECT sql FROM sqlite_master WHERE name='player_stats'"
```
If the UNIQUE constraint is missing, create a migration that rebuilds the table (since SQLite can't add constraints to existing tables). This must be fail-closed.

- **DB touched:** clone
- **Verify:** `PRAGMA index_list('player_stats')` shows the unique index

---

## PHASE 2 — FIX APPLICATION REGRESSIONS (code + test on clone)

### Step 2.1 — Verify league-blind filter is actually fixed (already in dev)
Run the test suite against the clone:
```
cd /root/lp-v0613-recut/backend
LP_DB_PATH=/tmp/lp-v0613-rehearsal.db venv/bin/python -m pytest test_players_profile_api.py -xvs
```
- **DB touched:** clone (read-only)
- **Verify:** Tests pass. Specifically, MLB/NBA/NHL/UFC profile queries return logs, matchups, and projections with non-zero counts.

### Step 2.2 — Verify 10/12/14-team draft persistence
```
cd /root/lp-v0613-recut/backend
LP_DB_PATH=/tmp/lp-v0613-rehearsal.db venv/bin/python -m pytest test_mock_draft_team_sizes.py -xvs
```
- **DB touched:** clone (writes to nfl_mock_drafts/picks — temporary test data)
- **Verify:** All tests pass. Specifically: 14-team draft with picks 181-210 and teams 13-14 persist correctly.

### Step 2.3 — Run full backend test suite
```
cd /root/lp-v0613-recut/backend
LP_DB_PATH=/tmp/lp-v0613-rehearsal.db venv/bin/python -m pytest -x --timeout=120 \
  test_players_profile_api.py \
  test_mock_draft_team_sizes.py \
  test_mock_draft_setup.py \
  test_mock_draft_completion.py \
  test_mock_draft_pool_parity.py \
  test_nfl_mock_draft.py \
  test_nfl_offseason_api.py \
  test_nfl_schedule_api.py \
  test_nfl_dst.py \
  test_ingest_nfl_adp.py \
  test_league_stats_contract.py \
  test_team_aggregates_contract.py \
  test_team_stats_contract.py \
  test_ufc_rankings_pipeline.py
```
- **DB touched:** clone
- **Verify:** All pass or flag only expected failures (pre-existing data gaps)

---

## PHASE 3 — INGEST 2026 ESPN PROJECTIONS AND RANK

### Step 3.1 — Extend ingest_nfl_adp.py to extract and store season projections
The ESPN response from the pinned snapshot already contains projection objects. Extend the ingest to parse:
- `player.playerStats` → find the entry where `seasonId=2026, scoringPeriodId=0, statSourceId=1, statSplitTypeId=0`
- Extract the raw `stats` map
- Compute `lp_ppr_projected_points` using a position-aware PPR formula

Create a new file `backend/ingest_nfl_projections.py` (or extend `ingest_nfl_adp.py`) that:
1. Reads the pinned snapshot JSON(s)
2. For each player, extracts the 2026 season projection stats
3. Maps ESPN stat IDs to named fields (see plan §"Do not ingest appliedTotal blindly")
4. Computes LP PPR points from raw stats
5. Writes to `nfl_player_projections` atomically (BEGIN → write all → COMMIT; ROLLBACK on any failure)

**PPR scoring formula (position-aware):**
- QB: `(pass_yds / 25) + (pass_td * 4) + (rush_yds / 10) + (rush_td * 6) - (interceptions * 2) - (fumbles_lost * 2)`
- RB/WR/TE: `(receptions * 1) + (rec_yds / 10) + (rec_td * 6) + (rush_yds / 10) + (rush_td * 6) - (fumbles_lost * 2)`
- K: `(fg_made_0_39 * 3) + (fg_made_40_49 * 4) + (fg_made_50_plus * 5) + (xp_made * 1) - (fg_missed * 1)` — using whatever ESPN keys map
- D/ST: `(def_int * 2) + (def_fumble_rec * 2) + (def_sack * 1) + (def_td * 6) + (def_safety * 2)` + points-allowed tier

- **Files touched:** New `backend/ingest_nfl_projections.py` (+ PPR formula module), possibly `backend/routers/nfl_mock_draft.py` to import
- **DB touched:** clone only
- **Verify:** Run the ingest, then check `SELECT COUNT(*) FROM nfl_player_projections WHERE season=2026` → ≥283 (coverage from the re-cut plan)

### Step 3.2 — Create PPR scoring test fixtures
Create `backend/test_nfl_ppr_scoring.py` with named position fixtures:
- QB named fixture against known Justin Jefferson/CeeDee Lamb projected stats
- RB/WR/TE fixture
- K fixture
- D/ST fixture
Each fixture has known input and independently-calculated expected output.

- **Files touched:** New `backend/test_nfl_ppr_scoring.py`
- **DB touched:** clone
- **Verify:** `venv/bin/python -m pytest test_nfl_ppr_scoring.py -xvs` → all pass

### Step 3.3 — Expose rank and projection in the pool API
Modify `backend/routers/nfl_mock_draft.py::pool()` (line 225) to:
- JOIN `nfl_adp.espn_ppr_rank` into the pool query
- JOIN `nfl_player_projections.lp_ppr_projected_points` into the pool query
- Add fields to each player dict: `espn_ppr_rank`, `proj_pts`
- Sort by `espn_ppr_rank ASC NULLS LAST` (default) instead of ADP

- **Files touched:** `backend/routers/nfl_mock_draft.py`
- **DB touched:** clone (read)
- **Verify:** `curl http://localhost:8096/api/nfl/mock-draft/pool?season=2026 | python3 -m json.tool | head -60` → check first player has `espn_ppr_rank: 1`, `proj_pts` is non-null, ordering is by rank

### Step 3.4 — Expose rank and projection in the player_detail API
Modify `backend/routers/nfl_mock_draft.py::player_detail()` (line 857) to:
- Query `nfl_adp.espn_ppr_rank` and `nfl_adp.espn_standard_rank`
- Query `nfl_player_projections` for the full projection stat breakdown + `lp_ppr_projected_points`
- Return `espn_ppr_rank`, `espn_standard_rank`, `projection_2026` (normalized stat map), `proj_2026_pts`

- **Files touched:** `backend/routers/nfl_mock_draft.py`
- **DB touched:** clone (read)
- **Verify:** `curl http://localhost:8096/api/nfl/mock-draft/player/XXX` (a known player ID) → response includes `espn_ppr_rank`, `projection_2026` with stat fields, and `proj_2026_pts`

### Step 3.5 — Verify rank/projection coverage gates
```
cd /root/lp-v0613-recut/backend
LP_DB_PATH=/tmp/lp-v0613-rehearsal.db venv/bin/python -c "
import sqlite3
db = sqlite3.connect('/tmp/lp-v0613-rehearsal.db')
db.row_factory = sqlite3.Row

# Gate: 32/32 D/ST have projections
dst = db.execute('''SELECT COUNT(*) as n FROM nfl_player_projections np
    JOIN players p ON p.id=np.player_id WHERE p.position='DEF' AND np.season=2026''').fetchone()
print(f'D/ST with projections: {dst[\"n\"]} (need 32)')

# Gate: rank coverage
pool = db.execute('SELECT COUNT(*) as n FROM nfl_adp WHERE season=2026 AND espn_ppr_rank IS NOT NULL').fetchone()
print(f'Players with PPR rank: {pool[\"n\"]} (need >=299)')

# Gate: honest nulls
nulls = db.execute('SELECT COUNT(*) as n FROM nfl_adp WHERE season=2026 AND espn_ppr_rank IS NULL').fetchone()
print(f'Players without PPR rank: {nulls[\"n\"]} (should be 1-2, all honest)')

# Gate: CeeDee, Jefferson, London, Rice have correct ranks
for name in ['CeeDee Lamb', 'Justin Jefferson', 'Drake London', 'Rashee Rice']:
    r = db.execute('''SELECT na.espn_ppr_rank FROM nfl_adp na
        JOIN players p ON p.id=na.player_id WHERE p.name=? AND na.season=2026''', (name,)).fetchone()
    print(f'{name}: rank={r[\"espn_ppr_rank\"] if r else \"MISSING\"}')"
```
- **DB touched:** clone (read)
- **Entry criteria:** All gates must be green before Phase 4
- **Exit criteria:** D/ST=32, rank≥299, honest nulls≥1, CeeDee=9, Jefferson=11, London=13, Rice=14

---

## PHASE 4 — REHEARSE ALL PRODUCTION DATA

### Step 4.1 — Rehearse 2026 schedule population
```
cd /root/lp-v0613-recut/backend
LP_DB_PATH=/tmp/lp-v0613-rehearsal.db venv/bin/python ingest_nfl_schedule.py \
  --season 2026 --schedule-only --csv data/nflverse_games_2026.csv
```
- **DB touched:** clone (writes to nfl_schedule)
- **Verify:**
```
sqlite3 /tmp/lp-v0613-rehearsal.db "
SELECT COUNT(*) FROM nfl_schedule WHERE season=2026;           -- 272
SELECT COUNT(DISTINCT team) FROM nfl_schedule WHERE season=2026; -- 32
SELECT team, COUNT(*) as g, COUNT(DISTINCT week) as w
  FROM nfl_schedule WHERE season=2026 GROUP BY team
  ORDER BY w DESC;  -- each team: 17 weeks, 1 bye (check for 18 distinct weeks including bye)
SELECT COUNT(*) FROM nfl_schedule WHERE season=2025;            -- 285 (unchanged)
"
```
- **Verify API:** `curl http://localhost:8096/api/nfl/schedule/2026 | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['teams']),'teams')"` → 32 teams

### Step 4.2 — Rehearse scoped Team Stats migration for NBA/NFL/NHL
The DEV database already has complete populations. The problem is production doesn't. Create and run `backend/migrate_team_stats.py` that:
1. Copies `team_game_results` rows for approved league/season windows from DEV to the clone
2. Copies matching `team_game_stats` rows
3. Populates `team_stats_coverage` manifests
4. Treats the Team Stats migration registry separately from `app_schema_migrations`
5. Is fail-closed: if any league population fails verification, rollback all three

Approved windows:
- NBA: 2025-26 regular season (1,227 games, 2,454 result rows)
- NFL: 2025 regular season (272 games, 544 result rows)
- NHL: 2025-26 regular season (1,311 games, 2,622 result rows)

- **Files touched:** New `backend/migrate_team_stats.py`
- **DB touched:** clone (writes)
- **Verify:**
```
sqlite3 /tmp/lp-v0613-rehearsal.db "
SELECT league, COUNT(*) FROM team_game_results GROUP BY league;
SELECT league, COUNT(*) FROM team_game_stats GROUP BY league;
SELECT league, games FROM team_stats_coverage;
"
```

### Step 4.3 — Verify Team Stats API endpoints
```
curl http://localhost:8096/api/nba/team-aggregates | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['supported'], len(d.get('teams',[])))"
curl http://localhost:8096/api/nfl/team-aggregates | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['supported'], len(d.get('teams',[])))"
curl http://localhost:8096/api/nhl/team-aggregates | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['supported'], len(d.get('teams',[])))"
```
- **DB touched:** clone (read)
- **Verify:** All three return `supported=true` with non-empty teams arrays

### Step 4.4 — Rebuild canonical MLB player_stats population
The audit found MLB has 3,162 rows for 2,397 distinct players (= duplicate IDs). Run a scoped rebuild:
1. Delete all `player_stats` rows for `league='mlb'` on the clone
2. Re-run `ingest_statcast.py` (the verified publisher) against the clone
3. Verify: `SELECT COUNT(*), COUNT(DISTINCT player_id) FROM player_stats WHERE league='mlb'` → counts match (no duplicates)
4. Verify: leader API returns unique player IDs

- **Files touched:** run `ingest_statcast.py` (already exists)
- **DB touched:** clone (delete + reinsert)
- **Verify:** `/api/mlb/leaders?type=batting&limit=100` → no duplicate player_ids, Jung Hoo Lee's ID matches `/api/player/26777`

### Step 4.5 — Resolve NHL publisher ownership (deduplicate)
The audit found NHL has overlapping published and derived `player_stats` rows. Decision: `ingest_nhl.py` (published) is the canonical source; retire derived rows from `derive_player_stats.py` for NHL.
1. Delete rows from `player_stats` where `league='nhl' AND source='derived'`
2. Verify: `SELECT COUNT(*), COUNT(DISTINCT player_id) FROM player_stats WHERE league='nhl'` → counts match
3. Verify: `/api/nhl/leaders?limit=100` → no duplicate player_ids

- **Files touched:** Run SQL on clone; patch `derive_player_stats.py` to skip NHL
- **DB touched:** clone
- **Verify:** No duplicate player_ids in NHL leader response

### Step 4.6 — Repair canonical player identity: verify MLB player_id=26777
```
sqlite3 /tmp/lp-v0613-rehearsal.db "
SELECT p.id, p.name, p.team, p.league, p.mlbam_id
FROM players p WHERE p.id=26777;
-- Should return Ethan Roberts, not Jung Hoo Lee
SELECT ps.player_id, p.name, ps.stat_type, ps.season
FROM player_stats ps JOIN players p ON p.id=ps.player_id
WHERE ps.player_id=26777;
-- Stats should belong to Ethan Roberts
"
```
If player_id=26777 still has the wrong identity, investigate the `players` table for duplicate `mlbam_id` values and fix the join path.

- **DB touched:** clone (read, then write if repair needed)
- **Verify:** `/api/player/26777` returns Ethan Roberts, and his stats belong to him

### Step 4.7 — Run the full Phase 4 invariant verification suite
```
sqlite3 /tmp/lp-v0613-rehearsal.db "
-- Quick check
PRAGMA quick_check;

-- Row count invariants
SELECT 'nfl_schedule 2026', COUNT(*) FROM nfl_schedule WHERE season=2026;
SELECT 'nfl_schedule 2025', COUNT(*) FROM nfl_schedule WHERE season=2025;
SELECT 'team_game_results by league', league, COUNT(*) FROM team_game_results GROUP BY league;
SELECT 'team_game_stats by league', league, COUNT(*) FROM team_game_stats GROUP BY league;

-- No duplicate player_ids in player_stats
SELECT league, COUNT(*)-COUNT(DISTINCT player_id) as dupes FROM player_stats GROUP BY league HAVING dupes > 0;

-- Protected prop tables unchanged (compare row counts with prod baseline)
SELECT 'props', COUNT(*) FROM props;
SELECT 'prop_results', COUNT(*) FROM prop_results;
SELECT 'prop_games', COUNT(*) FROM prop_games;

-- NFL adp coverage
SELECT COUNT(*), COUNT(espn_ppr_rank) FROM nfl_adp WHERE season=2026;

-- NFL projection coverage
SELECT COUNT(*) FROM nfl_player_projections WHERE season=2026;
"
```
- **DB touched:** clone (read)
- **Verify:** All invariants match expected values

---

## PHASE 5 — RESTORE ESPN-PARITY UI

### Step 5.1 — Add RK, PROJ, BYE columns to the draft room table
Modify `components/Leagues/NflDraftRoom.tsx`:
- Replace the current default columns with: `RK | PLAYER | BYE | ADP | PROJ | AVAILABLE | action`
- `RK` reads from `pool_player.espn_ppr_rank`, renders `—` for null
- `PROJ` reads from `pool_player.proj_pts`, renders `—` for null
- `BYE` reads from `pool_player.bye_week` (or compute from schedule)
- Default sort: `RK` ascending, nulls last
- Sort options: `Rank · Proj Pts · ADP · Availability · Bye · 2025 Pts/G · 2025 xFP`

- **Files touched:** `components/Leagues/NflDraftRoom.tsx`, `components/Leagues/types.ts` (add types), `components/Leagues/hooks/useNflDraftBoard.ts` (add sort options)
- **DB touched:** none
- **Verify:** `npm run build` succeeds; browser renders the new columns

### Step 5.2 — Restore the player card: PROJ 2026 above 2025
Modify `components/Leagues/PlayerDetailOverlay.tsx`:
- In the season stats table, add `PROJ 2026` row above `2025`
- `PROJ 2026` reads from `player_detail.projection_2026` fields
- Position-relevant columns:
  - QB: `ATT / CMP / PASS YDS / PASS TD / INT / RUSH / PPR`
  - RB/WR/TE: `CAR / REC / TAR / YDS / TD / PPR`
  - K: `FG / FGA / XP / PPR PTS`
  - D/ST: `SACK / INT / FR / TD / PA / PPR PTS`
- Unsupported fields render `—`

- **Files touched:** `components/Leagues/PlayerDetailOverlay.tsx`, `components/Leagues/types.ts`
- **DB touched:** none
- **Verify:** browser — open any player card, see PROJ 2026 row with position-relevant stats

### Step 5.3 — Run frontend tests
```
cd /root/lp-v0613-recut
npx jest --testPathPattern='NflDraftRoom|mock-draft|PlayerDetail' --passWithNoTests
```
- **DB touched:** none
- **Verify:** Tests pass; no console errors

### Step 5.4 — Production Next.js build
```
cd /root/lp-v0613-recut
npm run build 2>&1 | tail -20
```
- **DB touched:** none
- **Verify:** Build succeeds with no errors

---

## PHASE 6 — WHOLE-APP BROWSER ACCEPTANCE (against the clone)

Start the v0.6.13 candidate against the production clone:
```
cd /root/lp-v0613-recut/backend
LP_DB_PATH=/tmp/lp-v0613-rehearsal.db venv/bin/uvicorn sports_service:app --host 127.0.0.1 --port 8196 &
# Wait for startup
curl http://localhost:8196/api/health
```

And frontend:
```
cd /root/lp-v0613-recut
LP_BACKEND=http://localhost:8196 npm run dev -- -p 3196 &
```

### Browser gate checklist (systematic — every gate at the acceptance level):

**NFL Mock Draft gates:**
- [ ] `/mock-draft` loads, shows 300-player pool
- [ ] Default sort is `RK` ascending, CeeDee Lamb at rank 9
- [ ] `PROJ` column shows 2026 projected points (non-null for 283+ players)
- [ ] `BYE` column shows correct bye week (schedule-backed)
- [ ] `ADP` column shows real ESPN ADP
- [ ] `AVAILABLE` column shows availability status
- [ ] Filter by position works for all 6 positions (QB/RB/WR/TE/PK/DEF)
- [ ] Sort by each option works, nulls always last
- [ ] 10-team draft: create → append picks 1-150 → resume → verify 150 picks
- [ ] 12-team draft: create → append picks 1-180 → resume → verify 180 picks
- [ ] 14-team draft: create → append picks 1-210 → resume → verify 210 picks
- [ ] Player card: `PROJ 2026` row visible above `2025`
- [ ] Player card: position-relevant columns for each position
- [ ] Player card: Overview / Stats / Game Log tabs work

**Shared player profile gates (non-NFL):**
- [ ] MLB: `/player/{id}` for James Wood → shows recent logs, matchups, projections
- [ ] NBA: `/player/{id}` for Julian Champagnie → shows recent logs
- [ ] NHL: `/player/{id}` for Brett Kulak → shows recent logs
- [ ] UFC: `/player/{id}` for Dustin Jacoby → shows recent fights

**Leaderboard uniqueness gates:**
- [ ] `/api/mlb/leaders?type=batting&limit=100` → no duplicate player_ids
- [ ] `/api/nhl/leaders?limit=100` → no duplicate player_ids
- [ ] Each leader's displayed identity agrees with `/api/player/{id}`

**Team Stats browser gates:**
- [ ] NBA Team Stats page loads with supported data
- [ ] NFL Team Stats page loads with supported data
- [ ] NHL Team Stats page loads with supported data

**UFC gates:**
- [ ] UFC Rankings page loads P4P and divisional rankings
- [ ] UFC fighter history shows durable fight records

**Esports gates:**
- [ ] Esports slate loads, match deduplication correct
- [ ] Stream links resolve
- [ ] Pick persistence works

**World Cup gates:**
- [ ] World Cup pages render (protected data unchanged)
- [ ] Existing WC tests pass

**Console gate:**
- [ ] `browser_console()` → zero unexpected errors across all pages

---

## PHASE 7 — TAG AND RELEASE

### EXACT AUTHORIZATION GATE
**No tag movement, no production write, no image build, no deployment until Micah explicitly authorizes Phase 7.** This authorization must be a direct message saying to proceed.

### Step 7.1 — Record the accepted commit
Once every Phase 5-6 gate is green:
```
cd /root/lp-v0613-recut
ACCEPTED_COMMIT=$(git rev-parse HEAD)
echo "ACCEPTED: $ACCEPTED_COMMIT" > /tmp/lp-v0613-accepted.txt
git diff --stat dev..HEAD  # should be the v0.6.13 re-cut changes
```

### Step 7.2 — Remove the bad v0.6.13 tag
```
git tag -d v0.6.13                                    # delete local
git push origin :refs/tags/v0.6.13                    # delete remote (with lease check)
```

### Step 7.3 — Re-create the annotated tag on the accepted commit
```
cd /root/lp-v0613-recut
git tag -a v0.6.13 -m "v0.6.13 — whole-app release, re-cut 2026-07-31"
git push origin v0.6.13
```

### Step 7.4 — Verify tag
```
git fetch --tags
git tag -v v0.6.13 2>/dev/null || git show v0.6.13 --no-patch
# Peel to commit: should match ACCEPTED_COMMIT
test "$(git rev-parse v0.6.13^{commit})" = "$ACCEPTED_COMMIT" && echo "MATCH" || echo "MISMATCH — STOP"
```

### Step 7.5 — Build production images
```
cd /root/lp-v0613-recut
docker compose build --no-cache
docker images | grep legendarypicks
```

### Step 7.6 — Final authorization request
At this point, report to Micah:
- Accepted commit hash
- Tag verification result
- Image build status
- Full Phase 5-6 gate results
- **Request explicit authorization to: (a) migrate data to production DB, (b) deploy new images, (c) restart services**

### Step 7.7 — Production deployment (only after authorization)
1. Apply migrations to production DB: `LP_DB_PATH=backend/data/picks.db venv/bin/python migrate_schema.py --apply`
2. Run Team Stats migration against production DB
3. Run 2026 schedule population against production DB
4. Run projection ingest against production DB
5. Rebuild MLB/NHL canonical player_stats (scoped deletes on approved windows)
6. Take a backup: `cp backend/data/picks.db backend/data/picks.db.v0.6.13-pre-deploy.bak`
7. `docker compose up -d --build`
8. Verify live domain: `curl https://legendarypicks.xyz/api/health` → `{"status":"ok","version":"0.6.13"}`
9. Browser verification on live domain (spot-check the 5 critical gates)

---

## DATABASE TOUCH SUMMARY

| Step | DB Targeted | Write? | What |
|------|------------|--------|------|
| 0.5 | Production | READ ONLY | `cp` to create clone |
| 1.1-1.4 | Clone only | YES | Schema migrations |
| 2.1-2.3 | Clone only | YES (test data) | Regression tests |
| 3.1-3.2 | Clone only | YES | Projection ingest |
| 3.3-3.5 | Clone only | READ | API verification |
| 4.1 | Clone only | YES | Schedule population |
| 4.2 | Clone only | YES | Team Stats migration |
| 4.4-4.6 | Clone only | YES | MLB/NHL canonical rebuild |
| 5.x | None | — | Frontend only |
| 6.x | Clone only | READ + test writes | Browser acceptance |
| 7.7 | **PRODUCTION** | **YES** | **ONLY after Phase 7 authorization** |

---

## ENTRY/EXIT CRITERIA BY PHASE

| Phase | Entry | Exit |
|-------|-------|------|
| 0 | Plan approved | Clone created, artifacts pinned, sha256s recorded |
| 1 | Clone exists | All migrations applied, schema verified |
| 2 | Migrations applied | All backend tests pass on clone |
| 3 | Tests passing | 283+ projections, 299+ ranks, D/ST=32, RK gates green |
| 4 | Projections populated | Schedule: 272 games/32 teams; Team Stats: 3 leagues supported; MLB/NHL: no duplicate player_ids; all invariants pass |
| 5 | Data ready | Next build succeeds; RK/PROJ columns render; player card shows PROJ 2026 |
| 6 | Build succeeds | Every browser gate checked green; zero console errors |
| 7 | Micah authorizes | v0.6.13 tagged on correct commit; images built; deployed; live verified |

---

This plan is ready for review. No production writes happen until Phase 7 authorization. Every data-touching step from Phase 1-6 targets the disposable clone at `/tmp/lp-v0613-rehearsal.db`.
