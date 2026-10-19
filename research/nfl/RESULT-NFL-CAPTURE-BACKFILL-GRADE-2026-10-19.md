# NFL capture backfill grade — 2026-10-19

## Verdict

The capture-to-grade path closes on the historical artifact, but live readiness is **FAIL CLOSED / NOT READY**. This is a reconstructed backfill, not a prospective forecast, not CP4 evidence, and not a model-adoption evaluation. No model math, market gate, threshold, serving code, scheduler, database, or production system was changed.

The frozen forecast input is `research/nfl/prospective-capture/backfill/nfl-2026-w03-w05.jsonl.gz`, SHA-256 `5804a50674ed0acc1252b58e9e5a34f80f8342cbb88760e34fe831d17bb60a83`. The grade script and machine-readable output are alongside it as `grade_capture_backfill.py` and `backfill/nfl-2026-w03-w05-grade.json`.

## Grade population and settlement mapping

The artifact has 26,638 side rows representing 13,319 paired sportsbook line-items. I verified exactly one over and one under row per line-item. The grade unit is the paired line-item: score P(over) once against the over-side outcome, and use the under side to validate complementary settlement and de-vig the quote. This avoids counting each forecast twice.

For resolved outcomes, over wins when `actual_value > line`, under wins when `actual_value < line`, and equality is a push. `true_zero` is gradeable and follows the same comparison. Each stored win/loss was independently checked against actual value and line. The gradeable population has 12,783 line-items (25,566 side rows), 359 player-games, 31 events, and weeks 4–5: 6,643 line-items in week 4 and 6,140 in week 5.

| Outcome state | Side rows | Paired line-items | Treatment |
| --- | ---: | ---: | --- |
| `resolved` | 24,524 | 12,262 | Grade |
| `true_zero` | 1,042 | 521 | Grade |
| `dnp` | 262 | 131 | Exclude both sides |
| `missing` | 810 | 405 | Exclude both sides |
| `unresolved` | 0 | 0 | Would exclude |
| `void` | 0 | 0 | Would exclude |

Settlement states across side rows were 12,783 wins and 12,783 losses, 262 DNP, and 810 missing. There were no pushes, voids, or unresolved settlements. On the over side, the gradeable items split into 6,473 wins and 6,310 losses. Thus the explicit exclusions are 536 line-items: 131 DNP and 405 missing. No row with an unavailable outcome was silently dropped.

The captured `player_game_logs:nflverse_weekly` outcome was the scoring target; `prop_results` was only a secondary check. For 12,743 of 12,783 gradeable line-items, the artifact had a book hit and actual value. Both agreed with the over-side grade on all 12,743. The remaining 40 had no stored book-result check and remained gradeable from the captured NFL outcome.

## Proper scores

The three probabilities were scored separately on the same 12,783 paired line-items:

- **v2 raw:** `p_over_raw`.
- **v2-platt:** `p_over_v2_platt`.
- **Market benchmark:** proportional de-vig of the captured over and under American prices: `implied(over) / (implied(over) + implied(under))`. This matches `grade_nfl_prop_probabilities.devig`; all scored items had both prices.

Log loss uses the repository grader's probability clipping to `[1e-9, 1-1e-9]`. The 95% percentile bootstrap resampled player-game clusters (359 clusters) and event clusters (31 clusters) separately, kept every line-item in each sampled cluster, and used the row-weighted mean. Model-minus-market deltas are paired within those same resamples. Each used 10,000 replicates; seeds were 20261019 for player-game and 20261020 for event. Deltas below are model minus market, so positive values are worse scores.

| Forecast | Brier: score; player-game CI; event CI | Log loss: score; player-game CI; event CI |
| --- | --- | --- |
| v2 raw | 0.2688; [0.2539, 0.2842]; [0.2545, 0.2841] | 0.7359; [0.7036, 0.7695]; [0.7051, 0.7693] |
| v2-platt | 0.2492; [0.2466, 0.2516]; [0.2465, 0.2519] | 0.6915; [0.6864, 0.6964]; [0.6862, 0.6969] |
| Market, no-vig | 0.2468; [0.2452, 0.2483]; [0.2450, 0.2485] | 0.6867; [0.6835, 0.6898]; [0.6831, 0.6902] |

| Model minus market | Brier delta: player-game CI; event CI | Log-loss delta: player-game CI; event CI |
| --- | --- | --- |
| v2 raw | +0.0220; [+0.0070, +0.0375]; [+0.0078, +0.0374] | +0.0493; [+0.0167, +0.0829]; [+0.0187, +0.0831] |
| v2-platt | +0.0024; [-0.0006, +0.0052]; [-0.0009, +0.0057] | +0.0048; [-0.0011, +0.0104]; [-0.0018, +0.0115] |

The raw v2 scores are worse than the market on both measures in this backfill. The v2-platt point estimates are also worse, while its paired intervals span zero. This is a comparison against a market benchmark, not an adoption argument; the sample is historical and selected by the captured backfill population.

### Per-market population and scores

Each score triplet is ordered **raw / v2-platt / market**. Exclusions are paired line-items, shown as DNP / missing. Per-market values are point estimates; the bootstrap intervals above are for the full gradeable population.

| Market | Captured / gradeable items | Player-games / events | Week 4 / week 5 gradeable | Excluded DNP / missing | Brier raw / Platt / market | Log loss raw / Platt / market |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Pass attempts | 356 / 356 | 50 / 30 | 184 / 172 | 0 / 0 | 0.2577 / 0.2499 / 0.2495 | 0.7082 / 0.6929 / 0.6922 |
| Pass completions | 304 / 304 | 50 / 30 | 155 / 149 | 0 / 0 | 0.2755 / 0.2512 / 0.2493 | 0.7482 / 0.6957 / 0.6918 |
| Passing touchdowns | 313 / 313 | 50 / 30 | 158 / 155 | 0 / 0 | 0.2308 / 0.2433 / 0.2436 | 0.6520 / 0.6796 / 0.6800 |
| Passing yards | 2,576 / 2,576 | 50 / 30 | 1,251 / 1,325 | 0 / 0 | 0.2804 / 0.2522 / 0.2449 | 0.7591 / 0.6976 / 0.6827 |
| Receiving yards | 7,622 / 7,232 | 309 / 31 | 3,822 / 3,410 | 102 / 288 | 0.2650 / 0.2487 / 0.2480 | 0.7276 / 0.6905 / 0.6892 |
| Receptions | 2,148 / 2,002 | 305 / 31 | 1,073 / 929 | 29 / 117 | 0.2745 / 0.2475 / 0.2445 | 0.7522 / 0.6881 / 0.6821 |

There are no captured targets rows. No carries market is present.

## Integerization discrepancy

The measurement is **confirmed**. On all 26,638 side rows, I recomputed integer-PMF P(over) as the sum of stored PMF mass at integer support values strictly greater than the line, then subtracted it from `p_over_raw`:

- Mean: **+0.00385971**.
- Population SD: **0.00352681**.
- Minimum: **0.00000** (no negative differences beyond floating-point noise).
- Maximum: **+0.02125**.
- Positive rows: 20,392; zero within `1e-12`: 6,246.

All lines in this artifact end in `.5`. The positive difference occurs only on yardage markets: receiving yards has mean +0.00602676 and max +0.02125; passing yards has mean +0.00212403 and max +0.005. Integer-valued receptions, attempts, completions, and passing touchdowns agree with the raw probability to floating-point precision. The 6,246 zero rows are those four count markets plus four receiving-yard rows with no sample mass in the affected fractional interval.

The reason is the stored yardage transform `X = floor(Y)`. The route's raw probability is `P(Y > k + 0.5)` on the unrounded continuous Gamma draws. The integer PMF answers `P(floor(Y) > k + 0.5)`, which is `P(Y >= k + 1)`. Draws in `(k + 0.5, k + 1)` contribute to the raw route probability but are placed at integer support value `k` by floor. This is a recording/distribution-representation mismatch, not a defect in the model calculation. The model and integerization remain unchanged.

### Which probability CP4 should grade

CP4 must grade the frozen scalar probability for the explicitly selected model version, never reconstruct it from the integerized PMF. In this artifact all 26,638 rows have `forecast_label=v2-platt` and calibration status `applied`; therefore, if this version is the evaluation target, its field is **`p_over_v2_platt`**. `p_over_raw` is the separate raw-v2 forecast and must remain a separate score.

There is a field-label hazard to resolve before live capture: `p_over_served_4dp` equals rounded raw v2 on **26,638/26,638** rows, but equals rounded v2-platt on only **4/26,638**. Do not treat that generic alias as the v2-platt probability. The version-to-field mapping must be explicit in the live CP4 consumer. This backfill cannot establish which version production currently serves.

Yes, future capture should also retain the continuous CDF representation alongside the integer PMF. The current artifact already records exact engine `p_over_raw` at each captured quote line, so that line can be graded without reconstructing it. The engine uses seeded Monte Carlo draws, not an analytic closed-form CDF; label a saved full CDF or unrounded draw representation as a **continuous empirical CDF**, and retain its draw count and seed. This makes alternate-line grading explicit without changing model math or floor integerization.

## Fail-closed live-readiness checklist

| Requirement | State |
| --- | --- |
| Backfill pairing, state mapping, scoring, benchmark odds, and clustered intervals | Proven for this historical artifact only |
| Scheduler before kickoff | Missing; no job or service is installed |
| Durable append-only forecast storage | Missing; artifacts currently live as local worktree files |
| Authorized production source | Missing; production DB was not accessed; this work used the accepted dev backfill artifact only |
| Explicit authorization for production reads, scheduler, and durable storage | Missing |
| Actual prospective pre-kickoff run and cutoff proof | Missing; every row is reconstructed backfill and CP4-ineligible |
| Unambiguous live model-version to probability-field mapping | Missing; current generic `p_over_served_4dp` is raw while every row is labeled v2-platt |

**Recommendation:** keep live capture and CP4 closed until the source and storage are authorized, durable append-only storage and the pre-kickoff scheduler are configured, one prospective run proves cutoff/lock ordering end to end, and the consumer uses the explicit probability field for the chosen model version. Nothing was installed as part of this task.

## Reproduction and artifacts

Run from the repository root:

```sh
python3 research/nfl/prospective-capture/grade_capture_backfill.py \
  research/nfl/prospective-capture/backfill/nfl-2026-w03-w05.jsonl.gz \
  --bootstrap-reps 10000 --seed 20261019 \
  --output research/nfl/prospective-capture/backfill/nfl-2026-w03-w05-grade.json
```

The grade script fails on duplicate observation IDs, unpaired sides, inconsistent actuals or settlements, mismatched paired odds, or a non-backfill/CP4-eligible input. A separate standard-library recomputation of line-item settlement, proportional de-vig, Brier, and log loss matched the output to within `1e-14`. The grade script was Python-compiled and run once for the result. The forecast artifact and DB were not modified; this task made no database writes or production reads.
