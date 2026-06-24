# AGENT-M2impl-reasonix — Storage Migration Design Log

**Agent:** reasonix (deepseek-v4-pro)  
**Task:** M2-impl — produce `docs/STORAGE-MIGRATION-DESIGN.md`  
**Started:** 2026-06-24 07:00 UTC  
**Status:** COMPLETE — design doc delivered

## Recon steps

1. **Read task spec** (`docs/TASK-M2impl-reasonix.md`) — 6-section deliverable, read-only guardrails.
2. **Read live DB schema** via `sqlite3 picks.db .schema` — 16 tables enumerated. Discovered orphan `player_stats_new` table (no code references).
3. **Surveyed M5/M6 progress:**
   - M5 (`logs/AGENT-M5-hermes.md`): header only — in early recon phase. Building against existing `team_game_stats` table.
   - M4 (`logs/AGENT-M4-hermes.md`): DONE — void persistence in `prop_results`. No schema change.
   - No M6 design doc exists yet — designed the `odds_snapshots` table shape directly from `ANALYTICS-BACKBONE.md` §2.
4. **Traced current read/write paths** in `sports_service.py`:
   - Read paths: `team_game_stats`, `scoring_plays`, `game_context`, `player_stats`, `players`, `prop_games`, `props`, `prop_results`
   - Write paths: `backfill_team_stats.py` → `team_game_stats`; `sports_service.py:_snapshot_team_game_stats()` → same
5. **Identified name-string joins** (§5 of doc) — 6 locations in `sports_service.py` where `player_id` fallback queries join on `name_norm` or `name=`. Root cause: identity crosswalk not done at ingest time.
6. **Wrote `docs/STORAGE-MIGRATION-DESIGN.md`** — 376 lines, 6 sections + 3 appendices.

## Decisions made

- **`games` uses `espn_event_id` as the canonical cross-source key** (matches current `prop_games.espn_event_id`). This means backfill from `prop_games` is a direct SELECT…INSERT with no mapping needed.
- **`game_player_stats` is per-game granularity** (not season aggregates). Per-season stats become a VIEW rollup. This enables game logs, opponent splits, and historical prop settlement.
- **M5 zero-throwaway:** `team_game_stats` survives with only an added FK column.
- **M6 absorbs via Option A** (odds columns on `props` + `odds_snapshots` FK'd to `games.id` and `props.id`).
- **Migration is 8 steps**, all reversible. Steps 1–4 are additive (CREATE/INSERT/ALTER ADD COLUMN) — zero risk of data loss. Step 7 (FK swap on `props`) is the only medium-risk step.

## Open items / handoff notes

1. **`player_stats_new` orphan** — should be dropped in cleanup. No code references (confirmed by grep).
2. **name-string join elimination** — depends on identity crosswalk coverage reaching ≥95% at ingest time. The `game_player_stats.player_id` column will have NULLs until that's done.
3. **M5 still in progress** — hermes hasn't committed schema changes yet. The absorption plan assumes M5 writes to the existing `team_game_stats` schema (which it does today via `backfill_team_stats.py`).
4. **Migration script** (`scripts/migrate_to_spine.py`) is scoped as the implementation deliverable — NOT part of this read-only design.

## Verification

- [x] Live DDL read from `picks.db` (not guessed)
- [x] Every table mapped to target or explicitly left unchanged
- [x] Every migration step has verify check + rollback
- [x] Name-string joins cataloged with fix strategy
- [x] Risk register covers all destructive steps
- [x] No code/DB writes made
- [x] Output file exists: `docs/STORAGE-MIGRATION-DESIGN.md` (376 lines)
