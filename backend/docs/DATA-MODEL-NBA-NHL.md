# DATA-MODEL-NBA-NHL.md — Schema Proposal

> **Date:** 2026-06-09  
> **Scope:** NBA + NHL only. Backend-first. Follows the `_snapshot_strength` pattern from `sports_service.py`.

## ESPN Data Availability

| Data | NBA | NHL | How |
|------|-----|-----|-----|
| **Rosters** (player_id, name, jersey, position) | ✅ | ✅ | `site.api.espn.com/.../teams/{team}/roster` |
| **Team per-game stats** (aggregates) | ✅ 26 fields | ✅ 14 fields | `boxscore.teams[].statistics[]` |
| **Scoring plays** (period, clock, scorer, assists) | ✅ | ✅ | `plays[]` with `scoringPlay=true` |
| **Game context** (venue, attendance, officials) | ✅ | ✅ | `gameInfo` |
| **Season standings** | ✅ | ✅ | Already collected (`strength_snap`) |
| **Per-player boxscore** (pts/reb/ast, G/A/PIM) | ❌ Empty | ❌ Empty | `boxscore.players[].athletes[]` is `[]` for completed games |

**⚠️ Player boxscore limitation:** ESPN's public API only populates per-player stats for *live* games. Once a game finishes, the `athletes[]` arrays are emptied. For historical per-player stats, we would need a different source (nba_api, NHL API, scraping) or capture them live. This is documented so the trading side knows per-player priors are not available from ESPN alone.

---

## Proposed Tables

All tables live in the existing `picks.db` (alongside `predictions` and `strength_snap`).  
Naming convention: `{domain}_snap` for snapshot-style tables.

### 1. `roster_snap` — Player Roster Per Team

**Grain:** `(league, team_abbrev, player_id, captured_at)` — one row per player per snapshot.  
**ESPN source:** `site.api.espn.com/.../teams/{abbrev}/roster` (via `espn_client.roster()`)

```sql
CREATE TABLE IF NOT EXISTS roster_snap(
  captured_at   TEXT NOT NULL,   -- ISO-8601 UTC
  league        TEXT NOT NULL,   -- 'nba' | 'nhl'
  team_abbrev   TEXT NOT NULL,   -- 'SA', 'NY', 'VGK', 'CAR', ...
  player_id     TEXT NOT NULL,   -- ESPN athlete ID (string)
  name          TEXT,            -- full name
  jersey        TEXT,            -- jersey number (can be NULL)
  position      TEXT             -- 'G', 'F', 'C' (NBA) / 'C', 'LW', 'RW', 'D', 'G' (NHL)
);
```

**Sample (NBA, 5 rows):**
```
captured_at              | league | team | player_id | name              | jersey | position
2026-06-09T17:30:00Z     | nba    | NY   | 4277869   | Jose Alvarado     | 5      | G
2026-06-09T17:30:00Z     | nba    | NY   | 3934719   | OG Anunoby        | 8      | F
2026-06-09T17:30:00Z     | nba    | NY   | 3147657   | Mikal Bridges     | 25     | G
2026-06-09T17:30:00Z     | nba    | NY   | 3934672   | Jalen Brunson     | 11     | G
2026-06-09T17:30:00Z     | nba    | NY   | 2528426   | Jordan Clarkson   | 00     | G
```

**Sample (NHL, 5 rows):**
```
captured_at              | league | team | player_id | name              | jersey | position
2026-06-09T17:30:00Z     | nhl    | VGK  | 3025616   | Nic Dowd          | 26     | C
2026-06-09T17:30:00Z     | nhl    | VGK  | 3648002   | Jack Eichel       | 9      | C
2026-06-09T17:30:00Z     | nhl    | VGK  | 2976844   | Tomas Hertl       | 48     | C
2026-06-09T17:30:00Z     | nhl    | VGK  | 4024989   | Brett Howden      | 21     | C
2026-06-09T17:30:00Z     | nhl    | VGK  | 2563057   | William Karlsson  | 71     | C
```

---

### 2. `team_game_stats` — Per-Game Team Aggregates

**Grain:** `(league, game_id, team_abbrev)` — one row per team per game.  
**ESPN source:** `boxscore.teams[].statistics[]` from summary endpoint.

```sql
CREATE TABLE IF NOT EXISTS team_game_stats(
  league        TEXT NOT NULL,   -- 'nba' | 'nhl'
  game_id       TEXT NOT NULL,   -- ESPN event ID
  captured_at   TEXT NOT NULL,   -- when we fetched it
  team_abbrev   TEXT NOT NULL,   -- home/away
  home_away     TEXT NOT NULL,   -- 'home' | 'away'
  -- NBA fields (NULL for NHL) --
  fgm_fga       TEXT,            -- '39-84'
  fg_pct        REAL,
  tpm_tpa       TEXT,            -- '12-34' (3PM-3PA)
  tp_pct        REAL,
  ftm_fta       TEXT,            -- '25-32'
  ft_pct        REAL,
  rebounds      INTEGER,
  off_rebounds  INTEGER,
  def_rebounds  INTEGER,
  assists       INTEGER,
  steals        INTEGER,
  blocks        INTEGER,
  turnovers     INTEGER,
  fouls         INTEGER,
  pts_off_to    INTEGER,         -- points off turnovers
  fast_break_pts INTEGER,
  pts_in_paint  INTEGER,
  largest_lead  INTEGER,
  lead_changes  INTEGER,
  lead_pct      REAL,            -- percent of game led
  -- NHL fields (NULL for NBA) --
  shots         INTEGER,
  blocked_shots INTEGER,
  hits          INTEGER,
  takeaways     INTEGER,
  giveaways     INTEGER,
  faceoffs_won  INTEGER,
  faceoff_pct   REAL,
  powerplay_goals INTEGER,
  powerplay_opps  INTEGER,
  powerplay_pct REAL,
  shorthanded_goals INTEGER,
  penalties     INTEGER,
  penalty_min   INTEGER
);
```

**Sample (NBA — SA@NY, Jun 8, 5 representative columns):**
```
league | game_id   | team | home | fgm_fga | fg_pct | tpm_tpa | tp_pct | rebounds | assists | steals | blocks | turnovers
nba    | 401859965 | SA   | away | 39-84   | 46     | 12-34   | 35     | 37       | 28      | 7      | 7      | 8
nba    | 401859965 | NY   | home | 40-88   | 45     | 13-37   | 35     | 46       | 18      | 4      | 6      | 13
```

**Sample (NHL — CAR@VGK, Jun 6):**
```
league | game_id   | team | home | shots | blocked | hits | faceoffs | faceoff% | ppg | ppo | pp% | penalties | pim
nhl    | 401874173 | CAR  | away | 33    | 14      | 42   | 54       | 59.3     | 1   | 2   | 50.0| 2         | 4
nhl    | 401874173 | VGK  | home | 35    | 30      | 66   | 37       | 40.7     | 1   | 2   | 50.0| 2         | 4
```

---

### 3. `scoring_plays` — Goal/Scoring Events

**Grain:** `(league, game_id, play_id)` — one row per scoring event.  
**ESPN source:** `plays[]` from summary endpoint (filtered to `scoringPlay=true`).

```sql
CREATE TABLE IF NOT EXISTS scoring_plays(
  league        TEXT NOT NULL,
  game_id       TEXT NOT NULL,
  play_id       TEXT NOT NULL,    -- ESPN play ID
  captured_at   TEXT NOT NULL,
  period        INTEGER,
  period_disp   TEXT,             -- '1st', '2nd', '3rd', '4th', 'OT'
  clock         TEXT,             -- '10:26' (time elapsed in period for NHL; remaining for NBA)
  away_score    INTEGER,
  home_score    INTEGER,
  team_abbrev   TEXT,             -- scoring team
  scorer_name   TEXT,             -- parsed from text
  play_text     TEXT,             -- raw ESPN description
  play_type     TEXT              -- 'Goal', '3PT', 'Dunk', 'Free Throw', etc.
);
```

**Sample (NHL — CAR@VGK, 5 scoring plays):**
```
league | game_id   | play_id              | per | clock  | away | home | team | scorer            | play_text
nhl    | 401874173 | 401874173000001234   | 2   | 10:26  | 0    | 1    | VGK  | Tomas Hertl       | Tomas Hertl Goal (5) Wrist Shot, assists: Jack Eichel (18), Mitch Marner (18)
nhl    | 401874173 | 401874173000001250   | 2   | 10:42  | 0    | 2    | VGK  | Mitch Marner      | Mitch Marner Goal (8) Backhand, assists: William Karlsson (5), Shea Theodore (10)
nhl    | 401874173 | 401874173000001270   | 2   | 14:32  | 0    | 3    | VGK  | Mitch Marner      | Mitch Marner Goal (9) Backhand, assists: Brayden McNabb (7)
nhl    | 401874173 | 401874173000001290   | 2   | 16:52  | 0    | 4    | VGK  | Mitch Marner      | Mitch Marner Goal (10) Slap Shot, assists: Tomas Hertl (8)
nhl    | 401874173 | 401874173000001450   | 3   | 7:03   | 1    | 4    | CAR  | Jordan Martinook  | Jordan Martinook Goal (2) Wrist Shot, assists: Seth Jarvis (6), Logan Stankoven (4)
```

---

### 4. `game_context` — Venue, Attendance, Officials

**Grain:** `(league, game_id)` — one row per game.  
**ESPN source:** `gameInfo` + `header.competitions[0].competitors[]`.

```sql
CREATE TABLE IF NOT EXISTS game_context(
  league        TEXT NOT NULL,
  game_id       TEXT NOT NULL PRIMARY KEY,
  captured_at   TEXT NOT NULL,
  home_team     TEXT,
  away_team     TEXT,
  venue_name    TEXT,
  venue_city    TEXT,
  attendance    INTEGER,
  officials     TEXT             -- JSON array of official names
);
```

**Sample:**
```
league | game_id   | home | away | venue                | city       | attendance | officials
nba    | 401859965 | NY   | SA   | Madison Square Garden| New York   | 19812      | ["John Goble","Curtis Blair","Marc Davis","Nick Buchert"]
```

---

## Snapshot Pattern

Like `_snapshot_strength`, each table gets a companion snapshot function in `sports_service.py`:

```python
def _snapshot_rosters(league, team_abbrev, players):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT INTO roster_snap(captured_at,league,team_abbrev,player_id,name,jersey,position) "
            "VALUES(?,?,?,?,?,?,?)",
            [(now, league, team_abbrev, p["player_id"], p["name"], p["jersey"], p["position"])
             for p in players])
        con.commit()

def _snapshot_team_game_stats(league, game_id, teams):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        for t in teams:
            s = t["stats"]
            con.execute(
                "INSERT OR REPLACE INTO team_game_stats(...) VALUES(...)", [...])
        con.commit()
```

---

## What We CAN'T Get from ESPN (Yet)

- **Per-player boxscore lines** (PTS/REB/AST for NBA, G/A/PIM/SOG for NHL) — empty for completed games
- **Advanced metrics** (PER, BPM, xG, Corsi) — not in the public API
- **Play-by-play with player attribution** for non-scoring events (shots, rebounds, turnovers by player)

If the trading side needs per-player priors, we would need:
1. **Live capture** — run a collector during games (like the Kalshi orderbook pattern) to catch player stats while live
2. **Alternative source** — `nba_api` Python library or NHL's stats API for historical boxscores

---

## Implementation Plan (after approval)

1. Add `_init_db()` migrations for the 4 new tables
2. Add espn_client helpers if needed (`team_game_stats()`, `scoring_plays()` wrappers)
3. Wire snapshot functions into existing endpoints: `/boxscore` → snapshots team_game_stats + scoring_plays + game_context; `/roster` → snapshots roster_snap
4. Backfill: pull current finals (NBA: SA@NY, NHL: CAR@VGK) from all completed games in the series
5. Frontend (later): surface team stats on game cards
