# SQLite schema-drift audit — 2026-07-28

Scope: every persistent `CREATE TABLE` under `backend/`, repository history
through release-readiness branch `codex/nfl-release-readiness`, and read-only
metadata from:

- DEV: `/root/legendarypicks/backend/data/picks.dev.db`
- Hermes: `/root/picks.hermes.db`
- prod: `/root/legendarypicks/backend/data/picks.db`

The audit used exact `CREATE TABLE` searches, `git log -S`, `PRAGMA
table_info`, table-presence comparisons, and `PRAGMA quick_check`. No
production row or schema was changed.

## Result

The only column-contract differences among tables present in all three
databases were:

| Table/change | History | DEV | Hermes | Prod | Classification | Migration |
|---|---|---|---|---|---|---|
| `player_game_logs.game_type TEXT` | table `e04745c`; create-only column `ba4ae0b` | exact | exact | missing | required | `20260728_001_player_game_logs_game_type` |
| seven nullable team-stat columns (`run_id`, `first_downs`, `total_offensive_plays`, `total_yards`, `net_passing_yards`, `rushing_yards`, `defensive_special_teams_tds`) | table `7b1267b`; guarded additions `c8198d8` | exact | exact | missing | required | `20260728_002_team_game_stats_backfill_columns` |

Both migrations are immutable/checksummed in `backend/migrate_schema.py`.
An exact unregistered schema is adopted; a wrong type, default, nullability,
primary-key declaration, registered checksum, or missing postcondition fails
closed. `--check` is read-only. `--apply` requires an existing absolute path,
takes and checks an online backup, and applies schema plus registry rows in one
transaction.

Measured current gate state:

| Database | 001 | 002 |
|---|---|---|
| DEV | exact, adoption required | exact, adoption required |
| Hermes | exact, adoption required | exact, adoption required |
| prod | pending | pending |

This is the expected pre-promotion state. Applying either migration to prod
still requires explicit production authorization.

## Creator inventory and history classification

The introduction commit below is the first exact table-creation occurrence in
repository history. A group on one row shares the same creator.

| Creator | Tables | Introduction | Classification / later-schema evidence |
|---|---|---:|---|
| `_core.py` | `predictions`, `strength_snap` | `231ba8f` | core, present everywhere |
| `_core.py` | `roster_snap`, `team_game_stats`, `scoring_plays`, `game_context` | `7b1267b` | core; team-stat drift is migration 002 |
| `_core.py` | `players`, `prop_games`, `props`, `prop_results` | `0c7a3d7` | core; schemas currently equal |
| `_core.py` | `player_stats` | `cfa6cde` | core; guarded `player_id` add exists |
| `_core.py` | `unresolved_players`, `name_alias` | `36c6f58` | core; guarded unresolved columns exist |
| `_core.py` | `prop_odds_snapshots` | `b8455ed` | core; guarded prop odds columns exist |
| `_core.py` | `game_story` | `7afa201` | core, present everywhere |
| `team_stats_schema.py` / `backfill_team_parity.py` | `schema_migrations`, `team_game_results`, `team_stats_coverage`, `team_stats_team_inventory`, `team_stats_ingestion_failures` | `c8198d8` (`team_game_results` first appeared in `9f8c914`) | team-stats proof feature; its integer registry is not the app registry |
| `ingest_nfl_logs.py` / UFC declaration | `player_game_logs` | `e04745c` | migration 001; schemas otherwise exact |
| `ingest_nfl_adp.py` | `nfl_adp` | `ac1d673` | NFL feature; present everywhere |
| `ingest_nfl_schedule.py` | `nfl_schedule` | `f771751` | NFL draft feature not yet populated/deployed to prod |
| `ingest_nfl_pbp_logs.py` | `nfl_pbp` | `de5ed44` | retained-play feature not deployed to prod; not required by draft readers |
| `ingest_nfl_depth_charts.py` | `nfl_depth_chart` | `189b2c7` | NFL draft feature not yet populated/deployed to prod |
| `ingest_nfl_dst.py` | `nfl_dst_stats` | `ab6aa12` | NFL draft feature not yet populated/deployed to prod |
| `ingest_nfl_snap_counts.py` | `nfl_snap_counts` | `def15fa` | NFL draft feature not yet populated/deployed to prod |
| `nfl_transactions_sync.py` | `nfl_transactions` | `2ee36bb` | present everywhere |
| `ingest_ufc_rankings.py` | `ufc_rankings` | `461477d` | present everywhere; separate proven migration |
| NFL draft routers | `nfl_mock_drafts`, `nfl_mock_draft_picks`, `nfl_draft_notes` | `31c752b` / notes `25a1d20` | new-table router schema, present everywhere |
| UFC/esports routers | `ufc_picks`, `esports_picks` | `a7b29b5` / `9f7c1fe` | new-table router schema, present everywhere |
| live-discount router | `live_price_snapshots`, `live_discount_log`, `live_discount_levels` | `9c3d89a` / levels `1683b27` | present everywhere |
| history refresh | `history_refresh_state` | `4f604d8` | environment-local scheduler state; prod-only |
| momentum job | `momentum_state`, `momentum_crosses` | `9f8c914` | feature not deployed to prod |

The prod-absent NFL draft tables are not silently “adopted” migrations. Their
schema and data are created together by the explicit, publisher-backed ingest
sequence in `RUNBOOK-prod-promotion.md`, rehearsed on an online prod clone
before deployment. The router handles the absence before promotion; the live
gate requires complete populated tables after promotion.

## Historical guards retained

- `_core.py` metadata-guards `props.odds`, `props.odds_captured_at`,
  `unresolved_players.source_player_key`, `unresolved_players.reason`, and
  `player_stats.player_id`.
- `migrate_prop_games_start_time_to_prod.py` is the explicit historical
  `prop_games.start_time` migration; the three live schemas now agree.
- `ingest_nfl_pbp_logs.py`, `ingest_nfl_schedule.py`, `ingest_statcast.py`, and
  `backfill_team_parity.py` contain explicit metadata guards. They remain useful
  compatibility checks, but do not substitute for the repository migration
  registry.
- `schema_migrations` remains owned by the team-stats proof. The repository
  registry is separately named `app_schema_migrations`.

## Production-log migrator result

`migrate_logs_to_prod.py` now:

- requires both databases to pass `migrate_schema --check`;
- requires absolute, distinct source and target paths;
- supports an explicit `--league nfl` scope;
- compares required column contracts before backup/copy;
- names every player and log column on both sides;
- excludes shared IDs whose normalized identity disagrees;
- remaps missing source IDs only when one stable target identity agrees;
- leaves every existing target log and its enrichment JSON unchanged;
- materializes source rows before the target write transaction;
- takes and verifies an online target backup;
- proves `props`, `prop_results`, and `prop_games` unchanged by row count and
  SHA-256 content fingerprint inside the write transaction.

Disposable tests cover legacy/current/adopted/wrong schema states, rollback,
checksum no-op behavior, a read-only check, column-order drift, stable-ID
remapping, identity collision exclusion, and protected-table preservation.
