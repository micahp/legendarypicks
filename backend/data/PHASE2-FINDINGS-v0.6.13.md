# Phase 2 findings — application regressions on clone

Date: 2026-07-31. Backend suite run from `/root/lp-v0613-recut/backend` (worktree, branch recut/v0.6.13).

## Result: 474 passed, 23 skipped, 0 failed

## 2.1 — League-aware game_type filter (profile API)
- `test_players_profile_api.py`: 13/13 pass.
- **Fix applied (test fixture, not product code):** the fixture's `player_stats` table was
  `(player_id, season)` only — stale vs. the rank-card code (`routers/players.py::_compute_stat_ranks`,
  queries `pass_yds_g`/`rush_yds_g`/`rec_yds_g`/`targets`/`receptions`/`fantasy_ppr_g` etc.).
  Added the NFL stat columns + `league`/`stat_type` to the fixture. Product code was correct;
  the fixture predated the NFL rank-card feature.

## 2.2 — 10/12/14-team draft persistence
- `test_mock_draft_team_sizes.py`: 4/4 pass (10-team 150 picks, 12-team 180 picks,
  14-team picks 181–210, 14-team max-rounds pick). Persistence validation reads stored
  `teams`/`rounds` — no hardcoded 12-team constants.

## 2.3 — Full backend suite
- 474 passed / 23 skipped / 0 failed.
- **Fixes applied (test fixtures, not product code):**
  - `test_nfl_dst.py::DstPoolSelectionTests` — added `player_stats` table to fixture
    (pool() computes stat ranks; fixture lacked the table).
  - `test_nfl_mock_draft.py::TestNflMockDraft::setUpClass` — added `player_stats` table
    (same reason; failure was order-dependent because the table came from another
    test file's global state).
- Skips (all expected, pre-existing data gaps):
  - `test_ingest_team_vocabulary.py` ×18 — LP_DB_PATH not set / MLB-NHL canonical migration
    not yet applied (Phase 4 work).
  - `test_nfl_usage.py` ×3 — `picks.dev.db` not present in the clean worktree.

## Note
All three fixes were stale test fixtures that assumed the pre-NFL-rank-card schema.
No product-code change was needed for Phase 2. The two `_compute_stat_ranks` definitions
in `routers/players.py` (lines 135 and 195 — second shadows first) are dead-code debt;
the shadowed first definition is unused. Not touched in this phase.
