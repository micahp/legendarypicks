# Issue: v1 and v1.5 stop on play states their history tables do not cover

- **Status:** open. Opened 2026-11-23 from the week 11 rerun (`docs/research/week11-rerun-preflight-2026-11-23/`).
- **Failure class:** unsupported cell (a named `blocked` status). The engine refuses on purpose. It does not guess.
  This is a coverage gap in these two models, not a crash.
- **Models:** v1 (`v1--season-2026.slcpkg`, code `58ef3861`), v1.5 (`v1.5-ind-hou-overtime.slcpack`, code `2eab8a89`).
- **Remote issue:** not created.

## Size, week 11 (13 games, 100 seeds each)

| model | attempted | completed | failed | games with a failure |
|---|---|---|---|---|
| v1 | 1,300 | 1,244 (95.7%) | 56 | 13 of 13 |
| v1.5 | 1,300 | 1,259 (96.8%) | 41 | 13 of 13 |
| v1.6, v2, pbv1, pbv1-off | 1,300 each | 1,298 to 1,300 | 0 unsupported-cell failures | |

The full breakdown by transition type, down, distance and field position is in the week 11 `REPORT.md` and in
`seed_completion.json` (`unsupported_cell_failures`).

## Cause

The engine draws each play from a table of historical plays keyed by (down, distance bucket, field bucket). In v1
and v1.5:

- After the QB decision layer picks a scramble, only scramble rows in that exact cell can be drawn. After it picks
  a designed run, only non-scramble run rows can be drawn. If the cell has none, the seed stops
  (`qb_scramble_source_rows_missing`, `non_scramble_run_source_rows_missing`, `slc_playcall.py`).
- If the play caller picks run but the cell has no run outcomes at all, the seed stops
  (`playcall_no_run_outcomes_in_cell`).
- Kicks: a blocked kick whose return or recovery lands outside the field, a kick row with a penalty, fumble or review
  that cannot be resolved, a 50+ yard field goal cell that is too thin, and a safety free kick at a quarter end all stop
  the seed.

The engine has five opt-in fixes for these (`e2_reference.BLOCKER_FIXES`): `run_scramble_backoff`,
`long_field_goal_feasibility`, `blocked_kick_source_audit`, `blocked_kick_geometry` and `safety_free_kick_boundaries`.
Each week 11 pack was loaded on 2026-11-23 and its `reference.blocker_fixes` read: v1 and v1.5 have none; v1.6 and v2
have all five. pbv1 shares v2's code commit and its audit log lists all five.

## What to do

- Do not change the v1 or v1.5 packs or their results.
- If v1 or v1.5 stay in the comparison, build them again as new versions (for example `v1-bf` and `v1.5-bf`) with the
  five fixes, and evaluate them side by side with the originals on the same snapshots and seeds.
- Until then, report both models with their completion rate, and use the matched-seed sensitivity in the week 11
  report when you compare them with the other models.
