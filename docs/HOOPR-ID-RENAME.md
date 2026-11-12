# Rename players.nba_id to players.hoopr_id

**Status:** Code and migration written on branch `feat/hoopr-id-rename`. Not applied to dev. Not applied to production.

## Why

`players.nba_id` never held an official NBA.com player ID. It holds hoopR athlete IDs. hoopR uses the ESPN athlete ID. Example: Georges Niang has `espn_id` 2990969 and `nba_id` 2990969. His NBA.com ID is 1627777.

The old name made people treat the column as an NBA.com ID.

## The three identifiers

| Where | Meaning |
|---|---|
| `players.espn_id` | ESPN athlete ID |
| `players.hoopr_id` | Legacy hoopR athlete ID, in the ESPN ID namespace |
| `player_source_ids`, `source = 'nba.com'` | Official NBA.com player ID |

There is no `nba_id` column after the rename. Do not add one unless there is a reason to copy NBA.com IDs out of `player_source_ids`.

## Migration

Script: `backend/migrate_players_hoopr_id.py`. It runs `ALTER TABLE players RENAME COLUMN`. SQLite keeps every value, the row order, and any index that used the column. It copies and deletes nothing. It never touches `players.id`.

    python3 backend/migrate_players_hoopr_id.py --db /abs/picks.dev.db            # dry run
    python3 backend/migrate_players_hoopr_id.py --db /abs/picks.dev.db --apply
    python3 backend/migrate_players_hoopr_id.py --db /abs/picks.dev.db --rollback

- It prints the row count, the filled count, and a hash over (`players.id`, `league`, value) before and after. The rename rolls back if they differ.
- It is safe to run again. If the column is already `hoopr_id`, it does nothing.
- It stops if both columns exist.
- Rollback is the same rename in reverse.

## Rehearsal, 2026-11-12

Run on a copy of the dev `players` table (61,510 rows). Result: 541 values before and after, hash unchanged, only league `nba` has values, no schema object other than `players` names the column, second apply did nothing, rollback restored `nba_id` with the same hash. A copy of the whole 3.9 GB database did not fit on disk (4.7 GB free).

## Code that reads the column

Production keeps `nba_id` until the rename is approved there. So code that must run on both databases uses `backend/hoopr_column.py` or checks which column exists. Changed: `ingest_hoopR.py`, `ingest_nba_sportsdataverse.py`, `ingest_nba_roster.py`, `scripts/merge_nba_identities.py`, `migration_manifest.py` (probe), `migrate_logs_to_prod.py` (reads and writes either name), `repair_mislinked_same_name_props.py`, `spine_merge.py`, `props_coverage.py`, `audit_league_stats/checks.py` (checks F and G), `scripts/coverage_report.py`. The label in `data/published-identity-names.json` and `fetch_identity_names.py` is now `hoopr_id`. New databases made by `_core.py` get `hoopr_id`.

## Before applying on dev

The ingest timers run the working tree at `/root/legendarypicks`. Old code reads `nba_id`. Apply the rename on dev only after that checkout has this code.

## Not done

- Not registered in `migration_manifest.py` as a tracked migration.
- Not applied to dev or production.
- Older design docs still say `nba_id`. They are history.
