# v0.6.13 player identity, roster, and league-stat contract

Date: 2026-07-29
Scope: backend candidate in `/root/lp-v0613-backend-data`; NBA v1 follow-on
in `/root/lp-nba-v1`
Production mutation: not authorized

## Decision

`players` remains the canonical person index. A roster is not a person index:
it is a versioned statement that a canonical person belonged to a team at a
point in time.

The release contract is:

1. one durable `players.id` per real person;
2. source-native IDs resolve to that person before any dependent row is
   written;
3. complete rosters publish immutable membership snapshots;
4. game logs, season statistics, props, and displays join by `players.id`;
5. unresolved or ambiguous identities queue and do not create speculative
   duplicates.

## How the current player index was constructed

The existing `players` table was accumulated by several jobs. It was not built
from one pinned manifest.

- `roster_sync.py` walked ESPN team rosters and populated ESPN ID, name, team,
  position, and active state.
- league-specific history jobs attached or imported MLBAM, nflverse GSIS, NHL,
  and hoopR IDs;
- historical migrations copied canonical players needed by dependent rows;
- some legacy prop collectors created name-only World Cup or UFC identities.

`players.id` is a SQLite surrogate key. Its source columns are:

| Column | Identity source |
|---|---|
| `espn_id` | ESPN rosters, scores, and box scores |
| `mlbam_id` | MLB / Statcast |
| `nfl_gsis_id` | nflverse |
| `nhl_id` | NHL API |
| `nba_id` | historical hoopR |

The mutable `team`, `position`, and `active` columns remain compatibility
fields. They are not historical membership records.

### Current database evidence

Read-only counts on 2026-07-29:

| Database | MLB | NBA | NFL | NHL | UFC | WC |
|---|---:|---:|---:|---:|---:|---:|
| DEV players | 2,459 | 1,132 | 24,678 | 995 | 49 | 93 |
| production players | 2,750 | 1,063 | 25,059 | 877 | 29 | 63 |

Those totals intentionally include historical identities, but the reported
active populations are also stale for several leagues. They cannot be treated
as a current roster without a verified roster publication.

Production also has 317 duplicated MLBAM-ID groups. Native-ID uniqueness must
not be enabled there until an identity-safe merge is rehearsed on a disposable
production clone and every dependent foreign key and protected-table
fingerprint is verified.

## Canonical roster contract

The legacy `roster_snap` is retained as a request-time capture table. It is not
the canonical roster:

- its `player_id` is an ESPN string, not `players.id`;
- it has no snapshot identifier, release state, checksum, or canonical
  foreign key;
- DEV contains only 97 rows across two leagues and four capture times.

The candidate adds:

### `roster_snapshots`

One immutable header per captured league population:

- league and conventional season;
- source and capture/publication timestamps;
- SHA-256 checksum;
- deterministic normalized source payload;
- team and player counts;
- `published` or `superseded` state.

Exactly one snapshot per league may be published.

### `roster_memberships`

One row per canonical member of a snapshot:

- `snapshot_id`;
- canonical `players.id`;
- source player key;
- team, position, jersey, and roster status;
- source display name for audit evidence.

Both the canonical player ID and source player key are unique within a
snapshot.

### Publication sequence

`roster_sync.py` now:

1. requires the explicit roster-schema migration before making source calls;
2. fetches the complete expected team directory and every non-empty roster;
3. normalizes team and position vocabulary;
4. detects missing or duplicate source IDs;
5. resolves the whole population by exact ESPN ID, or by a constrained
   one-time name crosswalk with no ID/team conflict;
6. queues ambiguity and preserves the previous published snapshot;
7. in one transaction, creates any authoritative roster identities, writes
   membership rows, supersedes the previous snapshot, publishes the new
   snapshot, and refreshes the compatibility fields.

A partial upstream response, ambiguous identity, duplicate source ID, schema
error, or transaction failure leaves the last published roster intact.

## Canonical season-stat ownership

`player_stats` is a published display table, not a multi-source raw lake.
There is one row per:

`(player_id, league, season, stat_type)`

Approved owners are:

| League / season | Stat type | Published owner |
|---|---|---|
| MLB | batting or pitching | Statcast |
| NBA through 2023 | season | hoopR |
| NBA after 2023 | season | ESPN published regular-season player table |
| NFL | season | nflverse weekly rollup |
| NHL | season | NHL API |

NBA and NHL no longer share a second derived display writer. The NFL
compatibility rollup is the only remaining `derive_player_stats.py` owner.

Collectors resolve source-native IDs to one canonical `players.id`. A miss or
duplicate source ID is queued; a stat/log collector does not create a player.
Leader and profile reads filter to the approved population and use canonical
player display identity. Duplicate canonical ownership fails closed.

The NBA publisher must learn from the ESPN table itself. ESPN's
`statistics/byathlete` collection is the correct publication shape: one
season-type request returns the table categories, stable ESPN athlete IDs, and
each athlete's aligned values. The individual ESPN Core athlete-season
endpoint agrees with those values, but one request per roster member triggered
HTTP 403 protection during the clone rehearsal and is not an acceptable
collection design.

The collection URL is:

`https://site.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete`

It is requested with explicit `season`, `seasontype=2`, `page`, `limit`, and
an ESPN table sort. The response currently reports 582 regular-season athlete
rows for 2026. Its named category schema includes the same dense measures ESPN
displays: GP, MIN, PTS, FGM/FGA/FG%, 3PM/3PA/3P%, FTM/FTA/FT%, REB, AST, STL,
BLK, and TO. Shooting makes and attempts are per-game values on the ESPN
table, not season totals.

The new NBA refresh requires the exact published roster snapshot as its current
identity gate, validates the collection schema, and then resolves every season
row against the full canonical NBA ESPN-ID spine before opening the short write
transaction. This distinction matters: the season table includes players who
appeared earlier in the year but are not on today's roster. Missing or
duplicate IDs, coverage below the configured threshold, or any source/schema
error preserves the previous good season population.

The first collection rehearsal resolved 580 of 582 ESPN rows. The two misses
were Markelle Fultz (`4066636`) and Andersson Garcia (`4702431`). Fultz already
existed under the equivalent legacy `nba_id`; Garcia had no canonical row.

The follow-on candidate adds a separate, backup-first season-identity
publisher. It does not write statistics or membership. On the disposable clone
its exact plan resolved 580 identities, backfilled Fultz's `espn_id`, inserted
Garcia as an inactive canonical person, and then allowed the stat publisher to
replace the legacy population with 582 of 582 `espn_site_stats` rows. The
resolved queue was empty after publication. DEV and production remain
unchanged.

## NBA season-phase contract learned from ESPN

ESPN separates NBA games with an explicit event `season.type` and
`season.slug`:

| ESPN type | ESPN slug | Canonical game type | 2025-26 dates from ESPN |
|---:|---|---|---|
| 1 | `pre` | `PRE` | 2025-10-01 through 2025-10-21 |
| 2 | `reg` | `REG` | 2025-10-21 through 2026-04-13 |
| 5 | `playin` | `PLAYIN` | 2026-04-13 through 2026-04-18 |
| 3 | `post` | `POST` | 2026-04-18 through 2026-06-27 |
| 4 | `off` | no game-log population | offseason |

The NBA Cup needs a narrower exception. Group, quarterfinal, and semifinal
games remain regular-season games. The event whose competition note is
`NBA Cup Championship` is `CUP`: ESPN carries it under season type 2, but
excludes it from regular-season standings.

Completion is independent from phase. A postponed event may have
`status.type.state = "post"` while `status.type.completed = false`; it must
not publish a zero box score. DEV currently contains one such event,
`401810384` (Chicago-Miami), as ten all-zero player rows in addition to its
makeup game. The NBA cleanup must remove that event.

ESPN's 2025-26 standings are the reconciliation authority for the regular
season: 30 teams, 82 games per team, and 1,230 games. DEV's current
`team_game_results` population has 1,227 games, eight team records disagree
with ESPN, and one team has 83 games. The legacy parity writer cannot certify
itself by setting `expected_games = games_written`; it must validate against
the ESPN standings totals, fetch completely before deleting, and fail the
whole publication on schedule or summary errors.

The follow-on parity publisher now requires the explicit migrated schema,
fetches ESPN standings, the 30-team directory, every team schedule, and every
summary before opening its write transaction. It excludes only the Cup
Championship, requires `completed=true`, reconciles every team to 82 games and
the standings win record, and requires exact operator-provided game/team counts
plus a verified backup under `--apply`. A disposable-clone rehearsal validated
all 1,230 summaries and atomically published 2,460 reciprocal result rows plus
2,460 complete team-stat rows. The manifest records
`espn_team_schedules+espn_boxscores+espn_standings`; legacy self-referential
manifests now fail closed as `schedule_not_reconciled`.

The current player-log population also cannot derive the published season
table: it contains 1,017 regular-season game IDs, 6 Play-In games, 85
postseason games, the Cup final, and the postponed zero game. It is missing
213 of ESPN's 1,230 regular-season games. Published ESPN regular-season stats
therefore own the season table; phase-tagged box scores own history.

The NBA identity rehearsal found that `players.nba_id` and `players.espn_id`
are the same ESPN athlete-ID vocabulary. DEV has 272 exact split identity
pairs. On a disposable clone, the guarded merge moved 264 historical
`player_stats` rows, then published an idempotent 2026 roster snapshot with
545 players across 30 teams and zero duplicate ESPN IDs. No DEV or production
database was mutated.

The completed clone rehearsal then:

- published 582 unique 2026 ESPN season rows and retained 525 hoopR-owned 2023
  rows;
- classified 1,017 regular-season games, 6 Play-In games, 85 postseason games,
  and the Cup final, while removing the ten-row postponed event;
- returned 100 unique leader links in the 100-row API sample;
- returned 30 supported NBA Team Stats rows with zero invalid or missing pairs;
- kept `props`, `prop_results`, and `prop_games` byte-identical to DEV; and
- passed `PRAGMA quick_check`.

## Shared log read correction

`player_game_logs.game_type` is now a shared phase field. The candidate
applies:

- explicit `REG` plus the bounded legacy regular-season rule for NFL;
- explicit `PRE`, `REG`, `PLAYIN`, `POST`, and `CUP` classification for NBA;
- NBA regular-season displays include only explicit `REG`; legacy null rows
  fail closed rather than blending phases;
- no NFL or NBA predicate to MLB, NHL, UFC, or WC;
- explicit NFL postseason and legacy postseason separation.

The same helper governs profile history, matchup evidence, projections, and
leader change evidence so those surfaces use the same population.

## Explicit migrations and current gates

### Canonical `player_stats`

`migrate_player_stats.py --check` is byte-for-byte read-only.
`--apply` requires an absolute DB path, creates and verifies an online backup,
and refuses to repair or guess data.

Current read-only result:

| Gate | DEV | Production |
|---|---:|---:|
| null canonical fields | 5 | 23 |
| display-name disagreements with `players` | 549 | 176 |
| invalid stat types | 2,638 | 4,044 |
| unowned sources | 2,799 | 4,205 |
| duplicate canonical keys | 703 | 519 |

Both databases are **BLOCKED**. Authoritative publisher refreshes and identity
repair must produce a clean clone before this migration can apply.

### Canonical roster snapshots

`migrate_roster_snapshots.py` is also read-only under `--check` and
backup-first under `--apply`. Both DEV and production currently report
**PENDING** because the new tables have not been created. No migration was
applied during implementation.

A disposable clone of the 2026-07-29 production database passed the roster
migration rehearsal:

- verified backup created;
- post-apply migration state `APPLIED`;
- `PRAGMA quick_check = ok`;
- one migration registry row;
- zero published snapshots before the first roster ingest;
- combined deterministic dumps of `props`, `prop_results`, and `prop_games`
  matched before and after:
  `26052fde701def36185c522eccedc374ca0bf2ec18a4dfa097f0de168102d65f`.

## Remaining identity recommendations

For v0.6.13:

- repair production's duplicated MLBAM identities on a disposable clone;
- after repair, add partial unique indexes for every populated native-ID
  column;
- retire remaining prop-side player creation and route it through
  resolve-or-queue;
- measure roster publication coverage independently for each league;
- require the published roster snapshot checksum in release evidence.

After v0.6.13, replace the growing set of native-ID columns with:

`player_external_ids(player_id, source, source_id)`

and enforce uniqueness on `(source, source_id)`. This is a schema
normalization, not a prerequisite for the re-cut, and should not be mixed into
the current data repair.

## Promotion boundary

This candidate code does not authorize production writes. Before promotion:

1. run both migration checks against a new production clone;
2. repair canonical populations only from pinned authoritative inputs;
3. take and verify backups before applying either migration;
4. publish complete rosters for MLB, NBA, NFL, and NHL;
5. prove one current snapshot per league and zero unresolved published
   memberships;
6. prove leader uniqueness, canonical links, profile history, matchup
   evidence, and projection evidence for every exposed league;
7. compare protected-table fingerprints before and after;
8. obtain explicit approval before touching the live production database.
