# OFFSEASON-DATA-DESIGN.md — Historical / Offseason Data Recon & Schema Proposal

**Date:** 2026-06-24  
**Author:** reasonix (deepseek-v4-pro)  
**Task:** M1 from CONTEXT-2026-06-24 master checklist  
**Status:** READ-ONLY research complete — no code/DB changes made

---

## 1. Problem Statement

NBA, NHL, and NFL seasons have ended (as of June 2026). The `player_stats` table is sparse:
- **NBA:** 525 players (only the hoopR 2023 season ingested)
- **NFL:** 612 players (2024 season only)
- **NHL:** 879 players (current-season-only from nhle.com)

Our app currently relies on live ESPN data + Bovada props as the de-facto source of truth. During the ~9-month offseason for these leagues, we have no data to show — the app is blind.

This document inventories every viable data source for historical/offseason team + player + game + boxscore data, verifies them with live curls, and proposes a storage schema where **games/teams/players are the parent entities** and props hang off them (not the reverse).

---

## 2. Per-League Source Table

### 2.1 NBA

| Source | Type | Seasons Available | What It Gives | Rate-Limit / IP Notes |
|--------|------|-------------------|---------------|----------------------|
| **ESPN hidden API** (`site.api.espn.com`) | Live API (free, no auth) | Historical ≥ 2023; full 2023-24 + 2024-25 seasons accessible | Scoreboard (game list per day), boxscore (per-player stats with named columns), team roster, standings | **No rate limiting observed.** Generic User-Agent works. Polite 1 req/sec recommended. 100-event cap per scoreboard call → iterate day-by-day. |
| **hoopR-data** (`sportsdataverse/hoopR-data` GitHub) | Static Parquet files | 2002–2023 (22 seasons) | Player box scores: 57 columns including game_id, athlete_id, athlete_display_name, team, minutes, PTS, REB, AST, STL, BLK, TOV, FG, 3PT, FT, +/- | No rate limits (GitHub raw). **2024 and 2025 NOT yet published** — pipeline appears stale. |
| **stats.nba.com** | Live API (aggressive IP blocking) | N/A | — | **BLOCKED** on all datacenter IPs (AGENTS §7). Do NOT propose. |

#### ESPN NBA Boxscore — Verified Payload

```
Endpoint: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=401769991
Stat names: ['MIN', 'PTS', 'FG', '3PT', 'FT', 'REB', 'AST', 'TO', 'STL', 'BLK', 'OREB', 'DREB', 'PF', '+/-']
Sample row: Isaiah Hartenstein id=4222252 → ['25', '8', '4-4', '0-0', '0-0', '6', '0', '1', '0', '0', '2', '4', '4', '-17']
```

**Key finding:** ESPN's boxscore endpoint returns **named stat columns** for NBA — clean, parsable, no reverse-engineering needed. The `athlete.id` field is the ESPN player ID, which maps to our `players.espn_id` for identity resolution.

#### ESPN NBA Scoreboard — Verified for Historical Query

```
Endpoint: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20250515
Result: 1 event (OKC @ DEN) — playoff game from mid-May 2025
Endpoint: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20230601
Result: 1 event (MIA @ DEN) — NBA Finals Game 1 from 2023
```

**ESPN retains scoreboard data ≥2 years back.** For full-season ingestion, iterate day-by-day (~170 game-days for an 82-game season × 2 req/day for scoreboard + boxscore = ~340 requests per season at 1/sec = 6 minutes per season).

#### hoopR-data — Verified Available Seasons

```
GitHub: sportsdataverse/hoopR-data/nba/player_box/parquet/
Seasons: player_box_2002.parquet through player_box_2023.parquet (22 files)
NOT available: player_box_2024.parquet, player_box_2025.parquet
player_box_2023 columns (57): game_id, season, season_type, game_date, athlete_id,
  athlete_display_name, team_id, team_name, minutes, field_goals_made,
  field_goals_attempted, three_point_field_goals_made, ... points, rebounds,
  assists, steals, blocks, turnovers, plus_minus_points
Sample: Draymond Green (athlete_id=6589) — game_date range 2022-10-18 to 2023-04-02
```

---

### 2.2 NFL

| Source | Type | Seasons Available | What It Gives | Rate-Limit / IP Notes |
|--------|------|-------------------|---------------|----------------------|
| **nflverse / nfl_data_py** | Static CSV/Parquet via GitHub Releases | 1999–2024 (26 seasons) | Weekly player stats (70+ columns: passing, rushing, receiving, EPA, fantasy), schedules, rosters, play-by-play, snap counts | No rate limits. Python package `nfl_data_py` wraps downloads. **2024 season (completed Feb 2025) IS available.** |
| **ESPN hidden API** | Live API | Historical ≥ 2024-09 | Scoreboard, boxscore (per-player stats — bare arrays, no names), team roster | No rate limiting. NFL boxscore stat labels ARE present (e.g., "Passing", "Rushing") but individual stat names are empty strings. Known stat order per position group. |

#### nflverse — Verified Coverage

```
Python: nfl_data_py.import_weekly_data([2024]) → 5,597 rows (full 2024 season)
         nfl_data_py.import_weekly_data([2025]) → HTTP 404 (season hasn't started)
         nfl_data_py.import_schedules([2024]) → 285 rows
         nfl_data_py.import_schedules([2025]) → 285 rows (upcoming season schedule available)

nflverse-data GitHub releases — tags available:
  player_stats, stats_player, pbp, schedules, rosters, snap_counts,
  nextgen_stats, pfr_advstats, depth_charts, injuries, trades, contracts, combine
```

#### ESPN NFL Boxscore — Verified Payload

```
Endpoint: https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=401671854
Player stat groups (labeled): Passing, Rushing, Receiving, Fumbles, Defensive, Kicking, Returns
Sample QB row: Patrick Mahomes id=3139477 → ['19/38', '159', '4.2', '2', '0', '0-0', '55.4', '78.7']
  (order: CMP/ATT, YDS, AVG, TD, INT, SACKS, QBR, RTG)
```

**Key finding:** NFL is the best-covered league for historical data. nflverse/nfl_data_py gives us EVERYTHING from 1999–2024 in one Python call. ESPN is only needed as a supplement for identity resolution (player_id → espn_id crosswalk) and for the 2025 schedule.

---

### 2.3 NHL

| Source | Type | Seasons Available | What It Gives | Rate-Limit / IP Notes |
|--------|------|-------------------|---------------|----------------------|
| **nhle.com API** (`api-web.nhle.com`) | Live API (free, no auth) | Full career stats per player (verified back to 2008-09 for McDavid, 36 seasons) | Roster per team, player landing page (season totals: G, A, P, +/-, SOG, PIM, TOI, PP/SH stats, faceoff%), current team | **Gentle rate limit:** 0.15s delay works (32 roster calls + ~700 player calls = ~2 min per full ingest). No IP blocking observed. |
| **ESPN hidden API** | Live API | Historical ≥ 2023 | Scoreboard, boxscore (per-player stats — bare arrays), team roster | No rate limiting. NHL boxscore stat names are empty but values are present in known order. |
| Published NHL data release | — | — | **None found.** GitHub search for "nhl player stats parquet csv" returned no major data releases comparable to nflverse/hoopR. | N/A |

#### nhle.com — Verified Payload

```
Roster endpoint: https://api-web.nhle.com/v1/roster/{TEAM}/current
  Returns forwards, defensemen, goalies with player id, firstName, lastName, positionCode
  (COL failed on test — API may be intermittently rate-limited or COL roster is empty post-playoffs)

Player landing: https://api-web.nhle.com/v1/player/8478402/landing (Connor McDavid)
  firstName.default: Connor, lastName.default: McDavid
  position: C, currentTeamAbbrev: EDM
  seasonTotals[]: 36 entries from 20082009 to 20252026
  Each entry: season, gamesPlayed, goals, assists, points, shots, shootingPctg,
              plusMinus, pim, powerPlayGoals, powerPlayPoints, shorthandedGoals,
              avgToi, faceoffWinningPctg
```

**Key finding:** nhle.com gives full career stats per player, but requires 1 API call per player (no bulk endpoint). With ~700 rostered NHL players and 0.15s delay, a full ingest takes ~2 minutes. This is perfectly fine for an offline cron job. `seasonTotals` returns ALL seasons — not just current — making it suitable for historical backfill.

#### ESPN NHL Boxscore — Verified Payload

```
Endpoint: https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary?event=401769953
Sample skater: Sebastian Aho id=3904173 → 
  ['0', '7', '0', '2', '19:44', '3:40', '2:15', '13:49', '23', '0', '3', '0', '0', '1', '0', '10', '6', '62.5', '1', '0', '0']
  (order: G, A, P, SOG, TOI, PP TOI, SH TOI, EV TOI, shifts, PIM, hits, blocks, giveaways, takeaways, FOW, FOL, FO%, ...)
```

---

### 2.4 Cross-Source Identity Mapping

All sources provide their own native player IDs. The identity spine (AGENTS §7) requires a crosswalk:

| Source | Native ID Field | Maps To | How to Crosswalk |
|--------|----------------|---------|-----------------|
| ESPN | `athlete.id` (integer) | `players.espn_id` | Direct — ESPN is our canonical identity provider |
| hoopR | `athlete_id` (integer) | `players.nba_id` | Same as ESPN's internal NBA player ID in most cases; verify match rate |
| nflverse | `player_id` (string, GSIS ID) | `players.nfl_gsis_id` | nfl_data_py includes `player_id` (GSIS). Join on this. |
| nhle.com | `id` (integer) | `players.nhl_id` | Direct — nhle.com player ID is the canonical NHL identity |

**Crosswalk strategy:** On first ingest, store each source's native ID. The `players` table already has `espn_id`, `nba_id`, `nfl_gsis_id`, `nhl_id` columns. For hoopR, the `athlete_id` typically matches ESPN's internal ID — verify by sampling before assuming.

---

## 3. Proposed Storage Schema

### 3.1 Design Principle: Game → Team → Player Spine (Props Hang Off)

The current schema is **props-centric** — `prop_games` is thin, `props` is the richest table, and game/team data is scattered across `team_game_stats`, `scoring_plays`, and `game_context`. The redesign inverts this:

```
games ──────→ game_teams ──────→ game_player_stats     ←── the STAT SPINE
  │                │                      │
  │                │                      │ (player_id)
  │                │                      ↓
  │                │              players (canonical identity)
  │                │                      ↑
  │                │                      │ (player_id)
  │                │              props ──→ prop_results    ←── hang OFF the spine
  │                │
  │                ↓
  │           team_stats (season aggregates)
  ↓
game_context (venue, attendance, officials)
```

**Props are a child of players, not the other way around.** A prop references `(game_id, player_id)` — both of which exist independently in the spine. This means:
- Games/teams/players can be ingested WITHOUT any prop data present
- Props can be captured LATER and linked by game+player foreign keys
- The app can show player stats even when no props are available for a game

### 3.2 New Tables

#### `games` — canonical game spine (replaces `prop_games` as the primary game table)

```sql
CREATE TABLE games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league TEXT NOT NULL,            -- 'nba', 'nfl', 'nhl', 'mlb'
    season INTEGER NOT NULL,         -- e.g., 2025 for the 2024-25 season
    season_type TEXT DEFAULT 'REG',  -- 'REG', 'POST', 'PRE'
    game_date TEXT NOT NULL,         -- 'YYYY-MM-DD'
    game_datetime TEXT,              -- ISO-8601
    espn_event_id TEXT UNIQUE,       -- ESPN game ID (the canonical cross-source key)

    -- Teams
    home_team_abbrev TEXT NOT NULL,
    away_team_abbrev TEXT NOT NULL,

    -- Result
    home_score INTEGER,
    away_score INTEGER,
    home_linescores TEXT,            -- JSON array e.g. '["28","33","21","25"]'
    away_linescores TEXT,
    status TEXT,                     -- 'pre', 'in', 'post'
    status_detail TEXT,              -- 'Final', 'Final/OT', etc.
    period INTEGER,                  -- regulation periods completed
    clock TEXT,                      -- game clock at last update

    -- Metadata
    source TEXT DEFAULT 'espn',      -- 'espn', 'nflverse', 'nhle'
    captured_at TEXT NOT NULL,       -- when we ingested it
    updated_at TEXT
);
```

#### `game_player_stats` — per-game, per-player boxscore rows (the heart of the spine)

```sql
CREATE TABLE game_player_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id),
    player_id INTEGER REFERENCES players(id),  -- NULL until identity resolved
    espn_player_id TEXT,                         -- raw ESPN athlete ID for crosswalk
    team_abbrev TEXT NOT NULL,
    league TEXT NOT NULL,

    -- Position / role
    position TEXT,                   -- G, F, C (NBA); QB, WR, RB (NFL); C, LW, D (NHL)
    starter INTEGER DEFAULT 0,       -- 1 if started
    minutes TEXT,                    -- playing time (e.g., "35:12" or "19:44")

    -- NBA core stats
    pts INTEGER, reb INTEGER, ast INTEGER,
    stl INTEGER, blk INTEGER, tov INTEGER,
    fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER,
    ftm INTEGER, fta INTEGER,
    oreb INTEGER, dreb INTEGER, pf INTEGER, plus_minus INTEGER,

    -- NFL core stats
    pass_cmp INTEGER, pass_att INTEGER, pass_yds INTEGER,
    pass_td INTEGER, pass_int INTEGER,
    rush_att INTEGER, rush_yds INTEGER, rush_td INTEGER,
    rec_tgt INTEGER, rec_rec INTEGER, rec_yds INTEGER, rec_td INTEGER,
    fum_lost INTEGER, sacks INTEGER, sack_yds INTEGER,

    -- NHL core stats
    goals INTEGER, assists INTEGER, points INTEGER,
    shots INTEGER, plus_minus_nhl INTEGER, pim INTEGER,
    ppg INTEGER, ppp INTEGER, shg INTEGER,
    toi TEXT, faceoff_pct REAL,
    hits INTEGER, blocks INTEGER, giveaways INTEGER, takeaways INTEGER,

    -- Source tracking
    source TEXT DEFAULT 'espn',
    captured_at TEXT NOT NULL
);

CREATE INDEX idx_game_player_stats_game ON game_player_stats(game_id);
CREATE INDEX idx_game_player_stats_player ON game_player_stats(player_id);
CREATE INDEX idx_game_player_stats_espn ON game_player_stats(espn_player_id);
```

**Why per-game rows instead of per-season aggregates?** Per-game data enables:
- Game logs (player performance over time)
- Opponent-specific splits
- Hot/cold streak detection
- Boxscore reconstruction for any past game
- Settlement of historical props

Per-season aggregates can be a **VIEW** or materialized cache querying this table.

#### `team_game_stats` — per-game team totals (already exists, stabilize)

```sql
-- Keep existing team_game_stats table but add FK to games.id
-- Add: game_id INTEGER REFERENCES games(id)
-- The existing columns cover NBA/NFL/NHL team stats adequately
```

#### `player_stats` — season-level aggregates (keep but refactor)

The current `player_stats` table should be **demoted to a materialized cache** derived from `game_player_stats`, not the primary source. However, to avoid breaking the existing API, keep it as-is during migration and populate it from a rollup query after ingesting `game_player_stats`.

### 3.3 How Props Hang Off the Spine

The existing `props` table already references `prop_games.id` and `players.id`. The new design:

```sql
-- props stays mostly the same, but game_id now references games.id
ALTER TABLE props RENAME TO props_old;  -- migration step

CREATE TABLE props (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id),      -- was prop_games.id
    player_id INTEGER REFERENCES players(id),            -- unchanged
    market TEXT NOT NULL,
    line REAL NOT NULL,
    side TEXT NOT NULL,
    source TEXT DEFAULT 'bovada',
    captured_at TEXT NOT NULL
);

-- prop_results stays the same (references props.id)
-- prop_games is DEPRECATED — its data merges into games
```

### 3.4 Migration Path (High-Level — Staged)

| Phase | Action | Risk |
|-------|--------|------|
| **Phase 0** | Backup DB (already have `picks.db.bak-20260624`) | Low |
| **Phase 1** | Create `games` and `game_player_stats` tables (additive — no DROP) | Low |
| **Phase 2** | Ingest historical data into new tables (ESPN + nflverse + nhle.com + hoopR). This is additive — current `player_stats` and `prop_games` are untouched. | Low |
| **Phase 3** | Write a migration script: populate `games` from `prop_games` + ESPN backfill, populate `player_stats` season aggregates from `game_player_stats` rollup | Medium |
| **Phase 4** | Switch API handlers to read from new tables; update `sports_service.py` endpoints | Medium |
| **Phase 5** | Drop deprecated `prop_games` + old `player_stats` columns (only after API verified stable) | High (defer until CTO confirms) |

**Key safety rule:** Phases 1–2 are strictly additive. The live API continues reading the old tables. Only when Phase 4 is verified do we cut over.

---

## 4. Ranked Recommendation

### Priority Order (by value-to-effort ratio)

| Rank | League | Source | Rationale |
|------|--------|--------|-----------|
| **1** | **NFL** | **nflverse / nfl_data_py** | One Python call gives EVERYTHING (26 seasons of weekly player stats). No rate limits. Already installed in venv. Existing `ingest_nfl.py` works — just run it for all seasons 1999–2024. Zero new infrastructure needed. |
| **2** | **NHL** | **nhle.com API** | `ingest_nhl.py` already fetches rosters + season totals. Extend to iterate `seasonTotals[]` arrays (the data is already in the response). No bulk endpoint needed — 700 players × 0.15s = 2 min. Full career stats available. |
| **3** | **NBA** | **hoopR-data (2002–2023) + ESPN (2024–2025)** | hoopR covers 22 seasons (2002–2023) in static Parquet files with 57-column granularity. For 2024–2025: ESPN day-by-day scoreboard → boxscore gives us the missing 2 seasons (~340 requests/season at 1/sec = 6 min/season). Combined, this gives 24 years of NBA data. |
| **4** | **All** | **ESPN game/team metadata** | The `games` table spine (game date, venue, attendance, officials) can be populated from ESPN's summary header for any game we already have a boxscore for — marginal cost is zero (it's in the same API response). |

### What NOT to do

- **Do NOT attempt stats.nba.com** — datacenter IPs are hard-blocked (AGENTS §7). A residential proxy is the only workaround and costs money.
- **Do NOT build per-game ingestion for NFL via ESPN** — nflverse is strictly better (more columns, no rate limits, bulk download). ESPN NFL boxscore is only useful as a supplement for identity crosswalk.
- **Do NOT write a live API caller in the request path** — the ingest→DB→serve pattern (AGENTS §7) is correct. All new data sources follow the same pattern: offline cron ingest → SQLite → FastAPI reads DB only.

---

## 5. Open Questions & Risks

1. **hoopR-data pipeline appears stale** — last season published is 2023 (2022-23 NBA). Will 2024/2025 ever be backfilled? If not, we're permanently dependent on ESPN for recent NBA.
2. **nhle.com roster endpoint failed for COL** — test with retry logic. The API may return empty during the offseason when rosters are in flux. Player landing endpoint worked fine for McDavid.
3. **ESPN scoreboard historical depth** — verified back to June 2023 (NBA Finals). How far back does it go for regular-season games? Testing a 2021 date would confirm but is not critical for our use case (we have hoopR for 2002–2023).
4. **`game_player_stats` storage size** — with 1,230 NBA games × ~20 players × 2 teams = ~49,200 rows per season. Over 24 NBA seasons = ~1.2M rows. SQLite handles this fine but `VACUUM` periodically.
5. **Cross-source player identity** — hoopR `athlete_id` may or may not match ESPN's internal IDs. Sampling needed before assuming they're the same namespace. The `espn_player_id` column in `game_player_stats` provides a fallback join path.
6. **nflverse `player_stats` vs `stats_player`** — two different releases cover the same seasons. `stats_player` appears to be end-of-season aggregates while `player_stats` is weekly. We probably want weekly (for game logs) but both could be sources.

---

## 6. Verification Evidence

All endpoints below were curled live on 2026-06-24 from this server (Contabo, St. Louis):

| Endpoint | Verified | Result |
|----------|----------|--------|
| ESPN NBA scoreboard (2025-05-15) | ✅ | 1 event (OKC @ DEN playoffs) |
| ESPN NBA scoreboard (2023-06-01) | ✅ | 1 event (MIA @ DEN Finals) |
| ESPN NBA boxscore (401769991) | ✅ | 14 named stat columns, per-player stats |
| ESPN NBA teams | ✅ | 30 teams with IDs |
| ESPN NFL scoreboard (2024-12-15) | ✅ | 13 events |
| ESPN NFL scoreboard (2024-09-08) | ✅ | 13 events |
| ESPN NFL boxscore (401671854) | ✅ | Labeled stat groups, per-player stats |
| ESPN NFL teams | ✅ | 32 teams with IDs |
| ESPN NHL scoreboard (2025-05-15) | ✅ | 2 events |
| ESPN NHL boxscore (401769953) | ✅ | Per-player stats (bare arrays) |
| ESPN NHL teams | ✅ | 32 teams with IDs |
| hoopR-data GitHub | ✅ | 22 Parquet files (2002–2023) |
| hoopR 2024/2025 | ❌ | 404 — not published |
| nflverse releases | ✅ | 24 tags including player_stats, pbp, schedules |
| nfl_data_py 2024 season | ✅ | 5,597 rows |
| nfl_data_py 2025 season | ✅ | 404 (expected — season not started) |
| nflverse player_stats CSV | ✅ | 70+ columns, GSIS player_id |
| nhle.com player landing (McDavid) | ✅ | 36 seasons of career stats |
| nhle.com roster (COL) | ⚠️ | Empty response (offseason roster flux) |
