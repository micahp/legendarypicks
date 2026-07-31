# Phase 1 findings — schema migrations on clone

Date: 2026-07-31. Target: `/root/lp-v0613-recut/backend/data/rehearsal-v0.6.13.db` (disposable prod clone).
No production DB writes. Only the clone was touched.

## 1.1 — Migration system state
- `migrate_schema.py --check` reports both v0.6.13 ALTER migrations APPLIED on the clone:
  - `20260728_001_player_game_logs_game_type` (checksum f4d1f624...)
  - `20260728_002_team_game_stats_backfill_columns` (checksum 873a29aa...)
- (They were already applied in production before the clone was taken.)

## 1.2 — League-aware game_type filter: CONFIRMED FIXED
- `backend/routers/players.py::_reg_season_game_filter` (line 16): returns empty predicate for non-NFL leagues;
  NFL uses `game_type='REG' OR (game_type IS NULL AND game_no < 19)` — the explicit legacy compatibility rule.
- Clone data distribution: game_type NULL=123,350 (legacy) / REG=18,521 / POST=878.

## 1.3 — nfl_player_projections table: CREATED (clone only)
- Added to `backend/_core.py` `_init_db()` as `CREATE TABLE IF NOT EXISTS` (the codebase pattern for new tables).
- Schema: (player_id, season) PK; espn_id; raw_projection_json; position-relevant normalized stat fields;
  `lp_ppr_projected_points`; fetched_at; payload_checksum. Matches the goal-loop plan §1.3.
- Verified on clone: table exists with composite PK; production `picks.db` does NOT have it (prod untouched).

## 1.4 — player_stats canonical uniqueness: MIGRATION EXISTS, CLONE BLOCKED (by design)
- Code (`league_stats.py:93`) expects `UNIQUE(player_id,league,season,stat_type)`; live table still has
  `UNIQUE(name_norm,league,season,stat_type)` (name-based).
- `backend/migrate_player_stats.py` already implements the fail-closed rebuild
  (`player_stats` → `player_stats_pre_canonical_v0613` → new table with player-based UNIQUE → copy → drop →
  register `20260729_001_canonical_player_stats`; backup + single transaction + post-commit verification).
- `--check` on clone: **BLOCKED** — duplicate_canonical_keys=110, unowned_sources=3346,
  invalid_stat_types=3278, display_name_mismatches=78, null_canonical_fields=23, orphan_players=0.
- Duplicates are multi-source conflicts (MLB statcast + mlb_statsapi; NHL published vs derived).
- **This is Phase 4 work**: rebuild MLB from statcast, retire NHL derived rows, resolve display-name
  mismatches, then re-run the migration. The migration refuses to run while duplicates exist — correct.

## Next
- Phase 2: backend regressions on the clone (league filter, 10/12/14-team drafts, suite).
