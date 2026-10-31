# Model D clock replay — full 2022–2024 training window, 2025 holdout

**Status:** research diagnostic; Model D remains opt-in and SLC defaults are unchanged.

## Data windows and provenance

- Fit window: 2022–2024 regular season, Weeks 1–18. There were 815 source games; six named development games were excluded, leaving 809 fitted games and 103,072 fitted plays.
- Holdout: 2025 regular season, Weeks 1–18: 272 games and 1,088 quarters. The boundary classification has 785 eligible quarters, replayed 20 times each (15,700 quarter-replicates); 303 quarters lack the required observable boundary marker and are excluded from that classification.
- The exact training and holdout PBP rows were read in one SQLite read transaction: 141,830 training-window rows and 46,452 holdout rows; their ordered-row SHA-256 is `6775da6a10cf209b83c4cc542f24a875d7d0a88971c1369663ef1ffdb674ba33`. The full SQLite file hash is also recorded in the JSON, but the scoped row hash is the stable identity for the data used here.
- The 2022–2024 OOB support by quarter and clock window is unchanged from the [full-season support review](../train-2022-2024-full-season-v3/REVIEW.md). In particular, Q4 `oob_snap` support in the `>120 and <300` second window is **449 plays**: 375 completed passes, 71 runs, and 3 sacks. The 375 pass count alone is not the support denominator.

## 2025 holdout results

| Measure | Model D | Observation or interpretation |
|---|---:|---|
| Accurate quarter-end classifications | 547 / 15,700 (3.48%) | — |
| Premature quarter ends | 676 / 15,700 (4.31%) | 2.68 later observed plays lost per premature quarter, on average |
| Missed quarter ends | 14,477 / 15,700 (92.21%) | Median residual clock at the observed boundary: 101 seconds |
| `oob_snap` runoff ≤15 seconds | 98.6% | 98.1% observed (n=537) |
| `oob_ready` runoff ≤15 seconds | 3.7% | 2.6% observed (n=2,307) |

At matched observed play states, positive clock bias means Model D has more time remaining than the observed game. That bias is present throughout the game:

| Quarter | Matched play states | Mean absolute clock error | Mean bias, simulated minus observed | RMSE |
|---|---:|---:|---:|---:|
| Q1 | 152,109 | 59.03 sec | +53.79 sec | 80.10 sec |
| Q2 | 182,789 | 68.57 sec | +65.53 sec | 88.01 sec |
| Q3 | 152,889 | 64.39 sec | +59.80 sec | 85.30 sec |
| Q4 | 180,705 | 52.44 sec | +42.17 sec | 70.64 sec |

## Runoff diagnostics

The sampled mean runoff is close to the 2025 holdout mean in the broad stop classes, including classes with substantial support. This indicates that the large clock-state bias is not explained by a single broad-class mean error; conditional timing, event sequence, and quarter-end hazard behavior need further diagnosis.

| Stop class | Observed mean | Model D mean | Holdout n |
|---|---:|---:|---:|
| Clock runs | 34.83 sec | 34.97 sec | 19,045 |
| Incomplete pass | 4.72 sec | 4.78 sec | 5,617 |
| Kick | 7.21 sec | 7.01 sec | 2,470 |
| OOB ready | 35.70 sec | 33.80 sec | 2,307 |
| OOB snap | 5.81 sec | 5.40 sec | 537 |
| Sack | 34.10 sec | 34.71 sec | 1,115 |
| Score | 5.04 sec | 5.27 sec | 1,248 |
| Turnover | 8.27 sec | 8.34 sec | 429 |

These are fixed-outcome quarter replays: each replicate follows the held-out event sequence and samples only the clock. They do not establish full-game play-volume calibration; that is evaluated separately in `clock-d-games-2025-holdout-train-2022-2024-v2`.

## Rebuild

```sh
python scripts/nfl_sequence/clock_d_replay.py \
  --window holdout \
  --train-season-from 2022 --train-season-to 2024 \
  --train-week-from 1 --train-week-to 18 \
  --replicates 20 \
  --out-dir docs/research/e3/oob-policy-replay-2026-10-30/train-2022-2024-full-season-v6
```
