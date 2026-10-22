# NHL Shot-to-Rebound Tracking Experiment

**Date:** 2026-10-22

**Branch:** `research/nhl-shot-to-rebound-tracking-2026-10-22`

**Status:** bounded research result; no production or NHL V3 changes

## Research question

On held-out games, do pre-shot puck, skater, and goalie-position features improve predictions of what follows a shot over a shot-event statistical baseline? The measured outcomes are goal conversion, a short-window puck-recovery proxy, recovery team, and a follow-up shot. The question is whether these tracking features add predictive information; this experiment does not simulate puck physics.

## Data and coverage

The [Big Data Cup 2026 release](https://github.com/bigdatacup/Big-Data-Cup-2026/releases/tag/Data) contains ten anonymized games: ten event files, ten shift files, 30 regulation tracking files, three overtime tracking files, and one camera-orientation file. The local manifest lists 54 assets totaling 674,203,388 bytes. This run verified every listed file name and byte size, but did not recompute the manifest SHA-256 values.

| Coverage measure | Result |
|---|---:|
| Event rows | 19,200 |
| Attempts (`Shot` + `Goal`) | 1,190 (1,132 `Shot`, 58 `Goal`) |
| Puck tracking rows tagged `Goal Score = G` | 52; no one-to-one match with the 58 event goals was verified |
| Unsuccessful shot destinations | 508 on net, 290 blocked, 334 missed |
| `Puck Recovery` events | 5,360 |
| Explicit `Save` / `Rebound` event rows | 0 / 0 |
| Per-shot recovery proxy within 3s, all attempts | 621 (295 shooting-team, 326 opponent); 569 none |
| Follow-up shots within 5s, all attempts | 174 |
| Tracking frames | 959,754 |
| Puck coverage | Exactly one puck row in every frame |
| Player rows per frame | Mean 7.75 |
| Estimated frame rate | Median 29.15 fps; 10th–90th percentile 26.06–29.80 |
| Shift rows | 7,861 |

Frame-rate estimates divide unique image frames by the integer-second game-clock span, so they are approximate. Event times are recorded to whole seconds. Tracking X/Y are in rink feet; event coordinates are camera-perspective coordinates and were kept unsigned. The shot-location features use absolute raw X/Y plus a coarse `89 - abs(X)` edge proxy; its scale was not independently validated. See the official [release README](https://github.com/bigdatacup/Big-Data-Cup-2026) for field definitions.

The tracking features require a puck and at least three tracked skaters from each team in both pre-shot clock bins. This leaves **847 of 1,190 attempts (71.2%)** across all ten games. Per-game coverage ranges from 41.3% to 86.7%. Both model arms use exactly these same rows. Among them, the shooter jersey matched a tracking row in 802 cases; the goalie was explicitly marked with a `Go` jersey in 775 cases, represented by a near-net fallback in 32, and unavailable in 40.

### Coordinate-quality caveat

The README describes puck Z as fixed at 0.02 feet except around goals. The downloaded files do not fully match that description: of 918,904 nonblank puck-Z rows, 870,287 equal 0.02 and 48,617 do not; 15,893 values are negative. The nonconstant values are concentrated in the 2025-10-17 Team F @ Team L P1/P2 files, where examples range from -27.5705 to 22.171 feet. These values may contain real height traces mixed with tracking errors, but the negative and extreme readings are not physically interpretable as supplied. Z was excluded from all models and should be quarantined pending validation. The 2D analysis therefore makes no claim that puck-height dynamics are usable.

## Comparison design

The event-only arm is a ridge logistic model using shot type, release location, traffic and one-timer indicators, manpower, score, period/clock, and preceding-event context. The movement arm adds features computed only from the two complete integer-second tracking bins before the shot clock (the bins with higher remaining-clock values): puck displacement/speed, nearest and second-nearest skaters, teammate/opponent counts within 10/20 feet, approach/closing movement, goalie location/velocity, and matched-shooter location/velocity. Both arms exclude shot destination (`Detail_2`), which records whether an unsuccessful attempt was on net, missed, or blocked.

For each outcome, predictions are out-of-game: ten-fold leave-one-game-out evaluation, with no tuning. The logistic ridge penalty is fixed at 0.2. Outcomes are read from later event rows:

- **Goal:** `Goal` versus `Shot` for the attempt.
- **Recovery:** first `Puck Recovery` within three integer game-clock seconds, before a stop, possession change, or another shot.
- **Recovery team:** no recovery, opponent recovery, or shooting-team recovery under that definition.
- **Follow-up shot:** next `Shot` or `Goal` within five integer game-clock seconds before a stop or opposing possession. All 174 labeled follow-up shots in the full event population were by the original shooting team.

The organizer defines `Puck Recovery` broadly: it can follow a missed, blocked, or saved shot, but also a dump, faceoff, or broken play. It is not a shot-linked rebound label. The recovery analysis is therefore a conservative event-sequence proxy, not a direct rebound classifier. No model predicts a recovery coordinate or time, so spatial error and predicted timing error cannot be measured; observed recovery delay has a two-second median and follow-up-shot delay a one-second median at the available event-clock resolution.

## Results

The table shows out-of-game metrics on the same 847 attempts. Mean predicted rate is included as a calibration check. Differences and intervals are **movement minus event-only**; negative values favor movement. Intervals use 2,000 paired bootstrap resamples of the ten game clusters with seed `20261022`. With only ten clusters, these intervals are exploratory and do not capture all training-set uncertainty.

| Target (positive / n) | Event-only Brier / log loss / AUC; mean p | Movement Brier / log loss / AUC; mean p | Δ Brier (95% interval) | Δ log loss (95% interval) |
|---|---|---|---:|---:|
| Goal (39 / 847) | 0.04238 / 0.17212 / 0.796; 0.05192 | 0.04226 / 0.17083 / 0.777; 0.05216 | -0.00012 [-0.00037, 0.00010] | -0.00129 [-0.00213, -0.00053] |
| Recovery within 3s (469 / 847) | 0.24902 / 0.69127 / 0.494; 0.55286 | 0.25213 / 0.69790 / 0.484; 0.55248 | +0.00311 [+0.00139, +0.00515] | +0.00663 [+0.00288, +0.01129] |
| Follow-up shot within 5s (129 / 847) | 0.12956 / 0.42837 / 0.505; 0.15521 | 0.12945 / 0.42791 / 0.526; 0.15529 | -0.00010 [-0.00110, +0.00083] | -0.00045 [-0.00454, +0.00306] |

For the three-class recovery-team target, the observed counts are 378 no recovery, 226 opponent recoveries, and 243 shooting-team recoveries. Event-only multiclass Brier/log loss are 0.65127/1.07701; movement gives 0.65951/1.09091. The movement-minus-event differences are +0.00824 (95% interval +0.00529 to +0.01145) and +0.01390 (+0.00884 to +0.01920), respectively. Marginal class frequencies are calibrated similarly in both arms; movement worsens the row-level proper scores. Conditional on a recovery (469 rows), same-team recovery Brier rises from 0.25168 to 0.25796 and log loss from 0.69663 to 0.70975.

**Interpretation:** the movement features did not improve recovery or recovery-team prediction; the paired game-bootstrap intervals support worse scores for both. Follow-up-shot differences are small and uncertain. Goal log loss favors movement in this sample, while goal Brier is inconclusive and AUC declines; with only 39 goals in the eligible sample, this is mixed evidence rather than a robust scoring improvement. Aggregate predicted rates are close to observed rates, but that does not rescue the weak discrimination or recovery results.

## Runtime and reproducibility

The final single-process run took 85.2 seconds: about 81.2 seconds to scan tracking files and 3.4 seconds for model fitting and evaluation. Bootstrap repetitions were deterministic with seed `20261022`. The source manifest's names and byte sizes passed; within-period event clock reversals were zero; each image frame had exactly one puck row. The analysis script's `--help` invocation and the full analysis run completed successfully. No test suite was run.

Machine-readable results: [`tracking_rebound_analysis.json`](../../research/nhl-shot-to-rebound-2026-10-22/results/tracking_rebound_analysis.json). Reproduction script: [`analyze_tracking_rebounds.py`](../../research/nhl-shot-to-rebound-2026-10-22/analyze_tracking_rebounds.py).

## Decision and limitations

**No-go for adopting a movement model or building a physical shot/rebound simulator from this result.** The observed 2D movement adds no demonstrated value for the key recovery targets, and the small goal log-loss result is not consistent across metrics. This is a bounded feature-ablation result, not evidence that physics can never help.

The data is useful for future research on pre-shot spatial interactions, but it does not yet establish the value of simulating shot-to-rebound physics. Main constraints are the broad recovery label, one-second event clocks, variable player coverage, event coordinates not transformed and validated against the tracking coordinate frame, absent explicit saves/rebounds, no validated tracking-error model or puck-trajectory uncertainty distribution, and the unresolved Z-coordinate anomalies. A true physical comparison needs shot-linked outcomes and subsecond sequence labels (rebound occurrence/location, recovery team/location/time, goalie contact/freeze, and the next event), plus validated coordinate uncertainty. This ten-game cross-validation is not an independent prospective or later-season evaluation. The current movement arm is a statistical classifier over 2D interaction features, not a physical rollout.

The event baseline uses the Big Data Cup event stream so its labels align with the tracking games. The separate NHL shot-event archive was not used: team labels here are anonymized, no game identity mapping has been verified, and no NHL-archive join was attempted. No starting-goalie inference or post-shot target-game locations enter the predictors; shooter-track features are matched from the shot row to pre-shot tracking only. The 2026 Big Data Cup [user agreement](https://github.com/bigdatacup/Big-Data-Cup-2026/blob/main/legal.md) restricts publicly shared research from being used for profit. The user confirmed separate written permission exists; I did not inspect or copy that permission into the repository.

This work changed no production code, live picks, Phase 2A or protected research reports. No database, ESPN, or provider-contact calls were made, and nothing was pushed.

## Robustness: regularisation and a matched null

This appendix keeps the original fixed-alpha analysis and its JSON unchanged. The original tables above use alpha = 0.2 in both arms. This robustness analysis uses nested outer leave-one-game-out evaluation: within each outer training set, alpha was selected independently for each arm by pooled inner leave-one-game-out Brier score over `{0.2, 1, 5, 20, 100, 500}`. Ties resolve to the first value in that order. Scaling, median imputation, and alpha selection are fitted using training games only. The outer held-out game does not affect any fit or choice.

The event-only design has **42 parameters including the intercept** (11 event numeric features, each with a missingness indicator; 19 categorical indicators; intercept). The movement design has **94** (the same 42 plus 26 movement values and missingness indicators). The common evaluation set remains 847 attempts from ten games. Each outer fold trains on 734–795 attempts and tests on 52–113 (mean training size 762.3, mean test size 84.7). The recovery-team conditional model fits only the recovered subset of each training fold; its exact recovered counts are shown below. Every table in this appendix uses the alpha-selected nested fits, except the matched-null table, which inherits the movement arm's selected outer-fold alpha as specified below.

### Nested metrics

Metrics are from the ten outer held-out games. Calibration is shown as observed rate versus mean prediction. Paired intervals resample the ten game clusters 2,000 times with seed `20261022`; they are exploratory with only ten clusters. Binary models each use 42 versus 94 parameters, respectively. The recovery-team model composes the nested recovery probability with a separately alpha-selected conditional same-team model of the same 42/94 parameter dimensions.

| Target (positive / n) | Arm | Observed rate | Mean prediction | Brier | Log loss | AUC |
|---|---|---:|---:|---:|---:|---:|
| Goal (39 / 847) | Event-only | 0.04604 | 0.05192 | 0.04238 | 0.17212 | 0.79586 |
| Goal (39 / 847) | Movement | 0.04604 | 0.05216 | 0.04226 | 0.17083 | 0.77716 |
| Recovery within 3s (469 / 847) | Event-only | 0.55372 | 0.54564 | 0.24821 | 0.68959 | 0.46202 |
| Recovery within 3s (469 / 847) | Movement | 0.55372 | 0.54247 | 0.24908 | 0.69136 | 0.46011 |
| Follow-up shot within 5s (129 / 847) | Event-only | 0.15230 | 0.15951 | 0.12998 | 0.43000 | 0.47979 |
| Follow-up shot within 5s (129 / 847) | Movement | 0.15230 | 0.16410 | 0.13013 | 0.43023 | 0.48923 |
| Same-team follow-up within 5s (129 / 847) | Event-only | 0.15230 | 0.15951 | 0.12998 | 0.43000 | 0.47979 |
| Same-team follow-up within 5s (129 / 847) | Movement | 0.15230 | 0.16410 | 0.13013 | 0.43023 | 0.48923 |
| Recovery team, 3 classes (847) | Event-only | — | class means below | 0.64919 | 1.07342 | — |
| Recovery team, 3 classes (847) | Movement | — | class means below | 0.65049 | 1.07520 | — |

The two follow-up labels are identical on these matched rows, so their nested predictions and scores are identical. Recovery-team observed counts are 378 no recovery, 226 opponent recovery, and 243 shooting-team recovery. Event-only mean class probabilities are 0.45436 / 0.27236 / 0.27328; movement gives 0.45753 / 0.27078 / 0.27170, in that class order.

| Target; movement minus event-only | Δ Brier (95% game-bootstrap interval) | Δ log loss (95% game-bootstrap interval) |
|---|---:|---:|
| Goal | -0.00012 [-0.00037, +0.00010] | -0.00129 [-0.00213, -0.00053] |
| Recovery within 3s | +0.00086 [-0.00012, +0.00239] | +0.00177 [-0.00024, +0.00486] |
| Follow-up shot within 5s | +0.00015 [-0.00055, +0.00088] | +0.00023 [-0.00225, +0.00276] |
| Same-team follow-up within 5s | +0.00015 [-0.00055, +0.00088] | +0.00023 [-0.00225, +0.00276] |
| Recovery team, 3 classes | +0.00130 [-0.00017, +0.00358] | +0.00177 [-0.00023, +0.00486] |

The tuned recovery and follow-up comparisons do not show a statistically supported difference from event-only under the paired game bootstrap. Goal log loss still favors movement, but goal Brier is inconclusive and AUC is lower; this remains mixed evidence with 39 goals. For recovery-team, the conditional same-team alpha is 500 in every outer fold for both arms; that strong shrinkage does not make the movement arm's small multiclass score deficit conclusive.

### Selected alpha by outer fold

Each alpha pair is event-only / movement. The model dimensions are 42 / 94 parameters in every binary table; outer training/test counts are listed per fold. The recovery-team conditional classifier also has 42 / 94 parameters and is trained only on the recovered counts listed separately. For each outcome, alpha was selected by inner LOO Brier over the nine outer-training games only.

| Held-out game | All training / test rows | Recovered training / test rows | Goal α E / M | Recovery α E / M | Follow-up α E / M | Same-team follow-up α E / M | Conditional recovery-team α E / M |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025-10-11 Team A @ Team D | 747 / 100 | 416 / 53 | 0.2 / 0.2 | 5 / 20 | 0.2 / 0.2 | 0.2 / 0.2 | 500 / 500 |
| 2025-10-17 Team F @ Team L | 771 / 76 | 429 / 40 | 0.2 / 0.2 | 1 / 1 | 1 / 1 | 1 / 1 | 500 / 500 |
| 2025-10-24 Team B @ Team A | 743 / 104 | 406 / 63 | 0.2 / 0.2 | 5 / 5 | 0.2 / 0.2 | 0.2 / 0.2 | 500 / 500 |
| 2025-10-24 Team E @ Team D | 780 / 67 | 432 / 37 | 0.2 / 0.2 | 5 / 5 | 0.2 / 1 | 0.2 / 1 | 500 / 500 |
| 2025-10-28 Team C @ Team A | 734 / 113 | 415 / 54 | 0.2 / 0.2 | 5 / 5 | 1 / 1 | 1 / 1 | 500 / 500 |
| 2025-10-29 Team G @ Team L | 772 / 75 | 429 / 40 | 0.2 / 0.2 | 5 / 5 | 0.2 / 0.2 | 0.2 / 0.2 | 500 / 500 |
| 2025-11-02 Team D @ Team A | 743 / 104 | 410 / 59 | 0.2 / 0.2 | 5 / 5 | 1 / 1 | 1 / 1 | 500 / 500 |
| 2025-11-16 Team H @ Team K | 795 / 52 | 441 / 28 | 0.2 / 0.2 | 5 / 5 | 0.2 / 1 | 0.2 / 1 | 500 / 500 |
| 2025-11-19 Team I @ Team K | 762 / 85 | 422 / 47 | 0.2 / 0.2 | 5 / 5 | 0.2 / 1 | 0.2 / 1 | 500 / 500 |
| 2025-11-28 Team J @ Team K | 776 / 71 | 421 / 48 | 0.2 / 0.2 | 5 / 20 | 0.2 / 1 | 0.2 / 1 | 500 / 500 |

The goal alpha remained at the grid's minimum, 0.2, in every fold. Recovery selected stronger shrinkage than the original 0.2 in most folds, with the movement arm selecting 20 in two folds. Follow-up selection varied by arm and fold. The conditional recovery-team model selected the grid maximum in all folds, indicating that its inner validation favored very strong shrinkage across this small population.

### Matched-null control: recovery within 3s

The 20 null replicates each independently permuted all 26 movement columns, including their missing values, across rows inside each outer training fold. Each fit retained the movement arm's 94-column design and used that fold's alpha selected from real training data by inner LOO. The held-out game's actual movement values remained untouched. Independent column permutations destroy movement-feature correlations, so this compares real features with a decorrelated movement block; it cannot isolate row alignment from the changed conditioning and shrinkage cost. It is not a separately tuned null model. Event-only paired comparisons still use the 42-parameter alpha-selected model.

| Loss delta, movement minus event-only (α per outer fold inherited from tuned movement) | Real movement delta | Null mean | Null median | Null 5th–95th percentiles | Null range | Real empirical percentile |
|---|---:|---:|---:|---:|---:|---:|
| Recovery Brier | +0.000864 | +0.000287 | +0.000253 | +0.000004 to +0.000639 | -0.000212 to +0.000726 | 100th (20/20 null deltas lower) |
| Recovery log loss | +0.001768 | +0.000577 | +0.000511 | -0.000003 to +0.001284 | -0.000433 to +0.001461 | 100th (20/20 null deltas lower) |

For both proper scores, the real movement arm is worse than all 20 independently shuffled controls. However, independently permuting the 26 columns also destroys their natural correlations, changing the conditioning of the 94-parameter design. This column-wise null cannot isolate training-row alignment from the cost of fitting a decorrelated feature block, so the difference does not identify an adverse effect of real movement alignment. Its percentile also has only 5-point resolution. The row-preserving control below addresses the correlation-structure limitation. Full replicate deltas, fold alphas, calibration bins, and metrics are in [`tracking_robustness.json`](../../research/nhl-shot-to-rebound-2026-10-22/results/tracking_robustness.json).

**Updated decision:** “Nested shrinkage removed about three quarters of the fixed-alpha recovery Brier deficit (+0.00311 to +0.00086), indicating that much of the original gap was a regularisation artifact; the real recovery delta lies inside the 200-replicate row-preserving null range, so the column-wise null's apparent harmful-alignment reading is not identified; movement still does not beat event-only on recovery Brier, tuned follow-up Brier worsens in both arms, and the recovery game-bootstrap interval includes zero, so no adverse movement effect is established.” Goal remains mixed and is not a positive claim: 39 positives, unchanged because alpha stayed at 0.2, and lower movement AUC. No model or feature candidate is selected for adoption.

The robustness computation took 112.4 seconds; the full single-process CLI invocation, including release scan and original fixed-alpha analysis, took about 3 minutes 43 seconds. BLAS/OMP thread counts were pinned to one. The existing `tracking_rebound_analysis.json` was not written; its SHA-256 matched the committed file after the run. The original robustness JSON is 77,748 bytes. No test suite was run.

### Fixed-alpha versus nested Brier scores

The fixed-alpha column uses the original results (alpha = 0.2 in both arms); nested values use the per-fold alpha selection documented above. Deltas are nested minus fixed, on the same 847 rows. Negative values mean nested shrinkage reduced Brier loss.

| Outcome | Arm | Fixed α = 0.2 Brier | Nested Brier | Nested minus fixed |
|---|---|---:|---:|---:|
| Goal | Event-only | 0.04238 | 0.04238 | 0.00000 |
| Goal | Movement | 0.04226 | 0.04226 | 0.00000 |
| Recovery within 3s | Event-only | 0.24902 | 0.24821 | -0.00081 |
| Recovery within 3s | Movement | 0.25213 | 0.24908 | -0.00305 |
| Follow-up shot within 5s | Event-only | 0.12956 | 0.12998 | +0.00042 |
| Follow-up shot within 5s | Movement | 0.12945 | 0.13013 | +0.00068 |
| Recovery team, 3 classes | Event-only | 0.65127 | 0.64919 | -0.00208 |
| Recovery team, 3 classes | Movement | 0.65951 | 0.65049 | -0.00902 |

### Recovery-team benchmark limitation

The three-class recovery-team comparison is not evidence of a near-null movement effect. Both conditional classifiers selected alpha = 500 in every outer fold and scored worse than a constant class-prior predictor from the observed counts (378 / 226 / 243): class-prior multiclass Brier 0.64733 and log loss 1.07081, versus nested event-only 0.64919 / 1.07342 and movement 0.65049 / 1.07520. The class-prior numbers use full-sample proportions and are descriptive, not an out-of-fold benchmark. Given the maximum shrinkage and neither fitted arm beating that reference, this row has no power to detect a movement effect in either direction; its +0.00130 Brier delta and interval must not be read as evidence of equivalence.

### Row-preserving matched null

The second control permutes each complete 26-feature movement vector, including its missing values, as a unit across outer-training rows. It preserves the movement block's within-vector correlations and marginal feature values while breaking the alignment with training labels and event rows. The held-out game's movement remains untouched. As in the first null, every fold uses the movement arm's alpha selected on that outer training set; no null tuning or held-out information is added. The seed schedule is `20261022 + replicate_index * 10 + sorted_game_index` (zero-based); the new null uses 200 replicates. The 94-parameter movement arm is compared with the same nested 42-parameter event-only OOF predictions.

| Loss delta (movement minus event-only) | Null construction | Reps | Real delta | Null mean | Median | P05–P95 | Min–max | Real percentile |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Recovery Brier | Independent column permutations | 20 | +0.000864 | +0.000287 | +0.000253 | +0.000004 to +0.000639 | -0.000212 to +0.000726 | 100.0 |
| Recovery Brier | Whole movement vectors | 200 | +0.000864 | +0.000371 | +0.000315 | -0.000120 to +0.001021 | -0.000245 to +0.001308 | 92.5 |
| Recovery log loss | Independent column permutations | 20 | +0.001768 | +0.000577 | +0.000511 | -0.000003 to +0.001284 | -0.000433 to +0.001461 | 100.0 |
| Recovery log loss | Whole movement vectors | 200 | +0.001768 | +0.000752 | +0.000642 | -0.000247 to +0.002066 | -0.000495 to +0.002658 | 92.5 |

The real delta is inside the whole-vector null range for both scores, though it is in the upper tail. Thus the column-wise null's outside-range result does not survive a control that preserves movement-feature correlations. Treat its apparent harmful-alignment signal as a column-wise decorrelation artifact and drop the inference that real row alignment is harmful. The row-preserving control does not show a statistically decisive movement benefit or harm; the paired game-bootstrap intervals versus event-only still include zero. This remains a ten-game research sample. The complete 200 deltas and fold alphas are in [`tracking_robustness_null2.json`](../../research/nhl-shot-to-rebound-2026-10-22/results/tracking_robustness_null2.json); that file adds the row-preserving result to the prior JSON while preserving all prior values, including the original 20-replicate null.

The row-preserving null fits took 71.8 seconds. The full invocation, including the release scan and nested recovery-fold reproduction, took 181.7 seconds with one BLAS/OMP thread and a maximum resident set of 81,600 KB. Disk availability remained 3.5 GB before and after. The original fixed-alpha and robustness JSON files were not modified. No test suite was run.
