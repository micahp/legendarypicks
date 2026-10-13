# Spec A: independent review

**Reviewed:** 2026-10-10
**Disposition:** Not complete for a public playoff-odds product. The current schedule and team inputs reconcile, and the v1 backtest is reproducible. Seeding logic is not NFL-compliant, the simulation does not represent tie outcomes correctly, and the weekly job, API, and page are not implemented.

This review treats earlier reports as claims to verify. I queried the dev database read-only, recomputed v1 metrics from the checked-in code, checked saved simulation outputs, inspected the service timer, and reconciled schedule data against the current nflverse games CSV. Historical seeding output was compared with the NFL's published brackets and tie-breaking rules.

## Slice status

| Slice | Finding |
| --- | --- |
| A0: schedule | Current coverage check passes: 842 games checked, zero overdue unscored games. The configured failure-alert path was not failure-injected during this review. |
| A1: teams | All 32 dev team codes match the 2026 team list. The table has no 2024/2025 snapshots. |
| A2: ratings and locks | The fitting and locking code exists, but the 14 stored game locks are from a pre-freeze week-5 run. They are not evidence for the final frozen configuration. |
| A3: backtest | Recomputed v1 metrics match the reported values and beat the two naive baselines in both seasons. The implemented tuning grid omits specified configurations; market and spread/total benchmarks are better. |
| A4: seeding | Generated historical seeds match 28/28 published 2024/2025 seeds. The algorithm does not implement the official tie procedures. |
| A5: simulation | Saved artifacts pass the odds-sum and two-seed stability arithmetic. The simulation's score and coin-flip handling do not model NFL ties faithfully; runtime was not re-measured. |
| A6: weekly job | Not present. |
| A7: API | Not present. |
| A8: page | Not present. |

## Verified data and v1 results

The dev `nfl_schedule` data was compared with the current [nflverse games CSV](https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv):

- 2024 and 2025 each have 285 matching rows, complete scores, and no game-ID or score differences. `game_type`, location, and market fields also match.
- 2026 has 272 matching regular-season fixtures and 65 matching scored games, with no ID or score differences. Seventeen market fields differ from the current upstream file, confirming that market values can change after ingestion.
- The active schedule timer runs the refresh and score checker. The current read-only checker result was `OK nfl_schedule: 842 games checked, 0 overdue unscored (grace 36h)`.
- The dev `nfl_teams` table contains 32 canonical 2026 codes matching the current team list.

I reran `nfl_backtest.backtest_season` and `summarize` against the dev database with the frozen v1 configuration (`half_life=6`, `cap=14`, no points cap, `sigma=13.295`). Results:

| Season | Model Brier / log loss | 50% Brier / log loss | 57% Brier / log loss | Market Brier / log loss |
| --- | ---: | ---: | ---: | ---: |
| 2024 | 0.222452 / 0.636249 | 0.250000 / 0.693147 | 0.251619 / 0.696439 | 0.200114 / 0.586997 |
| 2025 | 0.228811 / 0.649558 | 0.250000 / 0.693147 | 0.249684 / 0.692544 | 0.213697 / 0.612535 |

The model beats the two naive baselines on these metrics in both seasons, but the market is better. Margin MAE also trails the spread in both years (2024: 10.487 vs 9.648; 2025: 10.671 vs 9.971), as does total MAE versus the total line (2024: 10.153 vs 9.723; 2025: 10.614 vs 10.175). The pre-registered pooled bootstrap includes the 2024 tuning season, and `nfl_metrics.bootstrap_mean_diff_ci` resamples individual games as independent pairs; this is a weak basis for a generalization claim. The 2025-only interval against the naive baselines narrowly excludes zero.

The specified margin-cap grid is 14, 17, 21, 28, and none (`docs/SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md`, §4.1). `backend/nfl_tune_2024.py` tests only 14, 21, and none, resulting in 36 configurations rather than the specified 60. The selected configuration and its backtest should not be described as the result of the full specified grid.

## Findings that block completion

### 1. The spec and seeding code do not implement NFL tiebreakers

Spec §5.3 says to skip the NFL's points-based criteria. The official [2024 NFL Record & Fact Book](https://operations.nfl.com/media/hfjn4oid/2024-record-fact-book-incl-supplemental.pdf) includes combined points rankings, net points, and net touchdowns before a coin toss. It also specifies restarting the two-team procedure after eliminations and reducing multi-team wild-card ties to the highest-ranked team in each division.

`backend/nfl_seeding.py` documents that its multi-team restart differs from the NFL procedure and that wild-card reduction is missing. Its final fallback sorts alphabetically and records a coin flag rather than drawing a coin flip. The historical 28/28 match is real—generated seeds match the [official 2024](https://www.nfl.com/playoffs/bracket/2024) and [2025](https://www.nfl.com/playoffs/bracket/2025) brackets—but does not exercise every tied-standings case. Simulated odds can be wrong when these cases arise.

### 2. A5 output arithmetic passes, but tie outcomes are absent from the simulation

The saved 20,000-run artifacts have playoff odds summing to 14 per league, seed probabilities summing to 1 per conference and seed, and a maximum playoff-probability movement of 0.00845 between the two checked seeds (below the 0.015 limit). The seed-3 database payload matches its JSON artifact.

In `backend/nfl_sim.py`, remaining games receive a continuous Gaussian margin and synthetic scores (`20 ± margin/2`). This does not model NFL scoring or ordinary tie outcomes. If seeding reaches its coin fallback, the alphabetical resolution makes it deterministic. Also, `inputs()` treats null-score games as remaining; a future weekly runner must enforce the A0 overdue-score check before simulation. I did not rerun the simulation: at review time the host had about 1.6 GB available RAM and all 4 GB of swap in use. Runtime under the spec's five-minute requirement remains unverified.

### 3. The storage schema cannot preserve versioned locked forecasts or idempotent grades

`backend/migrate_nfl_model_tables.py` makes locked projection uniqueness depend on `(league, game_id, locked)`, without model version. That prevents two model versions from retaining a locked projection for the same game. `projection_grades` has no unique key, so rerunning grading can duplicate rows. The projection snapshot stores spread and total but not moneyline prices; it also lacks a distinct quote timestamp/source record for reproducible market-probability grading. The lock code reads mutable schedule lines and hardcodes the market source.

The dev database contains 36 2024 tuning runs, one 2025 holdout run, one legacy week-5 lock run, and one frozen 2026 simulation run. Its `game_projections` table has 14 rows from the legacy lock configuration (cap 21, sigma 13.4). `team_ratings`, `playoff_odds`, and `projection_grades` are empty. These records do not demonstrate a persistent current-model grading history.

### 4. A6–A8 are not built

There is no `backend/jobs/nfl_weekly_model.py`, NFL model router, playoff-odds page, or NFL model timer. The dev database has no normalized odds or grade rows. The acceptance evidence specified for a complete public feature—a weekly run, grades, API responses, and a page showing real graded rows—is therefore absent.

## Separate EPA v2 candidate

The EPA candidate inspected here is in `/root/lp-nfl-epa`, not on `dev`; Spec A §9 says not to build v2 yet. The candidate aggregates offensive game-total EPA rather than the specified per-play offense/defense pass/rush splits. Its `epa_games()` marks every training game non-neutral, including neutral-site games. Its `evaluate()` calls `with_sigma()` on the season being scored, fitting 2025 sigma from 2025 outcomes and violating the frozen-sigma rule.

I recomputed 2025 metrics using 2024-fitted sigma. The candidate v2 still trails v1: Brier 0.230738 vs 0.228811 and log loss 0.656407 vs 0.649558. This result describes the current candidate; it is not an evaluation of a corrected v2 design.

## Review limits

This was a read-only review of code, database rows, and saved artifacts. I did not run the test suite or rerun the 20,000-season simulations. No source files or database rows were changed. The repository already had unrelated modifications and untracked files; those were left untouched.
