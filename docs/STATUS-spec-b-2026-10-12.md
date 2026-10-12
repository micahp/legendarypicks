# Spec B status, 2026-10-12

Branch `feat/player-projections-availability` (worktree `/root/lp-player-proj`). Not merged into `dev`, not
pushed, no timer installed. All database work below was on the dev DB (`picks.dev.db`) only.

| Slice | Status | Evidence |
|---|---|---|
| B0 date fix, snaps, injuries | Inputs exist; 2024 snap counts loaded 10-12 (25,357 rows, was 0) | `ingest_nfl_snap_counts.py --year 2024`: 25,398 publisher rows, 41 skipped for unmapped ids |
| B1 availability | Built; absences bracketed by snaps for the same team now recorded (`08c143c`) | 3,416 new 2024-25 absences, 0 contradicted by play-by-play touches (control: 97% of 30+ snap skill players do touch) |
| B2 per-game shares | Built; 2026 rebuilt 10-12 | 32 of 32 team air-yard denominators match; rerun after BUF at LA (10-13) |
| B3 splits | Built | Nacua / Stafford example in the review doc |
| B4 "without" filter, backend | Done (`32eb564`, `42a3a27`) | 11 tests; real: Stafford without Nacua 6 games, 29 with, 7 not counted (4 REG games with an incomplete snap file or playoffs, 3 playoff games outside availability) |
| B5 "without" filter, frontend | Done, **not seen in a browser** (`3a8cb33`) | 8 jest tests, strict tsc, negative control; this worktree cannot be served |
| B6 engine v2 | Built, gate passed by the rule as written (`27d8efe` onward) | `RESULTS-player-projection-v2-2026-10-12.md` |
| B7 tables, job, grading, ESPN capture | Built and run once for 2026 week 6 on dev | 290 player-games, 2,320 rows; ESPN 936 rows; nothing graded yet (needs week 6 to finish) |
| B8 API and record panel | Built, **not seen in a browser** | 5 endpoint tests, 4 jest tests; panel has no real rows until week 6 is graded |

## What is true and unfinished

- **The gate result is thin.** Receiving yards clearly better than Marcel-lite; receptions better with an interval
  touching zero; targets a tie; carries worse; v2 under-projects every stat (receiving yards -3.6 per player-game).
  Rushing is therefore not published. v2 only ties ESPN's weekly projection (and that comparison has caveats).
- **Not built:** next-man-up weighting (4.3), game-script adjustment (needs SPEC A margin), quarterback passing,
  rushing distribution, a Friday/Sunday timer (the job is idempotent and appends runs; no timer installed).
- **The default projection route is unchanged.** `/api/projections/player/{id}` still returns Marcel-lite. The new
  routes are `/api/nfl/projections/player/{id}`, `/api/nfl/projections?week=` and `/api/nfl/projections/record`.
  Switching the default is Micah's call.
- **Pre-kickoff ESPN capture has not happened.** The 2025 ESPN rows were captured after the games; their grading
  is excluded by the kickoff rule. The first real comparison is week 6: run the job and
  `capture_espn_weekly_projections.py --season 2026 --weeks 6` on Friday and Sunday before kickoff, then
  `grade_nfl_player_projections.py --season 2026 --week 6 --summary` after the games.
- **Spotted, not fixed:** the 2024 player logs carry no `game_date`, so the prop chart orders them as a block after
  dated games and prints a blank date; `player_prop_history` takes `settled[-20:]` of a newest-first list, which is
  the OLDEST 20 (existing code, left alone; the new `hit_rates` field uses the newest).

## Before anything goes to dev

The HANDOFF checklist is still open: merge order with `feat/nfl-playoff-odds` and `feat/nfl-grading-record` (this
branch is based on an older `dev`, `a6921c9`, so a rebase or merge is needed and the Model tab files are not here),
the full suite against both DBs, and a browser look at the chart control and `/nfl/projections`.
