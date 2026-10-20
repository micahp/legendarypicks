# NHL new-information availability audit

Audit date: `2026-10-20`.

This is a read-only inventory. No model was fitted, scored, or tuned. The counts below are emitted by [`audit_nhl_sources.py`](audit_nhl_sources.py); its output is the measurement record for every numeric claim in this report.

## Scope and target archive

The target is the normalized SBR archive in the NHL research tree. SBR records have a season label, date, and team names, but no NHL game ID. The audit joined them to the official canonical game table by date and unordered team pair, then used the canonical `game_id` for the source coverage checks. The crosswalk resolved every target row; it found one SBR home/away orientation mismatch, printed with the affected date by the script.

### SEASON COVERAGE

```text
archive_rows=5132 canonical_game_ids=5132 regular_season_games=4872 playoff_games=260
season=2018-19 sbr_games=1358 canonical_matches=1358 regular_season_games=1271 playoff_games=87 date_span=2018-10-03..2019-06-12
season=2019-20 sbr_games=1082 canonical_matches=1082 regular_season_games=1082 playoff_games=0 date_span=2019-10-02..2020-03-11
season=2020-21 sbr_games=952 canonical_matches=952 regular_season_games=868 playoff_games=84 date_span=2021-01-13..2021-07-07
season=2021-22 sbr_games=1401 canonical_matches=1401 regular_season_games=1312 playoff_games=89 date_span=2021-10-12..2022-06-26
season=2022-23 sbr_games=339 canonical_matches=339 regular_season_games=339 playoff_games=0 date_span=2022-10-11..2022-11-27
```

The archive's final season is a short slice ending November 27, 2022. Its 339 games are not a full-season holdout. The season counts above include playoffs where present; they are not all regular-season rows.

## On-disk table inventory

The file table covers the normalized target archive, the canonical game table, derived pregame features, special-teams features, and MoneyPuck team-game CSVs. The host-local DuckDB and development SQLite inventories follow. The script also emits each table's representative key columns and join key.

### Files

| Source table | Rows / coverage | Key fields and join |
|---|---:|---|
| Normalized SBR archive | 5,132 games; seasons 2018-19 through 2022-23 | `date` + unordered team pair, bridged to canonical `game_id` |
| Official canonical games | 23,222; season labels 2008–2025; dates 2008-10-04–2026-06-14 | `game_id`, `game_date`, `home_team`, `away_team` |
| Pregame rolling features | 23,222; season labels 2008–2025; dates 2008-10-04–2026-06-14 | `game_id`; includes rolling 5v5 xG and each side's max feature-source date |
| Special-teams merged features | 23,002; season labels 2008–2025; dates 2008-10-19–2026-06-14 | `game_id`; team PP/PK rate fields `hpp`, `hpk`, `app`, `apk` |
| Special-teams all-arms features | 9,147; season labels 2019–2025 | `game_id`; PP/PK and penalty-rate fields |
| MoneyPuck team-game CSVs | 190,110 rows across 32 files; season labels 2008–2026; dates 2008-10-04–2026-10-18 | `gameId` + `playerTeam` + `situation`; team-game xG fields |

The normalized SBR table was reconciled against the canonical table rather than treating the raw workbook count as game coverage. The source directory contains 16 Excel workbooks.

### Goalie research DuckDB

The DuckDB contains 19 tables. `gameId` joins in its game-log tables match the canonical NHL game ID. The `shots` table instead uses a season-local source key.

| Table | Rows | Seasons / dates | Join key; representative fields |
|---|---:|---|---|
| `goalies_gamelogs` | 231,540 | 2008–2025; 2008-10-04–2026-04-16 | `gameId`; `playerId`, situation, ice time, xGoals, goals |
| `goalies_playoff_boxscores` | 328 | 2025; 2026-04-18–2026-06-14 | `gameId`; player, `starter`, saves, save percentage |
| `goalies_playoff_seasons` | 125 | 2025 | `playerId` + season + team; xGoals, goals, on-goal |
| `goalies_playoff_shot_metrics` | 174 | 2025 | `gameId`; `goalieId`, shots, saves, xGoals against, GSAx |
| `goalies_seasons` | 8,510 | 2008–2025 | `playerId` + season + team; xGoals, goals, on-goal |
| `lines_gamelogs` | 1,323,417 | 2008–2025; 2008-10-04–2026-04-16 | `gameId`; `lineId`, situation, ice time, xGoals |
| `lines_playoff_gamelogs` | 5,658 | 2025; 2026-04-18–2026-06-14 | `gameId`; `lineId`, situation, ice time, xGoals |
| `lines_playoff_seasons` | 285 | 2025 | season + team; line, situation, ice time, xGoals |
| `lines_seasons` | 158,361 | 2008–2025 | season + team; line, situation, ice time, xGoals |
| `players` | 3,400 | No season column | `playerId`; team |
| `shots` | 2,079,359 | 2007–2025; no date column | season + local `game_id`; goalie/player IDs, xGoal, angle, distance, location |
| `skaters_gamelogs` | 3,886,835 | 2008–2025; 2008-10-04–2026-04-16 | `gameId` + player; situation, ice time, on-ice xG |
| `skaters_playoff_boxscores` | 2,952 | 2025; 2026-04-18–2026-06-14 | `gameId` + player |
| `skaters_playoff_seasons` | 1,735 | 2025 | `playerId` + season + team; situation and ice time |
| `skaters_playoff_shot_metrics` | 2,499 | 2025 | `gameId` + player; shots and xGoals |
| `skaters_seasons` | 81,355 | 2008–2025 | `playerId` + season + team; situation and ice time |
| `teams_gamelogs` | 232,220 | 2008–2025; 2008-10-04–2026-06-14 | `gameId`; team, situation, xGoals for/against |
| `teams_playoff_seasons` | 80 | 2025 | season + team; situation and xGoals |
| `teams_seasons` | 2,770 | 2008–2025 | season + team; situation and xGoals |

### Development SQLite NHL tables

The SQLite inventory used `picks.dev.db` in immutable read-only mode. It contains current/recent league data, not historical rows for the SBR target seasons.

| Table | NHL rows / seasons | Key fields and join |
|---|---:|---|
| `player_game_logs` | 54,727 rows; season keys 2026–2027; 1,488 games | `game_id` + `player_id`; game date, team, postgame stats JSON |
| `player_stats` | 1,801 rows; season keys 2026–2027 | `player_id` + season; goalie `save_pct`, saves, shots against, goals against |
| `player_team_shares` | 2,199 rows; season key 2027 | player + team + season + metric |
| `players` | 1,429 rows | NHL ID; team, position, injury status, last-news date |
| `injury_reports` | 0 NHL rows; the table's 14,070 rows are NFL | player + season; report and practice status |
| `news_items` | 1,709 NHL rows; published dates 2025-01-25–2026-10-20 | `key_player` + published timestamp; unstructured headline/body |
| `roster_snapshots` | 517; season key 2027 | snapshot ID; captured/published time and source checksum |
| `roster_memberships` | 405,303 NHL snapshot memberships across 517 snapshots | snapshot ID + player ID; team, position, roster status |
| `published_roster` | 0 NHL rows | NHL is absent; rows belong to other leagues |
| `player_game_availability` | 0 NHL rows | NHL is absent; rows belong to NFL |

The corresponding script output includes the per-season row/date breakdowns, goalie-row counts, filled injury fields, and current roster capture interval.

## Candidate information families

| Family | Status | Evidence and target coverage |
|---|---|---|
| Announced starting goaltender | **ABSENT** | No archived, time-stamped pregame starter announcements were found. The explicit starter flags located are postgame: playoff boxscore starter fields are from the 2025 season and match none of the SBR target games; current SQLite logs contain 3,075 postgame starter-flag rows and match none of the target games. The local starter-feed feasibility audit also found no historical pregame snapshots. |
| Goalie quality | **PARTIAL** | `goalies_seasons` has 18 season labels and prior-season xGoals, goals, and on-goal values, sufficient to derive GSAx-like and save-percentage summaries. The source-season key is the completed season before each target season, but no per-record capture timestamp is stored. At least one prior-season goalie metric exists for both teams in 5,050 target games. The missing 82 team sides are Seattle in 2021-22, which has no preceding-season team row. This is team-season availability, not the announced starter's individual rating. The separate save-percentage summaries in SQLite are only for season keys 2026 and 2027. |
| Shot quality | **PARTIAL** | Pregame rolling 5v5 xG features exist for 5,127 target games, and both sides' maximum source dates precede each game. Five target rows are incomplete; all five are in 2021-22. These are already-materialized historical features. The `teams_gamelogs` table has postgame xG aggregates with direct game-ID matches for every target game; they must be lagged before use. The raw shot table has 2,079,359 postgame rows, xGoal/angle/distance/location fields, no date field, no explicit coordinate columns, and a season-local game key. A results-anchored one-to-one bridge, keyed by season, teams, final score, and game type, matches 3,055 target games; 158 target games are ambiguous and 1,919 have no candidate. That bridge is for coverage measurement only, not a pregame feature join. MoneyPuck all-situation team-game rows are postgame and have both teams for 3,805 target games. |
| Deployment | **PARTIAL** | Actual line and skater game logs are postgame. Their official game-ID joins cover all 4,872 regular-season target games and none of the 260 playoff target games. They record lines/situations and actual ice time, not the announced pregame lineup or scratches. Existing lagged team PP/PK features have all four values for 5,127 target games; their source code filters to games strictly before the target date. |
| Injuries / roster status | **PARTIAL** | The development database has current NHL roster snapshots for season key 2027, but no season overlap or historical SBR game-status coverage. There are no NHL rows in structured injury reports, published rosters, or player-game-availability tables, and `players` has no filled injury status or last-news date. NHL news is unstructured and begins in 2025, after the SBR archive window. |

### Postgame-only sources

These fields describe completed games and must not be treated as information known before puck drop:

- Goalie appearances, actual starter flags, saves, save percentage, and goals against in game logs or boxscores.
- Shot-level xG, angles, distances, and on-ice context.
- Actual lines, situational use, skater time on ice, and shifts.
- MoneyPuck team-game xG and other team aggregates.

Historical values from completed games can only become pregame inputs to later games after a strict date/season lag. The pregame rolling-feature source dates and the special-teams source-code date filter were checked separately by the script.

## What this rules out

The current local archive cannot support a historical backtest of *announced* starting goalies, injuries, healthy scratches, or pregame line assignments. Postgame flags and usage do not establish what was known before the game. Raw shot-level coverage is also not complete or directly keyed to the canonical game ID. The inventory does show lagged team xG and PP/PK features, but those are already materialized in the historical feature files and are not evidence of a new information feed.

## Reproduction

From the repository root, run:

```sh
/root/lp-goalie-research/.venv/bin/python research/nhl/newinfo-audit-2026-10-20/audit_nhl_sources.py
```

The script reads the local research files, DuckDB, and development SQLite database only. It requires the host-local research directories named in the script and exits with an error if a required source is missing. It does not write to those sources or perform model fitting.
