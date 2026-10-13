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

## Update 2026-10-13 (branch `scratch/spec-b-rebase`, dev merged in at 9020531)

Every number below is on a copy of the dev DB taken 2026-10-13 02:04 CDT; details and game sets in
`RESULTS-player-projection-v2-2026-10-12.md` (sections dated 2026-10-13).

| Spec item | State |
|---|---|
| Review findings P1 x4, P2 | Each has a test that fails when its fix is reverted (checked by mutation). The refresh test runs the real script with steps stubbed. |
| 4.3 redistribution | Built (`REDIST='4.3'`), not the default: worse than v2.0 on 2025. Next-man-up fraction 0.590 (targets) / 0.519 (carries) on 2024, close to proportional and unstable on 2025. |
| 4.4 P(plays) | Questionable 0.682 (493 of 723, 2024-2025 skill), Doubtful 0 of 84, Out 0 of 602. In the job. |
| 4.1 game script | Built (`SCRIPT_2024`, `--run --script`), not adopted: 2025 team and player MAE rose. |
| Bias | Defect fixed: LAR/WSH opponent (6.6% of logs). Remaining bias is share held by non-playing candidates (13.3% of targets). P_LOG fixes the bias and RMSE but raises MAE, so not adopted under the MAE rule: mean vs median is Micah's call. |
| 4.5 QB passing | Built, gate passed (403 QB-games, every stat beats Marcel-lite). In job, grader, API (P(over) for passing markets) and page. Rushing still unpublished (carries worse than Marcel-lite). |
| 4.6 consistency | Measured for 2025, `RESULTS-nfl-team-consistency-2025.csv`. |
| 5 props grading | Built (`grade_nfl_prop_probabilities.py`), read-only. Our P(over) loses to the market on Brier in every market on 2026 weeks 2 to 5. |

Fixed on the way: the prop chart ordered undated logs (all 2024 and 2025 NFL logs on PROD) oldest first; the
hit-rate test fixture lacked `props.game_id`; the availability rebuild would have run on PROD through the
installed timer and is now DEV only; em dashes in the new UI.

## What is still not built or not decided

- Rushing publication (gate not passed). The default projection route `/api/projections/player/{id}` is still
  Marcel-lite; switching it is Micah's call. Mean or median projection (P_LOG) is Micah's call.
- No timer for the weekly job. The 2026 week 6 job and ESPN capture have not been run with these changes; the
  stored week 6 rows predate them (no quarterbacks, P(plays) 0.70).
- Props grading is not stored or shown on a page; the projection record panel shows stat-level grading only.
- Nothing has been seen in a browser: the worktree cannot be served.

## Before anything goes to dev

- The installed `legendarypicks-nfl-availability.timer` (Tuesdays 09:30) runs the main checkout's
  `scripts/nfl-availability.sh` against DEV and PROD. With this branch merged, its snap ingest creates the
  new table `nfl_snap_team_sources` on PROD (the availability rebuild itself is DEV only). Decide before merging.
- Browser checks after the merge: the Without control on a prop chart, `/nfl/projections` (receivers and the new
  quarterbacks table), and the projection record panel.
