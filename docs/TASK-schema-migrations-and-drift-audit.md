# TASK — versioned SQLite migrations and full schema-drift audit

**Owner:** backend  
**Status:** implemented and rehearsed; authorized prod application still required
**Written:** 2026-07-28

## Why this task exists

`CREATE TABLE IF NOT EXISTS` creates a fresh table. It does not migrate an
existing one.

That distinction was missed for `player_game_logs.game_type`. Commit `ba4ae0b`
added `game_type TEXT` to `ingest_nfl_logs.ensure_table`, but DEV and prod
already had the table. The weekly NFL ingest therefore failed on DEV with:

```text
sqlite3.OperationalError: table player_game_logs has no column named game_type
```

The failure was clean and wrote no partial rows, but it also meant the published
all-position weekly artifact had never populated DEV. The result was a
user-visible, plausible absence: 38 kickers rendered and none carried
`pk_pts_per_game`.

The gate was independently fixed in `53a4813`: Aubrey must carry a positive
value after playing 17 games, and at least 80% of kickers with eight or more
games must carry a value. This task fixes the schema mechanism underneath that
gate.

## Current measured state

All database checks below were read-only.

| Database | `game_type` column | 2025 NFL log rows | rows with `fg_att` |
|---|---:|---:|---:|
| DEV `backend/data/picks.dev.db` | yes, manually added | 19,421 | 562 |
| Hermes `/root/picks.hermes.db` | yes | 19,465 | 562 |
| prod `backend/data/picks.db` | **no** | 5,377 | **0** |

Prod is therefore confirmed affected. Its currently deployed API predates the
PK surface and rejects `position=PK`; that does not make the database ready for
the newer code.

The first cross-database schema comparison also found:

- prod `player_game_logs` is missing `game_type`;
- prod `team_game_stats` is missing `run_id`, `first_downs`,
  `total_offensive_plays`, `total_yards`, `net_passing_yards`,
  `rushing_yards`, and `defensive_special_teams_tds`;
- several whole feature tables exist only in DEV/Hermes. A missing table is not
  automatically drift: classify it against the release being promoted before
  proposing a migration.

The existing `schema_migrations` table belongs to the team-stats proof schema
and only stores an integer version. Do not silently treat it as a repository-wide
migration registry.

## Required outcome

Add one explicit, versioned, testable migration path for every persistent SQLite
database used by the application:

```text
backend/data/picks.dev.db
/root/picks.hermes.db
backend/data/picks.db
```

The path must support:

```bash
python3 backend/migrate_schema.py --db /absolute/path --check
python3 backend/migrate_schema.py --db /absolute/path --apply
```

`--check` is read-only and exits nonzero when a required migration or required
schema element is absent. `--apply` requires an explicit absolute database path,
takes a consistent SQLite backup, applies migrations transactionally, verifies
them, and prints each applied or adopted migration ID.

Do not run migrations implicitly while importing a router or starting the
service. Startup may check and fail clearly; deployment applies migrations as a
separate, observable step.

Implementation: `backend/migrate_schema.py` and
`backend/test_migrate_schema.py`. The checked-in historical inventory and
three-database classification is
`docs/SCHEMA-DRIFT-AUDIT-2026-07-28.md`.

## Migration registry contract

Create a repository-wide table distinct from the team-stats proof table:

```sql
CREATE TABLE IF NOT EXISTS app_schema_migrations (
    migration_id TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Each migration has:

- an immutable ordered ID;
- an immutable checksum;
- a precondition;
- an additive transactional change;
- a postcondition that reads SQLite metadata;
- an adoption path for databases already carrying the exact target schema but
  lacking the registry row.

If an existing column has the wrong declared type, default, nullability, or key
contract, fail. Do not mark it adopted merely because its name exists.

## First required migration

Add and verify:

```sql
ALTER TABLE player_game_logs ADD COLUMN game_type TEXT;
```

The migration must work in all three starting states:

1. legacy table without the column — add it;
2. DEV-style table with the correct column but no registry row — verify and
   adopt it;
3. fresh database created by `ensure_table` — verify and adopt it.

After schema migration, population remains a separate copied-data step:

```bash
LP_DB_PATH=/absolute/path \
  backend/venv/bin/python backend/ingest_nfl_weekly_stats.py \
  --year 2025 --all-positions
```

That ingest copies `season_type` and kicking buckets from nflverse's published
weekly artifact. Do not reconstruct them from play-by-play.

## Full historical audit

Inventory every production table creator under `backend/`, including router
initializers. For each `CREATE TABLE IF NOT EXISTS`:

1. locate the commit that first introduced the table;
2. inspect every later commit that added or changed a column, constraint, or
   index in the create-only DDL;
3. determine whether an explicit `ALTER`, rebuild migration, or verified
   adoption path accompanied it;
4. compare the required current schema with DEV, Hermes, and prod read-only;
5. classify each difference as:
   - required migration;
   - feature not deployed yet;
   - retired schema;
   - environment-local table;
6. emit a checked-in report naming the table, change commit, affected
   databases, migration ID, and evidence.

The initial candidate list must include:

- `ingest_nfl_logs.ensure_table` and every league ingest that imports it;
- `ingest_ufc_fight_stats.ensure_table`, which separately declares
  `player_game_logs`;
- `_core` application tables;
- NFL ADP, schedule, PBP, depth-chart, D/ST, snap-count, and transaction tables;
- team-result/team-stat schemas;
- UFC rankings;
- mock-draft, draft-note, pick, live-discount, and history-refresh router tables.

Existing schema guards in `_core.py`, `ingest_nfl_pbp_logs.py`,
`ingest_nfl_schedule.py`, `ingest_statcast.py`, and
`backfill_team_parity.py` are evidence to preserve, not proof that all tables
are covered.

## Fix the production log migrator

`migrate_logs_to_prod.py` currently:

- creates `player_game_logs` only when the table is absent;
- does not compare the existing DEV/prod `player_game_logs` schemas;
- uses `INSERT INTO player_game_logs SELECT *`, which is unsafe whenever column
  order or count differs.

Before it can be used again:

1. require the schema migration check to pass for both databases;
2. name every copied column explicitly on both sides;
3. fail before backup/copy if the required column contracts differ;
4. keep the existing identity-mismatch exclusion;
5. prove `props`, `prop_results`, and `prop_games` are unchanged by count and
   content checksum.

## Tests

Add deterministic tests using disposable SQLite files:

- fresh database applies all migrations once;
- legacy `player_game_logs` gains `game_type`;
- correct unregistered schema is adopted;
- wrong column declaration fails closed;
- a failed migration rolls back both schema work and registry row;
- a second apply is a no-op with the same checksums;
- `--check` performs no writes;
- prod-log migration rejects schema drift before copying;
- prod-log migration uses explicit columns and preserves enrichment JSON;
- a fixture modeled on the pre-fix DEV database fails A1b/A1c before the
  all-position ingest and passes afterward.

## Promotion acceptance

Do not promote the current draft work until an authorized prod migration run
shows all of the following:

```text
prod PRAGMA quick_check = ok
player_game_logs.game_type present
2025 rows with fg_att = 562
Aubrey pk_pts_per_game > 0
eligible kickers with gp>=8 and positive pk_pts_per_game >= 80%
pool-vs-board availability disagreements = 0
pre-existing snap/NGS enrichment preserved exactly
props / prop_results / prop_games unchanged
```

Run the full gate suite against the live production candidate after migration.
Compare the PASS messages between DEV and the candidate, not only the verdicts:
two green gates carrying different coverage numbers require investigation.

## Scope and safety

- Audit prod read-only until a production migration is explicitly authorized.
- Never replace `picks.db` with DEV or Hermes.
- Never copy live prop tables from another database.
- Back up and verify the exact target before applying migrations.
- Use copied publisher fields wherever they exist; schema repair is not
  permission to add new derivations.
