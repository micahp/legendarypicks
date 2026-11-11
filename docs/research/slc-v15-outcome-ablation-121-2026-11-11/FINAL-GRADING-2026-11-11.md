# V1.5 outcome-layer ablation: final cohort grading

**Run completed:** 2026-11-11, fast-host output captured at 09:08 CT

**Graded:** 2026-11-11

**Simulator source:** `67d3f5522da13d20f79389cfac2f7495386c4d10`
**Treatment:** disable only `team_offense_defense_outcomes`

## Run coverage

The cohort contained 121 scheduled games. The runner completed 119 with 20 valid paired RNG-v2 seeds per arm (2,380 paired seeds per arm). Two games failed validation and remain excluded from complete-game comparisons:

| Game | Failed arm and seed | Preserved result |
| --- | --- | --- |
| `2026_03_LA_DEN` | Ablation, seed 9 | Full failed record; safety followed by a clock-expiring safety free kick |
| `2026_04_LAC_SEA` | Control, seed 16 | Full failed record; safety followed by a clock-expiring safety free kick |

These are the failures documented in [the safety analysis](SAFETY-FAILURE-ANALYSIS-2026-11-11.md). The saved records suggest the validator does not recognize `safety_free_kick` as a game-ending kick. The engine's clock rule for those kicks is an authored modeling choice and still needs a separate rules review. No failed seed was rerun or counted as a valid game.

The 119 completed games include `2026_08_CHI_SEA`, for which the grading database has no final score. Predictive scoring therefore covers 118 games. The team points metric has 236 team-game observations; actual sacks and turnovers have 222 team-game observations each because the database lacks player-game rows for some teams. Grading used the existing read-only `/root/repro/picks-snap.db` on the fast host.

## Predictive scores

| Metric (lower is better) | Control | Ablation | Ablation minus control | 95% paired interval for difference |
| --- | ---: | ---: | ---: | ---: |
| Winner Brier, 118 games | 0.24784 | 0.26133 | +0.01349 | −0.01253 to +0.03865 |
| Winner log loss, 118 games | 0.69768 | 0.71753 | +0.01985 | −0.04057 to +0.07907 |
| Home points CRPS | 5.20944 | 5.47714 | +0.26770 | — |
| Away points CRPS | 6.11740 | 6.25708 | +0.13968 | — |

Both winner scores and both points CRPS values are worse for the ablation. The paired 95% intervals for winner Brier and log loss include zero. The predeclared advancement rule fails: the ablation does not improve both winner metrics, and the log-loss difference is not statistically below zero.

## Score distributions and tails

The table pools simulated team scores across the 119 completed games and 20 seeds (4,760 team scores per arm). Actual team scores cover the 236 teams from 118 scored games. Total-score rates use 2,380 simulated games per arm and 118 actual games.

| Scoring measure | Control | Ablation | Actual |
| --- | ---: | ---: | ---: |
| Team points: mean | 22.18 | 22.18 | 22.96 |
| Team points: p10 / median / p90 | 10 / 22 / 34 | 12 / 22 / 34 | 10 / 24 / 35 |
| Team scores ≤10 | 10.25% | 9.68% | 12.71% |
| Team scores ≥35 | 8.26% | 7.42% | 11.02% |
| Game total: mean | 44.35 | 44.36 | 45.92 |
| Game total: p10 / median / p90 | 29 / 44 / 61 | 29 / 44 / 61 | 28 / 44 / 64 |
| Game totals ≤30 | 12.31% | 13.32% | 11.86% |
| Game totals ≥60 | 11.55% | 11.09% | 21.19% |

Both arms produce fewer very high scoring games (total ≥60) than observed in this cohort. The ablation slightly increases low team scores and lowers high team scores; these tail rates are descriptive, not independent-game uncertainty estimates.

## Team outcomes and player workload

For team outcomes, MAE is averaged over observed team-games. Paired differences are game-clustered; positive values mean the ablation has higher error.

| Metric | Actual mean | Control prediction / MAE | Ablation prediction / MAE | Paired MAE change (95% interval) |
| --- | ---: | ---: | ---: | ---: |
| Points (236 team-games) | 22.96 | 22.15 / 7.96 | 22.16 / 8.06 | +0.108 (−0.174, +0.393) |
| Sacks taken (222 team-games) | 2.33 | 0.83 / 1.77 | 0.82 / 1.78 | +0.008 (−0.030, +0.046) |
| Turnovers (222 team-games) | 1.27 | 0.67 / 1.02 | 0.73 / 0.99 | −0.031 (−0.066, +0.003) |

Player workload scoring includes only players with positive observed carries or targets. Missing or zero-touch rows are not treated as confirmed inactive.

| Workload | Positive observed rows | Matched predictions | Missing predictions | Control MAE | Ablation MAE | Paired MAE change (95% interval) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Carries | 932 | 853 | 79 | 3.567 | 3.593 | +0.027 (−0.036, +0.092) |
| Targets | 1,884 | 1,711 | 173 | 2.185 | 2.200 | +0.019 (−0.006, +0.044) |

The exported records contain a non-null player snap value in 9,520 of 461,840 player rows (2.1%). Snap counts are too sparse here for a reliable player-snap grading result. Roster and game-day eligibility remain unknown where the saved records do not provide verified evidence.

## Conclusion

This 118-game retrospective evaluation does not support removing `team_offense_defense_outcomes` from V1.5. The control has better aggregate winner scores, points CRPS, points MAE, sack MAE, and workload MAE. The ablation has a small descriptive improvement in turnover MAE. All reported paired intervals include zero, so these results do not establish a decisive predictive difference. Keep the unchanged V1.5 configuration as the control; do not promote the ablation from this run.

This cohort is retrospective and development-exposed, not a locked holdout. It tests the event-multiplier ablation only; it does not validate the broader SLC strength model.

## Reproducibility files

- [`EVALUATION-119.json`](EVALUATION-119.json): full grading output, including per-game/team/player scored rows.
- [`FINAL-PROGRESS.json`](FINAL-PROGRESS.json): final runner manifest with all 119 completed games and both failures.
- [`SAFETY-FAILURE-ANALYSIS-2026-11-11.md`](SAFETY-FAILURE-ANALYSIS-2026-11-11.md): preserved failure diagnosis and seed identities.
- Grader: `scripts/nfl_sequence/grade_v15_outcome_ablation_cohort.py`, SHA-256 `3f3227b4c6d9f12863801b1de154d2273939c96b5fb383a228d00e48731b3766`.
- Fast-host run directory: `/root/ot-sim-out/slc-v15-outcome-ablation-121-2026-11-11`.
- Cohort: 2026 Weeks 1–8; seeds 2–21; season adaptation N0=4; RNG-v2 paired streams; five ordinary blocker fixes; no optional layers.
