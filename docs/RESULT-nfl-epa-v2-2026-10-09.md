# RESULT: EPA layer (SPEC A section 9), built 2026-10-09

Branch `feat/nfl-epa-efficiency` (worktree `../lp-nfl-epa`, off dev a6921c9). Dev DB only.
Nothing in prod was touched. **The SPEC A 9 gate FAILED on the 2025 holdout: version 2 is not
adopted.** The layer ships as data + measurement, not as the model.

## What was done

1. **Published EPA copied, never computed.** `nfl_pbp` now holds the nflverse play-by-play for
   2024, 2025 and 2026 (the EPA/wpa/cpoe columns are published per play; this work only
   aggregates them). Measured after ingest, from the dev DB:

   | season | plays | games | EPA null | pass_attempt=1 | weeks |
   |---|---|---|---|---|---|
   | 2024 | 47,274 | 272 | 544 | 19,224 | 1-18 |
   | 2025 | 46,452 | 272 | 544 | 18,822 | 1-18 |
   | 2026 | 11,327 | 65 | 130 | 4,585 | 1-5 (week 5 = TB@DAL only, 1 of 15 games) |

   Reconciles with the publisher: 272 REG games per season, ~46k plays per season,
   ~1.2% null EPA (kick plays), consistent across all three seasons. 0 orphan pbp game_ids
   vs `nfl_schedule` (2025 checked). All pbp game_ids join `nfl_schedule` on the same key.

2. **Ingest defect found and fixed in data.** 2025's rows had `pass_attempt`/`rush_attempt`
   NULL on every row: 2025 was ingested before those columns joined `_PLAY_COLS`, and the
   widen path (`ALTER TABLE ... ADD COLUMN`) added empty columns without refilling them.
   Re-running the idempotent ingest refilled them (18,822 pass plays). The lesson for the
   ingest: a widened table is not a refreshed one.

3. **Wiring fixed (was the 2026 gap).** `ingest_nfl_pbp_logs.py` was in no unit, no cron, no
   runner script: 2025 was a one-off hand run. Added to `scripts/nfl-availability.sh`
   (weekly, Tue 09:30 America/Chicago, after injury reports) and the unit description.
   nflverse rewrites the season file as weeks land; INSERT OR REPLACE on (game_id, play_id)
   keeps it idempotent.

4. **The model** (`backend/nfl_epa_efficiency.py`): same ridge rating structure as v1
   (`nfl_ratings.py`), fitted on team-game offensive EPA totals instead of points, blended
   walk-forward into the frozen v1 margin: `margin = (1-w)*margin_v1 + w*margin_epa`.
   Walk-forward semantics identical to `nfl_backtest.backtest_season` — proven by fixture:
   `w_blend=0` reproduces v1 margin-for-margin (test_w_zero_reproduces_version_one).
   sigma fitted from each configuration's own residuals (the A3 rule). Scored game without
   published EPA refuses loudly; a zero-play side refuses.

   9 fixture tests pass (`backend/test_nfl_epa_efficiency.py`), including the leakage test:
   planting 99-EPA plays in week 3 changes nothing in any week-3 projection.

5. **Pre-registered grid, 2024 only** (`backend/nfl_tune_epa.py`; v1 parameters frozen,
   not in the grid). Grid = w_blend {0.2..0.6} x epa_half_life {3,6,12} x epa_cap {10,14,none},
   45 configurations, every one beats v1 on 2024 (v1: Brier 0.2225, margin MAE 10.49):

   | w_blend | epa_half_life | epa_cap | sigma | Brier | log loss | margin MAE |
   |---|---|---|---|---|---|---|
   | 0.6 | 12 | 14 | 13.10 | **0.2161** | 0.6228 | 10.46 |
   | 0.6 | 6 | 14 | 13.11 | 0.2166 | 0.6238 | 10.46 |
   | 0.5 | 12 | 14 | 13.12 | 0.2169 | 0.6245 | 10.46 |
   | ... | | | | (45 rows; spread 0.2161-0.2208) | | |

   Chosen on 2024 only, by the spec tie rule: `w_blend=0.6, epa_half_life=12, epa_cap=14`
   (sigma 13.098).

## The gate (SPEC A 9): FAILED on the holdout

2025 holdout, chosen configuration, priors for both fits built from 2024 (shrink 1/3):

| model | n | Brier | log loss | margin MAE |
|---|---|---|---|---|
| blend (v2) | 255 | 0.2304 | 0.6551 | 10.73 |
| v1 (frozen) | 255 | **0.2287** | **0.6493** | **10.67** |

Pooled 2024+2025 (511 games): blend Brier 0.2232 vs v1 0.2256 — the pooled number is
dominated by 2024, which is exactly why the holdout is the gate and the pooled number is not.

Market comparison (2025, n 255): model Brier 0.2304, market 0.2137 — both models lose to the
market; the blend does not close that gap (diff CI [0.0058, 0.0278], positive = worse).

Splits (pooled rows, chosen config): weeks 2-4 the blend ties v1 (0.2665 vs 0.2664);
weeks 5-18 the blend is better on Brier (0.2134 vs 0.2163) and worse on margin MAE
(10.32 vs 10.29). No segment carries the gate.

## Verdict and what ships

- **v2 is not adopted.** Tuned on 2024, it loses to v1 on the 2025 holdout on both Brier and
  margin MAE. Per SPEC A ("stop and report if a gate fails") this is reported, not tuned away.
- What ships: the ingested 2024/2025/2026 EPA data, the weekly ingest wiring, the aggregation
  + blend module with its tests, and this grid/holdout record. `model_runs` rows for the grid
  and holdout were NOT written — recording a v2 tuning run beside the frozen v1 rows would
  read as adoption; the run is reproducible from this branch and the paste above.

## What would change the verdict (pre-registered for next attempt)

- More seasons of walk-forward (2022-2023 pbp are one ingest away) so the choice is not made
  on one tuning season.
- EPA blended with a **defensive** EPA term and pass/rush split, not only offense totals.
- EPA as an extra observation inside the points fit (not a post-hoc margin blend).
- A QB-adjustment term (SPEC A 9), which needs SPEC B's availability layer.
