# Tennis Brier comparison across targets

Generated from the four-archive point-event audit and the ATP/WTA chronological match-stat backtests. The shared
evaluation window is 2022–2024. Forecasts are fixed before each event-start date is added to model history. Uncertainty
is bootstrapped by tournament, keeping matches and the two player targets from one match together.

## Match winner

The winner test includes 2,749 matches with verified point histories, calibrated on 623 verified matches from 2021.
The direct point model estimates both players' point-winning probabilities and maps their difference directly to a
match-win probability without simulating scoring. Calibration now augments every match with the reversed player order
and complementary outcome, and rejects a fitted nonzero intercept. This prevents the archive's source-side ordering
from creating a preferred side: in the selected histories, side 1 won 50.9% of Grand Slam archive matches and 53.2% of
Match Charting matches.

| Model | Brier | Log loss |
| --- | ---: | ---: |
| Elo, raw | 0.20878 | 0.60866 |
| Elo, calibrated on 2021 | **0.20691** | **0.60126** |
| Point simulator, raw | 0.22273 | 0.63561 |
| Point simulator, calibrated on 2021 | 0.22370 | 0.63782 |
| Direct point logistic, side-order symmetric calibration | 0.22336 | 0.63707 |

The direct model's Brier is 0.01458 above raw Elo (95% tournament-cluster interval +0.00610 to +0.02208) and 0.01645
above calibrated Elo (+0.00962 to +0.02241). Keep Elo as the match-winner incumbent. The direct model and point
simulator are effectively tied with each other on match-winner Brier.

For the point-level target, predictions averaged within each of 3,667 matches scored 0.23411 Brier versus 0.23533 for
the surface-only baseline. The paired difference was −0.00122 (95% tournament-cluster interval −0.00140 to −0.00107).
This small point-outcome improvement did not carry through to match winners.

## Total games

These are binary exceedance Briers at diagnostic thresholds, not collected sportsbook lines. The direct challenger is a
prior-only historical distribution keyed by format, surface, and pre-match competitiveness. Positive `sim − direct`
means the non-simulation direct model scored better. Each estimate uses 10,385 ATP and 11,291 WTA matches, respectively.

| Tour | Over | Simulator Brier | Direct Brier | Simulator − direct (95% tournament-cluster CI) |
| --- | ---: | ---: | ---: | ---: |
| ATP | 18.5 | 0.19274 | 0.18357 | +0.00916 [+0.00684, +0.01147] |
| ATP | 20.5 | 0.25521 | 0.24158 | +0.01363 [+0.01072, +0.01667] |
| ATP | 22.5 | 0.26348 | 0.24853 | +0.01495 [+0.01211, +0.01776] |
| ATP | 24.5 | 0.25178 | 0.23747 | +0.01431 [+0.01149, +0.01708] |
| ATP | 26.5 | 0.22453 | 0.21210 | +0.01243 [+0.00978, +0.01469] |
| WTA | 18.5 | 0.26048 | 0.23289 | +0.02760 [+0.02413, +0.03121] |
| WTA | 20.5 | 0.27861 | 0.25054 | +0.02806 [+0.02411, +0.03205] |
| WTA | 22.5 | 0.26092 | 0.23791 | +0.02301 [+0.01926, +0.02678] |
| WTA | 24.5 | 0.24041 | 0.21944 | +0.02098 [+0.01760, +0.02417] |
| WTA | 26.5 | 0.20225 | 0.18563 | +0.01663 [+0.01387, +0.01918] |

The direct distribution beats the point simulator at all five thresholds for both tours, with all paired tournament
intervals above zero. This matches the distributional comparison: simulator CRPS was 3.5320 vs 3.3715 on ATP and 3.5577
vs 3.2669 on WTA.

## Aces and double faults

These count models use main-tour match statistics, rather than the point-event flags. P0 Gamma–Poisson models a player's
count per match; P1 adds player-specific service-point exposure (and second-serve opportunities for double faults) and
integrates exposure and event-rate uncertainty. Counts below are player-match targets; P1-minus-P0 intervals resample
tournament IDs (205 ATP, 172 WTA). Negative differences favor P1.

| Tour | Target | Player-match targets | Cutoff | P0 Gamma–Poisson Brier | P1 Gamma–Poisson Brier | P1 − P0 (95% tournament-cluster CI) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ATP | Aces | 20,788 | ≥4 | 0.20745 | 0.20016 | −0.00729 [−0.00876, −0.00583] |
| ATP | Aces | 20,788 | ≥6 | 0.19500 | 0.19301 | −0.00199 [−0.00272, −0.00128] |
| ATP | Aces | 20,788 | ≥8 | 0.15738 | 0.15551 | −0.00188 [−0.00249, −0.00133] |
| ATP | Aces | 20,788 | ≥10 | 0.11396 | 0.11105 | −0.00291 [−0.00355, −0.00228] |
| ATP | Double faults | 20,788 | ≥1 | 0.11438 | 0.11257 | −0.00181 [−0.00225, −0.00138] |
| ATP | Double faults | 20,788 | ≥2 | 0.21623 | 0.21288 | −0.00335 [−0.00441, −0.00233] |
| ATP | Double faults | 20,788 | ≥4 | 0.18410 | 0.18384 | −0.00026 [−0.00057, +0.00002] |
| ATP | Double faults | 20,788 | ≥6 | 0.08106 | 0.08056 | −0.00050 [−0.00083, −0.00014] |
| WTA | Aces | 22,506 | ≥4 | 0.16360 | 0.16275 | −0.00086 [−0.00127, −0.00041] |
| WTA | Aces | 22,506 | ≥6 | 0.09606 | 0.09514 | −0.00092 [−0.00135, −0.00053] |
| WTA | Aces | 22,506 | ≥8 | 0.05066 | 0.04966 | −0.00101 [−0.00132, −0.00067] |
| WTA | Aces | 22,506 | ≥10 | 0.02562 | 0.02498 | −0.00064 [−0.00085, −0.00044] |
| WTA | Double faults | 22,500 | ≥1 | 0.06464 | 0.06372 | −0.00093 [−0.00129, −0.00054] |
| WTA | Double faults | 22,500 | ≥2 | 0.15924 | 0.15552 | −0.00372 [−0.00482, −0.00260] |
| WTA | Double faults | 22,500 | ≥4 | 0.22034 | 0.21894 | −0.00140 [−0.00250, −0.00032] |
| WTA | Double faults | 22,500 | ≥6 | 0.15043 | 0.15035 | −0.00009 [−0.00061, +0.00042] |

The P1 count model improves Brier at most tested thresholds. The ATP double-fault ≥4 and WTA double-fault ≥6 intervals
include zero, and several other improvements are small. Treat the result as historical model-comparison evidence, not
proof of sportsbook-line value or prospective performance.

## Reading the scores

Brier scores are meaningful within the same binary target and cutoff; their raw magnitudes should not be ranked across
markets with different event rates. Match winner and total-games evaluations use verified main-tour results and point
histories. Ace and double-fault target rows come from the broader main-tour match-stat archive. The 2026 US Open and
Kalshi point captures contribute score-state and event-label checks, but they have no matched final results in the
available outcome archive and therefore do not enter these Brier tests. Match Charting Project does not label ace or
double-fault events.
