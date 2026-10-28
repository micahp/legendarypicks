# Reference cutoff audit, 2026-10-28

Rule: a historical simulation may use only evidence observed before its declared cutoff. A reference source that holds
any observation later than the target cutoff fails closed. 2026 stays sealed.

## What the code does now

- `e2_reference.load(eligible_before=...)` refuses every historical cutoff before it reads any table. The refusal names each
  unsafe source (`COHORT_UNSAFE_SOURCES`, `test_reference_cutoff.py`). This stops the leak. It does not make the historical
  path work yet.
- The default path (no cutoff, S0) is unchanged and still loads the pinned artifacts as before.
- The pool and kickoff rows are cutoff-filtered by `e1.load(eligible_before=...)`. That part was already safe.
- Consequence: the 2024 Arizona at Miami exploratory comparison in the earlier turn used sources with 2025 outcomes. It is
  kept as an engineering record only. It is not a valid pregame result, and it cannot be rerun under the cutoff until the
  rebuilds below exist.

## Source inventory

| Source | Where | Window | Per-row date | Cutoff-safe now | Rebuild needed |
|---|---|---|---|---|---|
| Blocked kicks | `docs/fixtures/e2/blocked_kick_outcomes_2022_2025.csv` plus rates in the JSON | 2022-2025 | season, week | no | filter records by cutoff; recompute the rates and the consistency check from the filtered records |
| Safety free kicks | `docs/fixtures/e2/safety_kick_outcomes_2022_2025.csv` | 2022-2025 | season, week | no | filter records by cutoff |
| Overtime drives | `docs/fixtures/e2/overtime_drives_2022_2025.csv` | 2022-2025 | season, week, game_date | no | filter records by cutoff |
| Try fallback (two-point by margin) | `docs/fixtures/e2/try_fallback_2022_2025.csv` | 2022-2025 | none (aggregated) | no | rebuild from play-by-play with a cutoff filter |
| Overtime choice model | `docs/fixtures/e2/overtime_choice_model_2025.csv` | 2025 only | none (one fit) | no | refit from overtime decisions before the cutoff; none exist before 2025 season-end |
| Kick table (FG, punt rates) | `measure_kick_outcomes.load_kick_table` (SQL, 2022-2025) | 2022-2025 | season, week | no | add `season/week < cutoff` to the SQL |
| Missed FG pool | `e2_reference.load_missed_field_goal_pool` (SQL, 2022-2025) | 2022-2025 | season, week | no | add the cutoff to the SQL |
| Participants and extras | `docs/fixtures/e2/play_extras_2022_2025.csv` | 2022-2025 | season, week | no | filter rows by cutoff |
| Position usage | `e2_reference.load_position_usage` (SQL, 2022-2025) | 2022-2025 | season, week | no | add the cutoff to the SQL |
| Kickoff and scrimmage pool | `e1.load(eligible_before=...)` | 2022 to cutoff | season, week | yes | none |
| Team tendencies | `team_tendency.build_from_rows` on prior-season rows | 2022 to cutoff season minus 1 | season | yes | none |

## Rebuild order (no start yet)

1. Row-level filters for the CSV sources (safety, overtime drives, participants, blocked-kick records) with tests that inject a
   future-dated record into each source and check the earlier forecast is unchanged or refused.
2. SQL cutoffs for the kick table, missed-FG pool and position usage.
3. Recomputed blocked-kick rates from the filtered records, replacing the pinned rates in cutoff mode.
4. Try-fallback and overtime-choice refits from play-by-play before each cutoff.
5. Re-run the 2024 Arizona at Miami comparison under the cutoff. Report it as an engineering result, not a backtest, unless the
   schedule and depth publication times are also verified.

## Labels that stay in force

- Schedule rows: current rows, unverified as-of.
- Historical depth charts: prior-week publication unverified.
- Any run that uses these inputs is an exploratory engineering smoke test, not a strict historical forecast.
