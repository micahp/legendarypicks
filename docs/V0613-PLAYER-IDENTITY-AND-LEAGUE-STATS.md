# v0.6.13 player identity, roster, and league-stat contract

Date: 2026-07-29
Scope: backend candidate in `/root/lp-v0613-backend-data`
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
| NBA after 2023 | season | ESPN Core athlete-season totals |
| NFL | season | nflverse weekly rollup |
| NHL | season | NHL API |

NBA and NHL no longer share a second derived display writer. The NFL
compatibility rollup is the only remaining `derive_player_stats.py` owner.

Collectors resolve source-native IDs to one canonical `players.id`. A miss or
duplicate source ID is queued; a stat/log collector does not create a player.
Leader and profile reads filter to the approved population and use canonical
player display identity. Duplicate canonical ownership fails closed.

The new NBA refresh fetches and validates all active ESPN identities before
opening the short write transaction. Coverage below the configured threshold
or any non-404 source/schema error preserves the previous good season
population.

## Shared log read correction

`player_game_logs.game_type` is an NFL field. The candidate applies:

- explicit `REG` plus the bounded legacy regular-season rule for NFL;
- no NFL predicate to MLB, NBA, NHL, UFC, or WC;
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
