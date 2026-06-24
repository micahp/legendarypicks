# STORAGE-MIGRATION-DESIGN.md — Migration to the Game→Team→Player Spine

**Date:** 2026-06-24  
**Author:** reasonix (deepseek-v4-pro)  
**Task:** M2-impl — schema migration design  
**Status:** READ-ONLY design doc — no DB/code changes made  
**Source DDL:** `backend/data/picks.db` (live `.schema`, read 2026-06-24)

---

## 1. Target Shape

From `docs/OFFSEASON-DATA-DESIGN.md` §3, the target spine inverts the current props-centric model:

```
games ──────→ team_game_stats ──────→ game_player_stats      ←── STAT SPINE
  │                │                        │
  │                │                        │ (player_id FK)
  │                │                        ↓
  │                │                players (canonical identity)
  │                │                        ↑
  │                │                        │ (player_id FK)
  │                │              props ──→ prop_results      ←── hang OFF spine
  │                │
  │                ↓
  │         team_season_stats (aggregate VIEW or materialized)
  ↓
game_context (venue, attendance, officials)
```

**Key principle:** Props are a child of `(game_id, player_id)`, both of which exist independently in the spine. Games/teams/players can be ingested without any prop data. The app can show stats even when no props are available.

**Target tables:**

| New Table | Purpose | Replaces |
|-----------|---------|----------|
| `games` | Canonical game spine — one row per game, keyed by `espn_event_id` | `prop_games` (promoted + enriched) |
| `game_player_stats` | Per-game, per-player boxscore rows | `player_stats` season aggregates (demotes to VIEW) |
| `props` (migrated) | Props re-attached to `games.id` and `players.id` | `props` (current, with FK change) |
| `prop_results` (unchanged) | Settlement — hangs off `props.id` | — |
| `team_game_stats` (refactored) | Per-game team totals with FK to `games.id` | `team_game_stats` (current, add FK) |
| `game_context` (refactored) | Venue/attendance/officials with FK to `games.id` | `game_context` (current, add FK) |
| `odds_snapshots` (new, M6) | Odds time-series — hangs off `props.id` or `(game_id, market_key)` | — |

---

## 2. Current Schema Map

### 2.1 Live tables (from `sqlite3 picks.db .schema` on 2026-06-24)

#### `players` — canonical identity spine ✅
```
id, name, team, league, espn_id, mlbam_id, nfl_gsis_id, nhl_id, nba_id, active, position, updated_at
```
**Disposition:** **KEEP as-is.** This is already the correct shape. No migration needed for the table itself. The `player_id` FK in `game_player_stats` will reference this.

#### `prop_games` — thin game wrapper (props-centric)
```
id, league, date, home, away, espn_event_id, final_home, final_away
```
**Disposition:** **PROMOTE to `games`.** Every row in `prop_games` becomes a row in `games`. The `espn_event_id` is the canonical cross-source key. `games` adds `season`, `season_type`, `game_datetime`, `home_score`, `away_score`, `linescores`, `status`, `status_detail`, `period`, `clock`, `source`, `captured_at`.

#### `props` — prop lines
```
id, game_id→prop_games.id, player_id→players.id, market, line, side, source, captured_at
```
**Disposition:** **MIGRATE** `game_id` FK from `prop_games.id` to `games.id`. The `player_id` FK stays. Add `odds_decimal`, `implied_prob` (M6 fields, see §3.2).

#### `prop_results` — settlement output
```
prop_id→props.id, actual_value, hit, settled_at
```
**Disposition:** **KEEP as-is** (FK to `props.id` is unchanged; only `props.game_id` changes, not `props.id`).

#### `player_stats` — season-level aggregates (the current "stat spine")
```
id, player_name, name_norm, league, team, stat_type, season, games,
[league-specific stat columns — 50+], source, player_id→players.id
```
**Disposition:** **DEMOTE to a materialized VIEW/rollup** from `game_player_stats`. Keep as a read-only cache during migration so the API doesn't break. After `game_player_stats` is populated and API reads switch over, `player_stats` can be dropped or kept as a fast aggregate cache.

⚠️ **Note:** There is also a `player_stats_new` table in the live schema with identical columns but missing the `player_id` FK and using `assists_` instead of `assists`. No Python code references it — it's an orphan. Drop during cleanup phase.

#### `team_game_stats` — per-game team totals
```
league, game_id, captured_at, team_abbrev, home_away,
[league-specific team stats — 30+ columns]
```
**Disposition:** **REFACTOR** — add `game_id_fk INTEGER REFERENCES games(id)` column. The existing `game_id` column holds the ESPN event ID (a string like "401769991"). The new `game_id_fk` joins to `games.id`. During migration, backfill `game_id_fk` via `games.espn_event_id = team_game_stats.game_id`.

**Current write paths:**
- `backfill_team_stats.py` — day-by-day ESPN boxscore → `team_game_stats` (idempotent upsert)
- `sports_service.py:_snapshot_team_game_stats()` — called from the per-game boxscore endpoint

**Current read paths:**
- `sports_service.py:206` — `"SELECT * FROM team_game_stats WHERE league=?"` (all games for league)
- `sports_service.py:249` — `"SELECT * FROM team_game_stats WHERE league=? AND game_id=?"` (per-game)

#### `game_context` — venue/attendance/officials
```
league, game_id PRIMARY KEY, captured_at, home_team, away_team, venue_name, venue_city, attendance, officials
```
**Disposition:** **REFACTOR** — change PK from `game_id` to `id`, add `game_id_fk INTEGER REFERENCES games(id)`. The existing `game_id` is the ESPN event ID string. Backfill via `games.espn_event_id`.

#### `scoring_plays` — play-by-play scoring events
```
league, game_id, play_id, captured_at, period, period_disp, clock, away_score, home_score, team_abbrev, scorer_name, play_text, play_type
```
**Disposition:** **REFACTOR** — add `game_id_fk INTEGER REFERENCES games(id)`. Backfill via `games.espn_event_id`.

#### `roster_snap` — roster snapshots
```
captured_at, league, team_abbrev, player_id, name, jersey, position
```
**Disposition:** **KEEP as-is** — rosters are team-level, not game-level. The `player_id` field here is an ESPN player ID string, NOT a FK to `players.id`. This is a known identity gap — these should be crosswalked to `players.id` or at minimum also store the `espn_id` for lookup.

#### `strength_snap` — team strength history
```
captured_at, league, abbrev, win_pct, differential, wins, losses
```
**Disposition:** **KEEP as-is** — this is team-level, not game-level. No FK change needed.

#### `predictions` — user predictions
```
id, league, game_id, predicted_winner, created_at, correct
```
**Disposition:** **KEEP as-is** — `game_id` here is the ESPN event ID string. Optionally add `game_id_fk` for consistency but not required.

#### `unresolved_players` + `name_alias` — identity resolution queue
```
unresolved_players: id, source, raw_name, league, team, first_seen, count
name_alias: id, player_id→players.id, alias_norm
```
**Disposition:** **KEEP as-is** — these support the identity spine and don't change.

### 2.2 Summary: what moves where

| Current Table | Action | New Table / Change |
|--------------|--------|--------------------|
| `prop_games` | Promote + enrich | → `games` (one row per `prop_games` row + backfill from ESPN) |
| `props` | Migrate FK | `game_id` → `games.id` (add `odds_decimal`, `implied_prob` for M6) |
| `prop_results` | Keep | No change (references `props.id`) |
| `player_stats` | Demote | → materialized VIEW from `game_player_stats` |
| `player_stats_new` | Drop | Orphan — no code references it |
| `team_game_stats` | Add FK column | `game_id_fk → games.id` |
| `game_context` | Add FK column | `game_id_fk → games.id` |
| `scoring_plays` | Add FK column | `game_id_fk → games.id` |
| `players` | Keep | Unchanged (the identity anchor) |
| `roster_snap` | Keep | Unchanged |
| `strength_snap` | Keep | Unchanged |
| `predictions` | Keep | Unchanged |
| `unresolved_players` | Keep | Unchanged |
| `name_alias` | Keep | Unchanged |

---

## 3. Absorption Plan for M5/M6 Incremental Tables

### 3.1 M5 — Team Stats Enrichment (hermes, in progress)

**What M5 is building:** Enriched per-game team stats for NBA/NHL/NFL (currently "glorified standings" per CONTEXT gap #4). Hermes is writing to the existing `team_game_stats` table via `backfill_team_stats.py`.

**Absorption into new spine:**
- The existing `team_game_stats` table is **already compatible** with the target spine — it stores per-game team data keyed by `league + game_id + team_abbrev`.
- The only change needed: add `game_id_fk INTEGER REFERENCES games(id)` and backfill it.
- **Zero throwaway:** Hermes' M5 output writes directly into a table that survives the migration with only a column addition. No rewrite needed.
- **Timeline:** M5 can ship against the current `team_game_stats` immediately. The migration adds the FK column later (additive, no data loss).

### 3.2 M6 — Odds Capture (designed, not yet built)

**What M6 will add (per ANALYTICS-BACKBONE.md Layer 1–2):**
- `props.odds_decimal` + `props.implied_prob` columns (capture odds at ingest)
- `odds_snapshots` table: `(market_key, line, side, odds_decimal, implied_prob, vig, captured_at, source)` — time-series for CLV computation

**Absorption into new spine:**

**Option A (recommended): Add columns directly to `props` + new `odds_snapshots`**
```sql
ALTER TABLE props ADD COLUMN odds_decimal REAL;
ALTER TABLE props ADD COLUMN implied_prob REAL;

CREATE TABLE odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prop_id INTEGER REFERENCES props(id),   -- NULL if market-level (pre-game)
    game_id INTEGER REFERENCES games(id),   -- NULL if prop-level
    market_key TEXT NOT NULL,               -- canonical market identifier
    line REAL NOT NULL,
    side TEXT NOT NULL,
    odds_decimal REAL NOT NULL,
    implied_prob REAL,                      -- 1/odds_decimal, vig-adjusted
    vig REAL,                               -- overround
    captured_at TEXT NOT NULL,
    source TEXT DEFAULT 'bovada'
);
```

- `odds_snapshots` can hang off either `props.id` (for prop-specific price history) or `games.id` (for game-level markets like moneyline).
- The `market_key` is a composite like `"nba.bos_lal.pts_over_27.5"` — a stable string that survives FK migrations.
- This design is **spine-native**: odds reference the game and optionally the prop, both of which live in the spine.

**Option B: Separate odds-only table (simpler, but less spine-connected)**
- Store odds entirely in `odds_snapshots` with `market_key` only, decoupled from `props`. Simpler to implement but harder to join for EV/CLV computation.
- **Recommend Option A** — the extra FK columns are cheap and make EV/CLV queries trivial: `props.implied_prob - model_prob`.

**M6 can build against Option A immediately:**
1. Add `odds_decimal` + `implied_prob` to `props` (additive ALTER).
2. Create `odds_snapshots` with `game_id` referencing the current `prop_games.id` temporarily.
3. During migration, `prop_games.id` → `games.id` mapping handles the FK switch via the backfill query.

---

## 4. Migration Steps (Ordered, Reversible)

### Pre-migration checklist
- [ ] Confirm `backend/data/picks.db.bak-20260624` exists (verified — 10,393 prop_results)
- [ ] Run `sqlite3 picks.db "PRAGMA integrity_check"` → must return `ok`
- [ ] Stop the cron pipeline during cutover (Step 4)
- [ ] Have rollback SQL ready for each step (included below)

---

### Step 1: Create `games` table (additive, zero risk)

```sql
CREATE TABLE games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league TEXT NOT NULL,
    season INTEGER NOT NULL,
    season_type TEXT DEFAULT 'REG',
    game_date TEXT NOT NULL,
    game_datetime TEXT,
    espn_event_id TEXT UNIQUE,
    home_team_abbrev TEXT NOT NULL,
    away_team_abbrev TEXT NOT NULL,
    home_score INTEGER,
    away_score INTEGER,
    home_linescores TEXT,
    away_linescores TEXT,
    status TEXT,
    status_detail TEXT,
    period INTEGER,
    clock TEXT,
    source TEXT DEFAULT 'espn',
    captured_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE INDEX idx_games_league_date ON games(league, game_date);
CREATE INDEX idx_games_espn ON games(espn_event_id);
```

**Verify:** `SELECT COUNT(*) FROM games` → 0 (empty, ready for backfill).  
**Rollback:** `DROP TABLE games` (no dependencies yet).

---

### Step 2: Create `game_player_stats` table (additive, zero risk)

```sql
CREATE TABLE game_player_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id),
    player_id INTEGER REFERENCES players(id),
    espn_player_id TEXT,
    team_abbrev TEXT NOT NULL,
    league TEXT NOT NULL,
    position TEXT,
    starter INTEGER DEFAULT 0,
    minutes TEXT,
    -- NBA
    pts INTEGER, reb INTEGER, ast INTEGER, stl INTEGER, blk INTEGER, tov INTEGER,
    fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER,
    ftm INTEGER, fta INTEGER,
    oreb INTEGER, dreb INTEGER, pf INTEGER, plus_minus INTEGER,
    -- NFL
    pass_cmp INTEGER, pass_att INTEGER, pass_yds INTEGER,
    pass_td INTEGER, pass_int INTEGER,
    rush_att INTEGER, rush_yds INTEGER, rush_td INTEGER,
    rec_tgt INTEGER, rec_rec INTEGER, rec_yds INTEGER, rec_td INTEGER,
    fum_lost INTEGER, sacks INTEGER, sack_yds INTEGER,
    -- NHL
    goals INTEGER, assists INTEGER, points INTEGER,
    shots INTEGER, plus_minus_nhl INTEGER, pim INTEGER,
    ppg INTEGER, ppp INTEGER, shg INTEGER,
    toi TEXT, faceoff_pct REAL,
    hits INTEGER, blocks INTEGER, giveaways INTEGER, takeaways INTEGER,
    -- Metadata
    source TEXT DEFAULT 'espn',
    captured_at TEXT NOT NULL
);
CREATE INDEX idx_gps_game ON game_player_stats(game_id);
CREATE INDEX idx_gps_player ON game_player_stats(player_id);
CREATE INDEX idx_gps_espn ON game_player_stats(espn_player_id);
```

**Verify:** `SELECT COUNT(*) FROM game_player_stats` → 0.  
**Rollback:** `DROP TABLE game_player_stats`.

---

### Step 3: Backfill `games` from `prop_games` + ESPN (additive, read-only on old tables)

```sql
-- 3a: Seed games from prop_games (props-enabled games we already have)
INSERT INTO games (league, season, game_date, espn_event_id,
                   home_team_abbrev, away_team_abbrev,
                   home_score, away_score,
                   status, source, captured_at)
SELECT
    pg.league,
    CAST(substr(pg.date, 1, 4) AS INTEGER) AS season,
    pg.date,
    pg.espn_event_id,
    pg.home,
    pg.away,
    pg.final_home,
    pg.final_away,
    CASE WHEN pg.final_home IS NOT NULL THEN 'post' ELSE 'pre' END,
    'prop_games',
    datetime('now')
FROM prop_games pg
WHERE pg.espn_event_id IS NOT NULL
  AND pg.espn_event_id NOT IN (SELECT espn_event_id FROM games);
```

**Verify:** 
- `SELECT COUNT(*) FROM games` → should equal `SELECT COUNT(*) FROM prop_games WHERE espn_event_id IS NOT NULL`
- `SELECT COUNT(*) FROM games WHERE espn_event_id IS NULL` → 0

**Rollback:** `DELETE FROM games WHERE source = 'prop_games'` (re-runnable — Step 3 uses `NOT IN` guard).

**3b (optional, deferred):** Backfill additional games from ESPN history (games without props). This uses the day-by-day scoreboard approach from OFFSEASON-DATA-DESIGN.md §2. Run as a separate offline script, not during the cutover. Only games that will have `game_player_stats` or `team_game_stats` rows need to be in `games`.

---

### Step 4: Add FK columns to child tables (additive, zero data loss)

```sql
-- team_game_stats
ALTER TABLE team_game_stats ADD COLUMN game_id_fk INTEGER REFERENCES games(id);

-- game_context
ALTER TABLE game_context ADD COLUMN game_id_fk INTEGER REFERENCES games(id);

-- scoring_plays
ALTER TABLE scoring_plays ADD COLUMN game_id_fk INTEGER REFERENCES games(id);
```

**Backfill the FK columns:**
```sql
UPDATE team_game_stats SET game_id_fk = (
    SELECT g.id FROM games g WHERE g.espn_event_id = team_game_stats.game_id
) WHERE game_id_fk IS NULL;

UPDATE game_context SET game_id_fk = (
    SELECT g.id FROM games g WHERE g.espn_event_id = game_context.game_id
) WHERE game_id_fk IS NULL;

UPDATE scoring_plays SET game_id_fk = (
    SELECT g.id FROM games g WHERE g.espn_event_id = scoring_plays.game_id
) WHERE game_id_fk IS NULL;
```

**Verify:**
```sql
-- Check resolution rate
SELECT COUNT(*) AS total,
       SUM(CASE WHEN game_id_fk IS NOT NULL THEN 1 ELSE 0 END) AS resolved,
       SUM(CASE WHEN game_id_fk IS NULL THEN 1 ELSE 0 END) AS unresolved
FROM team_game_stats;
-- Unresolved rows are games not yet in the `games` table (no prop_games row, no backfill yet)
```

**Rollback:** The old `game_id` column (ESPN string) is untouched — all existing queries still work. `ALTER TABLE … DROP COLUMN game_id_fk` if needed.

---

### Step 5: Dual-write period (new ingest writes to both old + new tables)

**Duration:** 1–2 days of cron cycles.

- **`props` ingest** (`ingest_props.py` / `bovada_scraper.py`): Continue writing to `prop_games` + `props` as today. Add a parallel INSERT to `games` (with `espn_event_id` dedup) and link `props.game_id` to the new `games.id` once the FK switch happens.
- **Team stats ingest** (`backfill_team_stats.py`): Continue writing to `team_game_stats` with the existing `game_id` (ESPN string). Also populate `game_id_fk` from the `games` lookup on each upsert.
- **Player stats ingest** (ingest_*.py): Continue writing to `player_stats`. New ingest scripts for `game_player_stats` run in parallel (additive — new table, no conflict).

**Verify:** End of dual-write period:
```sql
-- Check games coverage: every prop_games row has a games row
SELECT COUNT(*) FROM prop_games pg
LEFT JOIN games g ON g.espn_event_id = pg.espn_event_id
WHERE g.id IS NULL;
-- Should be 0.

-- Check FK resolution on team_game_stats
SELECT COUNT(*) FROM team_game_stats WHERE game_id_fk IS NULL;
-- Should be 0 or close to 0 (only very old games not in `games`).
```

---

### Step 6: Cutover API reads to new tables

Update `sports_service.py` to read from new tables. The changes are:

| Endpoint | Current Query | New Query |
|----------|--------------|-----------|
| `/api/{league}/games` (boxscore team stats) | `SELECT * FROM team_game_stats WHERE league=? AND game_id=?` | Same query — use `game_id_fk` or keep string `game_id` (both work) |
| `/player/{id}/stats` (all leagues) | `SELECT * FROM player_stats WHERE league=? AND player_id=?` | `SELECT * FROM game_player_stats WHERE player_id=?` with GROUP BY for aggregates, OR keep reading `player_stats` as a materialized cache |
| `/props/*` (all prop endpoints) | `JOIN prop_games pg ON pg.id = p.game_id` | `JOIN games g ON g.id = p.game_id` (after Step 7 FK switch) |
| `/api/{league}/strength` | `strength_snap` | Unchanged |

**Implementation strategy:** Add new query functions alongside old ones, gated by a feature flag or config switch. This allows A/B testing and instant rollback.

**Verify (per endpoint):**
```bash
curl -s http://127.0.0.1:8100/api/nba/games | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d))"
curl -s http://127.0.0.1:8100/player/123/stats | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('player_name'))"
curl -s http://127.0.0.1:8100/props/slate | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d))"
```
Compare old vs new output for equivalence.

**Rollback:** Flip the feature flag back. All old tables and queries are intact.

---

### Step 7: Migrate `props.game_id` FK (the critical step)

This is the **highest-risk step** because `props` is the most-queried table. Perform during a cron quiet period.

```sql
-- 7a: Backfill a temp column
ALTER TABLE props ADD COLUMN game_id_new INTEGER REFERENCES games(id);

UPDATE props SET game_id_new = (
    SELECT g.id FROM games g
    JOIN prop_games pg ON pg.espn_event_id = g.espn_event_id
    WHERE pg.id = props.game_id
);

-- 7b: Verify completeness
SELECT COUNT(*) FROM props WHERE game_id_new IS NULL;
-- Must be 0.

-- 7c: Swap columns (in a transaction)
BEGIN;
ALTER TABLE props RENAME COLUMN game_id TO game_id_old;
ALTER TABLE props RENAME COLUMN game_id_new TO game_id;
COMMIT;

-- 7d: Drop old column (optional, defer)
-- ALTER TABLE props DROP COLUMN game_id_old;  -- SQLite can't DROP COLUMN easily; just leave it.
```

**Verify:**
```sql
-- Every prop references a valid game
SELECT COUNT(*) FROM props p LEFT JOIN games g ON g.id = p.game_id WHERE g.id IS NULL;
-- Must be 0.

-- Every prop still has a player
SELECT COUNT(*) FROM props WHERE player_id IS NULL;
-- Must be 0.

-- Spot-check: pick a prop, verify its game_id resolves to the same espn_event_id
SELECT p.id, p.game_id, g.espn_event_id, g.home_team_abbrev, g.away_team_abbrev
FROM props p JOIN games g ON g.id = p.game_id LIMIT 5;
```

**Rollback:**
```sql
-- Restore old game_id from game_id_old (if not dropped)
UPDATE props SET game_id = game_id_old;
```
Or restore from backup.

---

### Step 8: Retire old tables + columns (defer — CTO confirms)

**Do NOT execute without CTO approval.** These are destructive.

| Action | Risk | Verification |
|--------|------|-------------|
| `DROP TABLE prop_games` | Medium — any un-migrated script that writes to it will break | `grep -rn "prop_games" backend/` shows zero writers |
| `DROP TABLE player_stats` (old) | Medium — API may still read it | Confirm all API reads are cut over to new tables |
| `DROP TABLE player_stats_new` | Low — orphan, no code references | `grep -rn "player_stats_new" backend/` returns nothing |
| Drop `game_id_old` from `props` | Low — just cleanup | FK is on `game_id` column now |

**Safe deferral:** The old tables can coexist indefinitely. SQLite handles dozens of tables fine. Clean up after 2+ weeks of stable operation on the new spine.

---

## 5. Identity Discipline — Name-String Joins to Eliminate

AGENTS §7: "Resolve identity BEFORE you integrate sources. Join on stable IDs, never on display strings."

### 5.1 Current name-string joins (found in `sports_service.py`)

| Location | Query | Problem |
|----------|-------|---------|
| Line 774, 780 | `SELECT * FROM player_stats WHERE name_norm=?` (MLB fallback) | Joins on normalized name when `player_id` is NULL. Silently drops spelling mismatches. |
| Line 832 | `SELECT * FROM player_stats WHERE name_norm=?` (NFL fallback) | Same — `player_id` should always be available from nflverse (has GSIS ID). |
| Line 888 | `SELECT * FROM player_stats WHERE name_norm=?` (NBA fallback) | Same — hoopR's `athlete_id` should resolve to `players.nba_id`. |
| Line 942 | `SELECT * FROM player_stats WHERE name_norm=?` (NHL fallback) | Same — nhle.com `id` should resolve to `players.nhl_id`. |
| Line 994 | `SELECT id FROM players WHERE name=? AND league=?` | Direct name match for identity resolution in `link_prop_games.py`. |
| Line 1003 | `...WHERE LOWER(REPLACE(name,'.','')) LIKE ? AND UPPER(team)=?` | Fuzzy match — designed as a fallback but silently creates name-only rows. |

### 5.2 Fix strategy

The root cause is that `player_stats` (and the new `game_player_stats`) get rows where `player_id` is NULL because the identity crosswalk hasn't been established at ingest time. The fix is **upstream**:

1. **At ingest time** (in `ingest_*.py`), resolve the source native ID → `players.id` BEFORE writing the stats row. If unresolved, write to `unresolved_players` queue instead of inserting a NULL `player_id`.
2. **Drop the name-string fallback queries** (lines 774–942) once `player_id` coverage reaches >95%.
3. **Replace `players.name=?` lookup** (line 994) with `players.espn_id=?` or `players.{league}_id=?` — resolve by ID, not name.
4. **Keep the fuzzy match** (line 1003) only as a manual review queue trigger, not an automated path.

**Target:** `game_player_stats.player_id` should be NOT NULL for ≥95% of rows. The remaining ≤5% go to `unresolved_players` for manual resolution.

---

## 6. Risk Register

| Risk | Impact | Likelihood | Mitigation | Step |
|------|--------|-----------|------------|------|
| **Live DB corruption** from a bad ALTER/UPDATE | HIGH — production goes down | LOW — all Steps 1–4 are additive (CREATE/INSERT/ALTER ADD COLUMN), no DROP/DELETE | Full backup before starting. Every step has a rollback. Steps 1–4 are zero-risk (non-destructive). | All |
| **`props.game_id` FK migration breaks prop queries** | HIGH — the main product feature | MEDIUM — FK swap is tricky | Do in a quiet period. Verify with `SELECT COUNT(*)` equivalence checks before/after. Keep `game_id_old` column as rollback. | Step 7 |
| **`espn_event_id` mismatch between `prop_games` and `games` backfill** | MEDIUM — orphan rows | LOW — `espn_event_id` is UNIQUE in `prop_games` and seeded directly | Verify with `LEFT JOIN … WHERE g.id IS NULL` after backfill. | Step 3 |
| **Dual-write drift** (new ingest writes to old tables but misses new ones) | MEDIUM — data gap | MEDIUM — requires discipline during Step 5 | Monitor with `COUNT(*)` comparisons daily during dual-write. | Step 5 |
| **Name-string joins silently drop players** | MEDIUM — coverage <95% | HIGH — already happening today (aggravated by offseason data gap) | Eliminate name-string fallbacks after `player_id` coverage confirmed ≥95%. Use `unresolved_players` queue for the rest. | §5, Phase 2 |
| **`player_stats_new` confusion** | LOW — orphan table | LOW — no code references it | Drop during cleanup. Document in migration script. | Step 8 |
| **API cutover breaks frontend** | HIGH — user-facing | LOW — feature-flag gated, old queries preserved | A/B test with feature flag. Verify every endpoint response shape matches. | Step 6 |
| **Cron pipeline runs during migration** | MEDIUM — concurrent writes | MEDIUM — cron is every 30 min | Stop cron during Step 7 (the only write-sensitive step). Steps 1–4 are safe with cron running. | Step 7 |
| **DB file size bloat** from additive steps | LOW — SQLite handles it | MEDIUM — each `ALTER TABLE ADD COLUMN` in SQLite recreates the table | Run `VACUUM` after migration complete. Do NOT `VACUUM` during migration. | Post-Step 8 |

---

## Appendix A: Rollback Kit (emergency)

If the migration goes wrong at any step, the fastest rollback:

```bash
# 1. Stop the backend + cron
docker compose stop backend
# 2. Restore from backup
cp backend/data/picks.db.bak-20260624 backend/data/picks.db
# 3. Restart
docker compose start backend
```

This is why Step 1 says "confirm backup exists." The backup is the ultimate safety net.

---

## Appendix B: Migration Script Template

The migration should be a single Python script `scripts/migrate_to_spine.py` that:
1. Takes `--dry-run` flag (print SQL, don't execute)
2. Takes `--step N` to run a single step
3. Prints row counts before/after each step
4. Has `--rollback-to-step N` to reverse
5. Logs everything to `logs/migration_YYYYMMDD_HHMMSS.log`

This is NOT to be written now (M2-impl is read-only design). The script is the implementation deliverable for whoever executes the migration.

---

## Appendix C: Verification Commands (run after each step)

```bash
# Step 1-2: Tables exist
sqlite3 backend/data/picks.db ".tables"

# Step 3: Game count
sqlite3 backend/data/picks.db "SELECT COUNT(*) AS games_count FROM games"

# Step 4: FK resolution rate
sqlite3 backend/data/picks.db "SELECT COUNT(*) AS unresolved FROM team_game_stats WHERE game_id_fk IS NULL"

# Step 7: Prop FK integrity
sqlite3 backend/data/picks.db "SELECT COUNT(*) AS orphan_props FROM props p LEFT JOIN games g ON g.id = p.game_id WHERE g.id IS NULL"

# All steps: Integrity check
sqlite3 backend/data/picks.db "PRAGMA integrity_check"
```
