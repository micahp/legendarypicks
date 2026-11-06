# Score distributions, JAX at BAL, conditional on completed simulations

Every distribution below uses completed seeds only. Blocked seeds have no final score, so each table shows the blocked count next to it. The win bounds are for the unconditional probability over all seeds: the lower bound counts every blocked seed as a loss for that side, and the upper bound counts it as a win.

| Arm | Seeds | Completed | Blocked | Blocked rate | Ties (completed) |
|---|---:|---:|---:|---:|---:|
| v1 | 1000 | 933 | 67 | 6.7% | 0 |
| v15 | 1000 | 934 | 66 | 6.6% | 2 |
| v2 | 1000 | 924 | 76 | 7.6% | 0 |

## Scores (completed seeds)

| Arm | Measure | Median | Mean | Narrowest 80% band | Share in band |
|---|---|---:|---:|---|---:|
| v1 | BAL | 22 | 22.34 | 13 to 34 | 80.1% |
| v1 | JAX | 23 | 23.38 | 10 to 31 | 80.2% |
| v1 | total | 45 | 45.71 | 29 to 59 | 80.2% |
| v1 | margin_BAL_minus_JAX | -2 | -1.04 | -19 to 12 | 80.2% |
| v15 | BAL | 20 | 20.32 | 6 to 27 | 80.4% |
| v15 | JAX | 24 | 24.16 | 10 to 31 | 80.2% |
| v15 | total | 44 | 44.48 | 29 to 59 | 80.8% |
| v15 | margin_BAL_minus_JAX | -3 | -3.83 | -18 to 11 | 80.1% |
| v2 | BAL | 20 | 20.53 | 9 to 30 | 80.5% |
| v2 | JAX | 24 | 24.21 | 12 to 33 | 80.3% |
| v2 | total | 44 | 44.74 | 28 to 58 | 80.8% |
| v2 | margin_BAL_minus_JAX | -4 | -3.67 | -22 to 9 | 80.6% |

## BAL and JAX win probability

| Arm | BAL win, completed | BAL win bounds (all seeds) | JAX win, completed | JAX win bounds (all seeds) |
|---|---:|---|---:|---|
| v1 | 46.1% | 43.0% to 49.7% | 53.9% | 50.3% to 57.0% |
| v15 | 37.1% | 34.7% to 41.3% | 62.6% | 58.5% to 65.1% |
| v2 | 37.7% | 34.8% to 42.4% | 62.3% | 57.6% to 65.2% |

Histograms: `score_distributions.csv` (one row per arm, measure and value).
