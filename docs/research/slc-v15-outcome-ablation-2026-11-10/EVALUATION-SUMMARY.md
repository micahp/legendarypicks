# V1.5 outcome-multiplier ablation: evaluation

This grades the three saved paired matchups. It does not rerun simulations. Each arm has 20 paired RNG-v2 seeds (60 valid pairs total), and every game passed full-game validation and box-score reconciliation.

## Game winners and score distributions

“Control” is the unchanged V1.5 configuration. “Ablation” disables only `team_offense_defense_outcomes`. Home-win probabilities use the 20 simulated seeds. Score bands are empirical 10th–90th percentile ranges, rounded to whole points.

| Matchup | Actual final | Control home-win p (Brier) | Ablation home-win p (Brier) | Control projected points, home / away | Ablation projected points, home / away |
| --- | ---: | ---: | ---: | --- | --- |
| MIN–NO (NO home) | NO 13–23 MIN | 0.35 (0.123) | 0.53 (0.277) | 18.8 [6–31] / 19.6 [13–27] | 20.0 [12–27] / 20.1 [9–27] |
| SEA–DEN (DEN home) | DEN 17–14 SEA | 0.50 (0.250) | 0.35 (0.423) | 19.0 [12–24] / 19.0 [8–27] | 20.1 [12–34] / 20.8 [10–34] |
| DEN–ARI (ARI home) | ARI 16–30 DEN | 0.55 (0.303) | 0.70 (0.490) | 22.7 [15–33] / 20.2 [9–31] | 23.7 [16–31] / 19.0 [7–30] |

| Aggregate forecast metric | Control | Ablation | Ablation minus control |
| --- | ---: | ---: | ---: |
| Winner Brier (lower is better) | 0.225 | 0.397 | +0.172 |
| Winner log loss (lower is better) | 0.641 | 1.000 | +0.360 |
| Points CRPS, home | 2.824 | 3.537 | +0.713 |
| Points CRPS, away | 3.952 | 4.265 | +0.314 |

The ablation scored worse on all four aggregate measures. With only three independent real games, this is a diagnostic result, not a reliable estimate of season-wide performance.

## Team outcomes and player workload

| Metric | Actual mean | Control predicted mean / MAE | Ablation predicted mean / MAE |
| --- | ---: | ---: | ---: |
| Team points | 18.83 | 19.86 / 5.46 | 20.59 / 6.41 |
| Sacks taken | 2.33 | 0.90 / 1.53 | 0.73 / 1.61 |
| Turnovers | 1.33 | 0.72 / 1.30 | 0.91 / 1.38 |

| Positive observed player-game opportunities | Scored rows | Missing predictions | Control MAE | Ablation MAE |
| --- | ---: | ---: | ---: | ---: |
| Carries | 22 / 24 | 2 | 2.71 | 2.70 |
| Targets | 45 / 49 | 4 | 2.27 | 2.36 |

Workload errors include only player-game records with a positive observed carry or target count. A missing or zero-touch row is not treated as confirmed inactive. Carry accuracy is essentially unchanged; target error rises slightly.

## Reading this result

The ablation ran correctly, but these three matchups do not show an improvement. Control is better on winner scoring, points distributions, team points, sacks and turnovers. The ablation has nearly identical carry error and slightly worse target error. This is not enough evidence to change the V1.5 default or to make a production decision.

## Reproduction and provenance

- Simulation source commit: [`67d3f552`](https://github.com/micahp/legendarypicks/tree/research/slc-v15-outcome-ablation-source-2026-11-10). This branch publishes the exact commit recorded in the run manifests.
- Paired matrix runner: `scripts/nfl_sequence/run_paired_seed_ablation_matrix.py`; SHA-256 `715e0f98453d27e9d3dc453de7e948c7b17072106b8c883ab1a9535ee7ce4249`.
- Grader: `scripts/nfl_sequence/grade_v15_outcome_ablation_cohort.py`; source commit `e3ae3008`.
- Inputs: 2026 Weeks 5–7 saved snapshots; season adaptation enabled with N0=4; RNG-v2, seeds 2–21; five ordinary blocker fixes applied identically; no optional layer enabled.
- Treatment: the only layer difference is `team_offense_defense_outcomes` enabled in control and disabled in ablation. Team-by-down play-calling and the other V1.5 adaptations remain enabled.
- All 60 seed pairs are complete and valid. The original paired reports are unchanged. The companion [JSON evaluation](EVALUATION-SUMMARY.json) contains the grader output and scored player/team rows.

