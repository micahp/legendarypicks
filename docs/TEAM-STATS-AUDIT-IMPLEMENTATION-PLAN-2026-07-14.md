# Four-league team statistics — data audit and implementation plan

**Audited:** 2026-07-14 (America/Chicago)  
**Database:** `/root/legendarypicks/backend/data/picks.dev.db`  
**Audit mode:** SQLite read-only; no shared database or runtime mutation

## Outcome

MLB has a coherent captured-results population suitable for the existing run
aggregate. NBA and NHL have useful box-score fields but not trustworthy season
coverage. NFL has no rows and no implemented extraction. The current
`team_game_stats` design cannot by itself establish season or game-date scope,
and its lack of a unique key has already produced repeated snapshots that look
like additional games if they are aggregated naively.

The API must therefore continue to fail closed for NBA, NHL, and NFL until
official schedule results, paired box scores, and a completed ingestion manifest
agree. Presence of 30 or 32 team abbreviations is not enough to claim coverage.

## Shared database measurements

### `team_game_results`

The table grain is protected by `PRIMARY KEY(league, game_id, team)` and contains
game date, opponent, home/away, scores, and winner.

| League | Rows | Games | Teams | Date range | Reciprocal paired games | Invalid games | Duplicate keys |
|---|---:|---:|---:|---|---:|---:|---:|
| MLB | 2,888 | 1,444 | 30 | 2026-03-26 through 2026-07-12 | 1,444 | 0 | 0 |
| NBA | 0 | 0 | 0 | — | 0 | 0 | 0 |
| NHL | 0 | 0 | 0 | — | 0 | 0 | 0 |
| NFL | 0 | 0 | 0 | — | 0 | 0 | 0 |

Every MLB game has two reciprocal team rows, reciprocal scores, opposing winner
flags, and two distinct home/away sides. This is measured captured coverage, but
there is no durable ingestion manifest proving every official schedule was
fetched successfully; the existing MLB API correctly reports
`external_schedule_reconciled: false`.

### `team_game_stats`

The table contains `league`, `game_id`, capture time, team abbreviation,
home/away, NBA fields, and NHL fields. It does **not** contain season, game date,
opponent, scores, an ingestion-run key, or any NFL-specific fields. It has no
primary key or unique index.

| League | Raw rows | Distinct games | Teams | Two-row games | Non-two-row games | Duplicate `(league, game, team)` excess rows |
|---|---:|---:|---:|---:|---:|---:|
| MLB | 176 | 8 | 16 | 0 | 8 | 160 |
| NBA | 488 | 228 | 30 | 227 | 1 | 32 |
| NHL | 492 | 246 | 32 | 246 | 0 | 0 |
| NFL | 0 | 0 | 0 | 0 | 0 | 0 |

The eight MLB games each contain 22 raw rows: the same two teams were snapshotted
11 times. NBA game `401859965` contains 34 rows: each team was snapshotted 17
times. After choosing the latest row per `(league, game_id, team_abbrev)`, the
logical NBA population is 456 team-game rows across 228 games.

All 488 raw NBA rows have values in the core shooting, rebound, assist, steal,
block, turnover, and foul fields. For NHL, 490 of 492 rows have every audited
league field; both rows for game `401881922` have all NHL metrics null. These
rows were captured from a summary/header fallback and must not count as a valid
box score.

`captured_at` ranges from June 9 to June 29 for NBA and June 9 to July 13 for NHL.
Those are collection times, not game dates. No `prop_games` or `game_context`
join recovers dates for these populations: zero NBA/NHL stat game IDs match
`prop_games`, while `game_context` covers only five NBA and three NHL games and
also has no game-date column.

## Code-path audit

### `backend/backfill_team_stats.py`

- NBA and NHL iterate backward from the machine's current date rather than from
  an explicit league season or authoritative schedule window.
- A game is skipped whenever its raw row count is at least two. This treats
  duplicate, null, or wrong-team rows as complete.
- If exactly one row exists, the update path cannot insert the missing opponent
  row.
- Fetch errors are silently skipped and there is no durable run manifest, team
  inventory, expected-game count, or failure record. A partial run is therefore
  indistinguishable from a complete run.
- The reported `inserted` counter also includes updates.
- NFL checks at most seven recent dates and intentionally performs no extraction.
- NBA turnover naming differs between paths (`totalTurnovers` in the backfill,
  `turnovers` in the snapshot helper); extraction must accept both ESPN names.

### `backend/_core.py` extraction and snapshots

- `_extract_team_stats` is a useful generic raw parser, but header fallback
  returns two teams with empty stats. `_snapshot_boxscore_full` then persists
  those empty rows because it checks only whether the team list is non-empty.
- `_snapshot_team_game_stats` uses `INSERT OR REPLACE`, but the table has no
  unique constraint. SQLite therefore inserts another row instead of replacing
  the existing team-game snapshot.
- Snapshot validation does not require exactly two distinct teams, reciprocal
  home/away sides, or league-required fields.
- The game endpoint invokes the snapshot path for NBA/NHL only. NFL is excluded.

### Existing routes and fixtures

`GET /api/{league}/team-stats` returns a capture-time-ordered raw list with a
200-row limit. It can split a game pair at the limit, include repeated snapshots,
and cannot communicate season or completeness. It should remain a diagnostic
route or be deprecated; it is not a season aggregate contract.

Before this work, the repository had no checked-in ESPN scoreboard/summary
fixture and no team-stat extraction test. A bounded fixture is now checked in
from official ESPN NFL summary event `401772830` (Tampa Bay at Atlanta,
2025-09-07). It confirms NFL team-stat names including `firstDowns`,
`totalOffensivePlays`, `totalYards`, `netPassingYards`, `rushingYards`,
`turnovers`, and `defensiveTouchdowns`. ESPN labels the last field “Defensive /
Special Teams TDs”; it must not be presented as a pure special-teams touchdown
measure. The team summary does not expose a complete special-teams portfolio, so
punt, kick, return, and kicking aggregation needs a separately measured source
shape before that category is expanded.

## Common response and coverage contract

The implemented response preserves `league`, `season`, `supported`, `reason`,
top-level `columns`, `coverage`, and `teams`, and adds league-specific
`categories`. Every category includes Games so rate denominators stay visible.

Coverage now distinguishes:

- the explicit season label and season start/end dates for NBA, NHL, and NFL;
- expected and observed teams;
- expected and observed games;
- reciprocal result pairs and invalid games;
- games with team stats and paired stat games;
- missing stat rows and rows with null required fields;
- first and last game dates;
- whether an official schedule run was reconciled.

For NBA, NHL, and NFL, a supported response requires all of the following:

1. an explicit `season_start` and `season_end` from the selected
   `team_stats_coverage` manifest; calendar-year inference is forbidden because
   NBA, NHL, and NFL seasons cross January 1;
2. the expected league team count;
3. reciprocal two-team result rows with valid scores and winners;
4. one usable, latest box-score row for both teams in every result game;
5. non-null league-required fields;
6. a completed manifest whose team and game counts agree
   with the measured rows.

MLB retains its calendar-year selection because its season is contained within
one calendar year. A non-MLB database without reviewable bounds fails closed as
`season_bounds_unavailable`; malformed or reversed bounds fail as
`invalid_season_bounds`.

If any condition fails, `teams` is empty and `reason` identifies the failed gate.
The current shared database therefore returns MLB supported and NBA/NHL/NFL
`season_bounds_unavailable`; it does not promote the partial box-score captures.

## Implemented first slice

- `backend/team_stats_contract.py` provides a read-only common aggregate builder,
  league category definitions, coverage gates, duplicate-to-latest selection,
  explicit cross-calendar season selection, percentage normalization, NBA
  weighted shooting rates, NHL rates, and NFL offense/derived-defense fields.
- `backend/routers/games.py` delegates the aggregate endpoint to the common
  builder while preserving existing MLB behavior.
- `backend/fixtures/espn_nfl_summary_401772830.json` records the bounded official
  source shape used by extraction tests.
- `backend/test_team_stats_contract.py` proves successful reconciled NBA output,
  cross-calendar season inclusion, schedule-bound failure, null-stat and
  invalid-pair failures, ESPN percentage parsing, and NFL extraction.
- `backend/test_team_aggregates_contract.py` continues to cover MLB reciprocal
  integrity and now verifies explicit NBA categories and fail-closed behavior.

This slice does not add migration-on-import behavior and does not mutate any
database. The manifest and NFL storage columns are contract requirements for the
next ingestion slice, not claims that the shared schema already contains them.

## Next implementation sequence

1. **Create an explicit, reviewable schema migration.** Add a durable
   `team_stats_coverage` ingestion manifest with required `season_start` and
   `season_end` ISO dates, NFL stat columns, and uniqueness at `(league, game_id,
   team_abbrev)`. On a database copy, classify duplicates,
   retain only the latest complete row, reject conflicting team pairs, and prove
   row-count/integrity invariants. Do not hide this migration in request startup.
2. **Make ingestion season-aware and schedule-first.** Accept league, season,
   and explicit start/end dates,
   fetch the official ESPN team inventory, reconcile every team schedule, build
   one unique completed-game set, and only then fetch each summary once. Record
   all failed teams/games and write a `complete` manifest only after counts agree.
3. **Use one normalized extraction/upsert path.** Share the tested ESPN mapping
   between backfill and live snapshots; require two distinct teams and all
   league-required values before an atomic upsert. A partial game must remain
   explicitly incomplete and retryable.
4. **Complete NBA and NHL on a fresh database copy.** Verify expected teams,
   authoritative completed games, reciprocal results, paired stats, no null
   required fields, no duplicates, date bounds, and aggregate sanity against an
   independent standings/sample source.
5. **Implement and validate NFL.** Store the measured team summary fields, derive
   defensive allowed metrics from the opponent row, then audit ESPN player/team
   kicking, punting, and return shapes before claiming a broader special-teams
   category.
6. **Expose the league-specific frontend categories.** Generalize the current MLB
   Teams view only after each league's response is supported. Preserve sorting,
   URL state, visible Games denominators, and the unsupported fallback.
7. **Shared-development backfill requires approval.** Take a SQLite-safe backup,
   run the migration and all ingestion on a fresh copy first, review the diff,
   then announce and obtain explicit approval before changing
   `picks.dev.db`. Production remains a separate promotion.
8. **Verify the real path without restarts unless necessary.** After approved data
   work, exercise backend, frontend, and tunnel contracts, including rendered
   categories and zero browser errors, while preserving the existing runtime
   environment.

## Audit and test commands

The read-only measurements used `sqlite3 -readonly` against the shared DB,
including schema inspection, grouped row/game/team counts, duplicate-key checks,
reciprocal-pair validation, per-field null counts, and neighboring-table joins.

The implementation tests run from `backend/`:

```sh
venv/bin/python -m unittest \
  test_team_aggregates_contract.py \
  test_team_stats_contract.py
```

The first slice passes all 12 focused tests. A final direct call using a SQLite
`mode=ro` connection confirmed the shared database response states without
starting or restarting a service.
