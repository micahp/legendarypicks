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
