# Context Summary — 2026-08-12 — MLS season-stats landing (worktree copy)

Branch: `feat/league-mls-ncaaf` @ worktree `/root/lp-league-mls-ncaaf`
(HEAD `2d6ab86`, uncommitted changes below). Canonical dev DB
(`/root/legendarypicks/backend/data/picks.dev.db`) was NOT written; all DB work
landed on a fresh copy at `/root/lp-league-mls-ncaaf/backend/data/picks.dev.db`
(replaced the symlink-to-canonical with a real 352 MB copy, `PRAGMA
quick_check=ok`, includes the 4267 ncaaf season rows).

## What changed (all in the worktree)

1. **`backend/migrate_mls_season_columns.py`** (new) — adds the `sot` column
   to `player_stats` (goals/assists/shots already existed). Dry-run by default.
2. **`backend/league_stats.py`** — mls added to `_SEASON_STAT_LEAGUES`;
   `source_owns_stats('mls', 'season', *, 'espn')` → True; mls branch in
   `canonical_population_sql` (`source='espn'`).
3. **`backend/ingest_mls_season_stats.py`** (new) — sums the publisher's own
   per-game values from `player_game_logs` (source `espn`, REG only, season
   2025) into `player_stats` season rows. Published **850 rows**; verified
   count == rows, all four columns non-null on all rows.
4. **`backend/routers/players.py`** — `/api/mls/leaders` was 404 for mls
   (route allowlist lacked mls). Added mls to the allowlist, an mls category
   definition (Scoring: goals/assists; Shooting: shots/sot), an mls default
   (`scoring`/`goals`), and mls change metrics (goals/assists per game).
5. **`docs/LEAGUE-STAT-GAPS.md`** — MLS row updated with the landing evidence.

## Verification evidence (all real, no network used)

- No ESPN requests issued — the rollup reads logs already in the DB
  (espn-request-budget: 0 budget spent).
- Rollup is published-first rung 4: SUM of the publisher's own per-game values,
  not a reimplementation. Independent recompute from raw logs matches the
  published row exactly (Messi: 29 G / 16 A / 157 shots / 71 sot, 28 games).
- Direct audit on the worktree copy (`audit_league_stats.py --db ...`):
  - `PASS mls A/required-stats[season]  4 required stats present and populated`
  - `PASS mls D/leaders-reach-logs      season 2025: 850 of 850 (100%)`
  - Both were FAIL before this landing.
- `verify-gates.sh COV-statset` with `LP_GATE_D`/`LP_GATE_DB` pointed at the
  worktree copy: `FAIL COV-statset (14 of a known 21 open: 2 FAIL, 12
  UNVERIFIED)` — down from 16 (4 FAIL) on the pre-MLS ruler; the two MLS
  FAILs cleared. Not >21 → not REGRESSED.
- `COV-identity` on the copy is blocked at invalid_stat_types=5117 (4267 ncaaf
  + 850 mls): tree artifact — main's `league_stats.py` has neither contract;
  the worktree has both. Goes green when the league_stats hunk lands in main.
- Endpoint probe (route function called directly against the worktree copy):
  `/api/mls/leaders` returns league=mls, season=2025, default category
  scoring/goals, categories [scoring(goals,assists), shooting(shots,sot)],
  Messi first (29G/16A), change evidence comparison 25/25 qualified.
- Tests: `test_leagues_hub_assertions.py` + `test_coverage_gate.py` 22/22;
  `test_audit_league_stats.py` + `test_ingest_mlb_counting_stats.py` +
  `test_ingest_nba_season_stats.py` 50/50.

## Still red for MLS (pre-existing, not regressed)

- `FAIL mls C/vocabulary[position]` — two levels in one column (AM under M,
  CD under D, ...) — same class as ncaaf C/vocab; needs the position_group
  split pattern. NOT part of this landing.
- `UNVERIFIED mls B/position-content[GK]` — no GK game logs; keepers record
  saves/minutes which `ingest_soccer_logs` does not map (documented GK gap).
- `UNVERIFIED mls E/qualifier[season]`, `UNVERIFIED mls G/published-identity` —
  pre-existing manifest items, unchanged.

## Notes / hazards

- The worktree copy of `audit_league_stats.py` is the OLD presence-based
  version (per `docs/PRESERVE-MLS-NCAAF-LANDING.md`). At landing, copy the
  mls/ncaaf MANIFEST hunks into main's newer coverage-floor file — never the
  whole file wholesale.
- The worktree DB is now a real file (not a symlink). Anything that expected
  the symlink (e.g. a worktree stack pointed at canonical dev) now reads the
  copy instead — verify `LP_DB_PATH`/`LP_GATE_D` point where you mean.
- Ralph loop remains INTERRUPTED (session 7); not resumed.
