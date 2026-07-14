# Team statistics data and backfill requirements

**Updated:** 2026-07-14 (America/Chicago)  
**Leagues:** MLB, NBA, NHL, NFL  
**Status:** implementation specification; shared-development backfill not yet approved

## Goal

Make the Teams destination show real, season-appropriate statistics for all four
leagues. A league is supported only after its official schedule, completed-game
results, paired team box scores, and coverage manifest reconcile. Partial captures
must return an unsupported reason instead of appearing to be season-to-date data.

## Current state

| League | Trustworthy data now | Missing before completion |
|---|---|---|
| MLB | 30 teams; 2,888 reciprocal result rows for 1,444 captured 2026 games | Reconcile captured games against the authoritative completed schedule and record a completed coverage manifest |
| NBA | 488 raw box-score rows across 228 games; useful fields but partial and duplicated | Full selected-season schedule/results, complete paired box scores, deduplication, explicit season bounds, and coverage manifest |
| NHL | 492 raw rows across 246 paired games; one game has two all-null stat rows | Full selected-season schedule/results, complete paired box scores, removal/retry of null rows, explicit season bounds, and coverage manifest |
| NFL | No stored team-stat rows | Full result and box-score ingestion, NFL storage columns, explicit season bounds, and measured special-teams sources |

The existing NBA/NHL rows are evidence and possible cache material, not proof of
season coverage. The current `team_game_stats` table has no unique key, season, game
date, opponent, score, or ingestion-run identity. It must not be aggregated directly
without joining to reconciled results and applying the coverage gates below.

## Required common data

Every league-season backfill needs four durable datasets.

### 1. Team inventory

Capture the authoritative team list for the selected league and season:

- league and season label;
- canonical team ID, abbreviation, and display name;
- active status for that season;
- source and capture time.

Expected active team counts are MLB 30, NBA 30, NHL 32, and NFL 32. The backfill must
fail if the observed inventory does not match the expected count; it must not silently
continue with a partial team list.

### 2. Completed-game schedule and results

For every authoritative completed game, store exactly two reciprocal team rows in
`team_game_results`:

- league, season, ESPN event ID, and game date;
- team and opponent;
- home/away side;
- score for and score against;
- win/loss/tie outcome;
- league-specific result details where needed;
- source and ingestion time.

Each pair must contain the same event ID and date, opposite teams and sides,
reciprocal scores, and compatible outcomes. The official schedule—not the number of
rows already in SQLite—defines the expected game population.

### 3. Paired team box scores

For every completed result game requiring advanced statistics, store exactly one
latest validated row for each team in `team_game_stats`. Both teams must be written
atomically. A game with one team, two identical teams, duplicate sides, or null
required metrics remains incomplete and retryable.

Required common identity fields are:

- league, season, event ID, game date, team, opponent, and home/away;
- source, source capture time, ingestion run ID, and validation status.

### 4. Coverage and ingestion manifest

Add a durable `team_stats_coverage` record for every attempted league-season run:

- league and season label;
- explicit ISO `season_start` and `season_end` dates;
- run status: `running`, `incomplete`, `failed`, or `complete`;
- expected and fetched team counts;
- expected and fetched completed-game counts;
- paired result games and paired stat games;
- failed team/game counts and a reference to failure details;
- first and last covered game dates;
- source, run ID, start time, and completion time.

NBA, NHL, and NFL cross January 1, so their season scope must come from explicit
manifest bounds. Calendar-year inference is forbidden for those leagues. MLB can use
its calendar-year season label, but it still needs an authoritative reconciliation
manifest for the final coverage guarantee.

Only a run that exactly reconciles its inventory, results, required box scores, and
failure count may be marked `complete`.

## Required schema migration

Build and prove this migration on a fresh `/tmp` database copy before requesting a
shared-development change.

1. Add a unique constraint or unique index on
   `(league, game_id, team_abbrev)` in `team_game_stats`.
2. Add `season`, `game_date`, `opponent`, `source`, `ingestion_run_id`, and validation
   metadata to team-stat rows, or enforce an equivalent normalized join whose
   invariants are checked during every write.
3. Add the NFL fields listed below.
4. Add `team_stats_coverage` with explicit season bounds and measured counts.
5. Add an ingestion-failure table or structured artifact keyed by run, league, team,
   and event ID. Fetch errors cannot be swallowed.
6. Add any result fields required to represent NHL overtime/shootout losses and NFL
   ties accurately.
7. Preserve the existing `team_game_results` reciprocal-pair primary key.

Before adding uniqueness, classify all duplicates on the copy. Retain the latest
complete row only when its teams and metrics agree with the official event. Archive
or report every discarded row. Never let a later null snapshot replace an earlier
complete row.

## League-specific data

### MLB

Initial categories:

- record: games, wins, and losses;
- run production: runs per game and total runs for;
- run prevention: runs allowed per game and total runs against;
- differential: run differential and differential per game.

Required backfill:

1. Fetch the authoritative 2026 MLB team inventory.
2. Fetch each team's completed schedule through a single recorded cutoff date.
3. Deduplicate games by ESPN event ID and rebuild/repair reciprocal result pairs.
4. Compare the authoritative completed-game set with the existing 1,444 captured
   games; fetch missing games and report unexpected extras or conflicting scores.
5. Write a completed manifest only when all 30 teams and all authoritative completed
   games reconcile with zero invalid pairs.
6. Add an incremental updater that repeats reconciliation after newly completed
   games.

MLB does not require `team_game_stats` for the initial record/run categories. Box
scores may be added later for batting, pitching, or fielding team categories, but
they must not block completing the current honest MLB view.

### NBA

Initial categories and required team-game fields:

- record/scoring: score for, score against, wins, and losses;
- shooting: field goals made/attempted, three-pointers made/attempted, and free
  throws made/attempted;
- rebounding: offensive, defensive, and total rebounds;
- playmaking/ball security: assists and turnovers;
- defense: steals and blocks;
- optional second-stage context: fouls, points off turnovers, fast-break points,
  paint points, largest lead, lead changes, and lead percentage.

Required backfill:

1. Select and record one NBA season with explicit official start/end bounds.
2. Fetch all 30 teams and reconcile their schedules into one unique completed-game
   set.
3. Store two reciprocal result rows for every completed game.
4. Fetch every game summary once and normalize both team box scores through the
   shared extractor.
5. Treat both `turnovers` and `totalTurnovers` ESPN names as the same metric.
6. Parse made-attempted values into weighted season totals; do not average per-game
   percentages.
7. Classify the existing duplicated game `401859965` and all other repeated rows on
   the database copy; retain only the validated latest pair.
8. Mark coverage complete only when all result games have two valid stat rows and
   all required fields are non-null.

### NHL

Initial categories and required team-game fields:

- record/scoring: goals for, goals against, wins, regulation losses, overtime or
  shootout losses, and standing points where supported;
- shots: shots and derived shooting percentage;
- possession/physical play: faceoff percentage, hits, blocked shots, takeaways, and
  giveaways;
- special teams: power-play goals and opportunities, shorthanded goals, penalties,
  and penalty minutes.

Required backfill:

1. Select and record one NHL season with explicit official start/end bounds.
2. Fetch all 32 teams and reconcile their schedules into one unique completed-game
   set.
3. Store reciprocal results, including enough status detail to distinguish a
   regulation loss from an overtime/shootout loss. Modern NHL records must not expose
   a generic ties column.
4. Fetch and validate both team summary rows for every game.
5. Normalize percentage strings such as `52.8%` before storage.
6. Reject and retry summary/header fallbacks that contain teams but no statistics.
   Existing game `401881922`, whose two NHL rows are all-null, must not count as
   covered.
7. Mark coverage complete only when every result game has a paired, non-null box
   score and the official game count agrees.

Goalie ingestion is a separate player-stat project and does not block team coverage.

### NFL

Initial categories and required team-game fields:

- record/scoring: score for, score against, wins, losses, and ties;
- offense: first downs, total offensive plays, total yards, net passing yards,
  rushing yards, turnovers, and derived yards per play;
- defense: points and yards allowed derived from the reciprocal opponent row, plus
  takeaways derived from opponent turnovers;
- special teams: at minimum defensive/special-teams touchdowns, with the broader
  fields below required before claiming a full special-teams category.

Required backfill:

1. Select the completed NFL season and record explicit bounds. Keep regular season
   and postseason scope explicit; do not mix them without labeling the combined
   scope.
2. Fetch all 32 teams and reconcile the complete schedule rather than checking a
   recent seven-day offseason window.
3. Store reciprocal result rows for every completed game, including valid tied
   games.
4. Add and populate `first_downs`, `total_offensive_plays`, `total_yards`,
   `net_passing_yards`, `rushing_yards`, `turnovers`, and
   `defensive_special_teams_tds`.
5. Fetch every game summary through the tested shared extractor and validate paired
   team rows.
6. Audit ESPN team/player shapes for field goals made/attempted, extra points,
   punts/net punting, punt returns, kickoff returns, return yards, and return
   touchdowns. Add only fields with reproducible source coverage.
7. Do not present `defensiveTouchdowns` as pure special-teams production; ESPN labels
   it defensive/special-teams touchdowns.
8. Mark coverage complete only after results, offense, derived defense, and the
   explicitly promised special-teams fields reconcile for the whole selected scope.

## Backfill implementation requirements

Replace the current date-loop scripts with one season-aware, schedule-first pipeline:

1. Accept explicit `--league`, `--season`, `--season-start`, `--season-end`, database
   path, and run/report destinations.
2. Refuse an unapproved shared-development or production path by default; make
   `/tmp` copy execution the normal development mode.
3. Create a `running` manifest and persist the exact input scope.
4. Fetch and validate the complete team inventory.
5. Fetch every team schedule, record failures, and reconcile one unique event set.
6. Upsert reciprocal result pairs atomically.
7. Fetch each completed event summary once.
8. Use one normalized extraction path shared with live snapshots.
9. Require exactly two distinct teams, home/away reciprocity, and every
   league-required field before atomically upserting the stat pair.
10. Retry transient failures with bounded backoff and leave permanent failures in the
    run report.
11. Recompute measured counts from SQLite rather than trusting counters in memory.
12. Mark the manifest `complete` only if every coverage invariant passes; otherwise
    mark it `incomplete` or `failed` with machine-readable reasons.
13. Support safe reruns and incremental updates without producing duplicates.

## Validation gates

The API may return `supported: true` only when all applicable checks pass:

- expected team count equals observed team count;
- authoritative completed games equal observed unique games;
- every game has exactly two reciprocal result rows;
- every required game has exactly two validated stat rows;
- home/away sides, opponents, scores, and outcomes agree;
- required fields contain no nulls;
- duplicate logical team-game keys equal zero;
- manifest season bounds contain every included game and exclude other seasons;
- manifest status is `complete` and its counts equal fresh database measurements;
- first/last covered dates and source are disclosed in the response.

League-specific aggregate sanity checks must also pass: wins/losses/ties reconcile,
league-wide points or runs for equal points or runs against, shooting makes do not
exceed attempts, NBA rebound components reconcile where the source guarantees it,
NHL power-play goals do not exceed opportunities, and NFL defense-derived totals
equal the reciprocal offense totals.

## Safe rollout order

1. Implement the schema migration and pipeline against fixtures.
2. Take a SQLite-safe copy of the shared development database into `/tmp`.
3. Apply the migration to the copy and produce a duplicate/archive report.
4. Backfill and validate MLB on the copy.
5. Backfill and validate NBA on the copy.
6. Backfill and validate NHL on the copy.
7. Backfill and validate NFL on the copy.
8. Review row counts, failures, aggregates, and before/after diffs for all leagues.
9. Obtain explicit approval before backing up and changing the shared development
   database.
10. Verify the real API and Teams UI without restarting the shared frontend, backend,
    or tunnel unless a restart is genuinely required.
11. Treat production as a separate approved migration and backfill.

## Definition of done

A league is complete only when ingestion can reproducibly rebuild and incrementally
update its selected season, the coverage manifest reconciles to official schedules,
the aggregate API is supported with league-specific categories, tests cover failure
and integrity cases, and the rendered Teams view is verified through the real
frontend/backend path.

Adding a tab, returning partial rows, or merely observing all expected team
abbreviations does not satisfy this definition.
