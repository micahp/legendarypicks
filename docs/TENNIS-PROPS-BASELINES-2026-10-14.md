# Tennis player-projection baselines

- **Initial experiment:** Gate A expected service-point volume
- **Run date:** 2026-10-16
- **Database:** local `backend/data/picks.dev.db`, queried read-only
- **Status:** Gate A rejects the current simulator as the service-point exposure forecaster on the evaluated completed best-of-three population. Gate B has two distinct P0/P1 experiments: the earlier E2-based result still favors ATP P1 and WTA P0; a newer direct-historical-exposure P1 variant leads its expanded development replay on all four cells. These are different model definitions and evaluation windows, so the newer result does not replace the earlier tour-specific finding or establish a promoted incumbent. Calibration, matched-sample comparison and prospective confirmation remain open.
- **Licence:** research only under the current CC BY-NC-SA source-data terms; see the [data audit](TENNIS-PROPS-DATA-AUDIT-2026-10-14.md).

## Question and scope

Does the existing point-probability and scoring model forecast each player's service-point volume better than direct
historical exposure estimates, and does service-point exposure improve direct ace/DF count forecasts? This report
compares expected service points and full service-point distributions, then evaluates direct P0/P1 ace and DF count
distributions. It does not test the event-labeled match simulator against P1 (Gate C), nor does it evaluate live
sportsbook lines.

The replay is chronological from prior records dated 2000 onward, with evaluation matches from 2015 through the latest
available 2026 rows. It uses the repository's ATP/WTA main-tour filters. Targets are completed best-of-three matches with
surface, both players' serve-point model inputs and both observed `svpt` counts. Retirements, walkovers, incomplete scores,
invalid serve totals and non-best-of-three matches are excluded. All matches sharing the same `tourney_date` are forecast
before any of them update state because this archive records event start date, not actual match time.

The point model uses the existing opponent-adjusted serve/return point rates (`K=250`, two-year player half-life), with
the surface baseline and player state available only from prior date groups. Simulator expectations average the two
opening-server cases 50/50. Direct baselines are:

1. **Player rolling:** two-year-decayed player/surface service points per completed best-of-three match, shrunk toward the
   tour/surface mean with eight pseudo-matches.
2. **Tour/surface mean:** the same prior-only, two-year-decayed surface mean for both players.

All three methods are scored on identical player-match targets. MAE is the primary expected-volume metric; RMSE and signed
bias are diagnostics. The interval is a paired normal-theory 95% interval over match-level differences in the two players'
mean absolute errors. Positive `sim - direct` means the simulator is worse. Distributional scoring will use full predictive
masses and match-cluster uncertainty as specified in the research plan.

## ATP

**35,099 matches; 70,198 player-match targets; 2015-01-04 to 2026-05-17.**

| Method | MAE (service points) | RMSE | Predicted minus observed mean |
|---|---:|---:|---:|
| Exact simulator expectation | 19.227 | 22.608 | +7.292 |
| Player rolling exposure | 17.711 | 21.535 | -0.312 |
| Tour/surface mean | 17.655 | 21.487 | -0.615 |

The simulator is worse than the player-rolling direct baseline by **1.516 service points MAE** (paired 95% interval
**+1.443 to +1.589**). It is worse than the tour/surface mean by **1.572 points** (95% interval **+1.497 to +1.647**).
Its mean forecast is about 7.3 service points per player above the observed mean, while the direct baselines have little
overall bias.

The tour/surface mean has slightly lower MAE than the player-rolling estimate: by 0.056 points on ATP (paired 95% interval
for surface mean minus rolling: -0.076 to -0.036) and 0.078 on WTA (-0.099 to -0.058). The rolling estimate has smaller
absolute mean bias and slightly lower RMSE. Keep both for distributional comparison; this small mean-metric difference is
not a reason to over-tune the direct baseline.

| Test year | Matches | Simulator MAE | Player-rolling MAE | Difference (sim - rolling) | Paired 95% interval |
|---:|---:|---:|---:|---:|---:|
| 2015 | 2,979 | 19.391 | 17.772 | +1.620 | +1.330 to +1.909 |
| 2016 | 2,891 | 19.305 | 17.509 | +1.797 | +1.520 to +2.073 |
| 2017 | 2,884 | 19.421 | 17.737 | +1.684 | +1.410 to +1.958 |
| 2018 | 3,237 | 19.171 | 17.748 | +1.424 | +1.177 to +1.670 |
| 2019 | 3,200 | 18.856 | 17.527 | +1.329 | +1.093 to +1.565 |
| 2020 | 1,562 | 19.483 | 17.957 | +1.526 | +1.183 to +1.870 |
| 2021 | 3,196 | 19.450 | 17.885 | +1.564 | +1.330 to +1.799 |
| 2022 | 3,377 | 19.513 | 17.977 | +1.536 | +1.309 to +1.764 |
| 2023 | 3,447 | 19.002 | 17.644 | +1.358 | +1.136 to +1.580 |
| 2024 | 3,570 | 19.047 | 17.595 | +1.452 | +1.233 to +1.670 |
| 2025 | 3,190 | 18.999 | 17.611 | +1.388 | +1.164 to +1.612 |
| 2026 partial | 1,566 | 19.337 | 17.668 | +1.669 | +1.344 to +1.994 |

The expected-volume result is consistently unfavorable to the simulator across every ATP test year and the hard, clay and
grass segments. It overpredicts mean exposure by roughly seven points per player. That is a clear **no-promotion for the
current simulator's expected service-point output**. It is not a reason to stop P0/P1: use direct exposure as the incumbent
while checking whether a corrected or improved opportunity model can close the gap.

### ATP service-point distributions

Each forecast uses 50 complete match trajectories with a randomized opening server. The direct forecast is the exact
two-year-decayed empirical player/surface count distribution, mixed toward a tour/surface empirical prior with eight
pseudo-matches. Simulator CRPS uses the unbiased empirical U-statistic; direct CRPS uses the exact discrete mass. Coverage
uses central equal-tail intervals. The reported paired interval is normal-theory over match-level score differences and
does not include Monte Carlo seed variation.

| Matches | Seed | Simulator CRPS | Direct CRPS | Sim minus direct CRPS (95% interval) |
|---:|---:|---:|---:|---:|
| 35,099 | 20261016 | 12.842 | 12.214 | +0.628 (+0.574 to +0.682) |
| 35,099 | 20261017 | 12.814 | 12.214 | +0.600 (+0.546 to +0.654) |

Lower CRPS is better. The simulator also under-covers its nominal intervals, while the direct empirical baseline is close
to nominal:

| Nominal interval | Simulator coverage | Direct coverage |
|---:|---:|---:|
| 50% | 45.7% | 51.2% |
| 80% | 74.9% | 80.3% |
| 90% | 84.4% | 89.7% |

The simulator has higher CRPS in all 12 annual folds (2015 through partial 2026) and on hard, clay and grass. Annual and
surface paired differences:

| Slice | Matches | Sim minus direct CRPS | 95% interval |
|---|---:|---:|---:|
| 2015 | 2,979 | +0.639 | +0.431 to +0.847 |
| 2016 | 2,891 | +0.730 | +0.529 to +0.931 |
| 2017 | 2,884 | +0.809 | +0.609 to +1.009 |
| 2018 | 3,237 | +0.546 | +0.364 to +0.727 |
| 2019 | 3,200 | +0.459 | +0.286 to +0.632 |
| 2020 | 1,562 | +0.716 | +0.458 to +0.974 |
| 2021 | 3,196 | +0.634 | +0.460 to +0.808 |
| 2022 | 3,377 | +0.699 | +0.526 to +0.872 |
| 2023 | 3,447 | +0.504 | +0.340 to +0.668 |
| 2024 | 3,570 | +0.678 | +0.514 to +0.842 |
| 2025 | 3,190 | +0.492 | +0.325 to +0.660 |
| 2026 partial | 1,566 | +0.790 | +0.545 to +1.035 |
| Hard | 20,470 | +0.663 | +0.591 to +0.734 |
| Clay | 11,452 | +0.636 | +0.540 to +0.732 |
| Grass | 3,177 | +0.378 | +0.210 to +0.545 |

The ATP result is stable across two independent simulation seeds: CRPS changes by 0.028, and simulated coverage changes
by less than 0.1 percentage point at each interval. Both runs clearly favor the direct empirical exposure model. Reject
the current fixed-probability simulator as the ATP service-point exposure incumbent.

## WTA

**38,635 matches; 77,270 player-match targets; 2015-01-05 to 2026-05-18.**

| Method | MAE (service points) | RMSE | Predicted minus observed mean |
|---|---:|---:|---:|
| Exact simulator expectation | 20.250 | 25.925 | +9.226 |
| Player rolling exposure | 18.036 | 24.366 | +0.042 |
| Tour/surface mean | 17.957 | 24.274 | -0.248 |

The simulator is worse than the rolling direct baseline by **2.215 service points MAE** (paired 95% interval
**+2.132 to +2.297**) and worse than the tour/surface mean by **2.293 points** (95% interval **+2.209 to +2.377**).
The mean simulator forecast is 9.226 service points per player above the observed mean. Both direct baselines are nearly
unbiased. The tour/surface mean has 0.078 lower MAE than the rolling-player estimate (paired 95% interval **-0.099 to
-0.058** for surface mean minus rolling), while rolling exposure has the lower absolute bias.

| Test year | Matches | Simulator MAE | Player-rolling MAE | Difference (sim - rolling) | Paired 95% interval |
|---:|---:|---:|---:|---:|---:|
| 2015 | 1,887 | 20.444 | 17.959 | +2.485 | +2.108 to +2.862 |
| 2016 | 3,709 | 20.603 | 17.874 | +2.729 | +2.448 to +3.010 |
| 2017 | 3,673 | 20.284 | 18.106 | +2.179 | +1.896 to +2.461 |
| 2018 | 3,855 | 19.889 | 17.549 | +2.340 | +2.070 to +2.610 |
| 2019 | 3,783 | 19.785 | 17.770 | +2.014 | +1.749 to +2.279 |
| 2020 | 1,681 | 20.134 | 18.088 | +2.046 | +1.655 to +2.437 |
| 2021 | 3,555 | 21.285 | 19.143 | +2.142 | +1.874 to +2.410 |
| 2022 | 3,593 | 19.916 | 17.873 | +2.043 | +1.783 to +2.303 |
| 2023 | 3,779 | 20.546 | 18.453 | +2.093 | +1.838 to +2.349 |
| 2024 | 3,879 | 20.292 | 18.077 | +2.215 | +1.963 to +2.467 |
| 2025 | 3,631 | 19.822 | 17.743 | +2.080 | +1.820 to +2.339 |
| 2026 partial | 1,610 | 19.849 | 17.571 | +2.279 | +1.887 to +2.670 |

The simulator loses in every WTA test year and on hard, clay and grass. The direct tour/surface mean has the lowest MAE of
the two direct mean baselines; the rolling player estimate has slightly lower absolute aggregate bias and remains a useful
comparison. The expected-volume conclusion is therefore the same on both tours: **do not promote the current simulator's
service-point expectation.**

### WTA service-point distributions

The WTA run uses the same 50-trajectory and direct empirical-distribution protocol as ATP.

| Matches | Seed | Simulator CRPS | Direct CRPS | Sim minus direct CRPS (95% interval) |
|---:|---:|---:|---:|---:|
| 38,635 | 20261016 | 13.503 | 12.422 | +1.081 (+1.021 to +1.142) |
| 38,635 | 20261017 | 13.505 | 12.422 | +1.083 (+1.023 to +1.144) |

Coverage is also low for the simulator and close to nominal for the direct distribution:

| Seed | Sim 50% | Sim 80% | Sim 90% | Direct 50% | Direct 80% | Direct 90% |
|---:|---:|---:|---:|---:|---:|---:|
| 20261016 | 44.0% | 73.0% | 82.8% | 51.0% | 80.1% | 89.6% |
| 20261017 | 43.9% | 73.0% | 82.7% | 51.0% | 80.1% | 89.6% |

Across the two seeds, WTA simulator CRPS changes by 0.002 and coverage by at most 0.13 percentage point. The direct
distribution is unchanged. Both runs clearly favor the direct baseline; reject the current fixed-probability simulator
as the WTA service-point exposure incumbent.

The simulator loses on CRPS in every WTA year and on hard, clay and grass. Annual and surface paired differences:

| Slice | Matches | Sim minus direct CRPS | 95% interval |
|---|---:|---:|---:|
| 2015 | 1,887 | +1.336 | +1.063 to +1.610 |
| 2016 | 3,709 | +1.390 | +1.184 to +1.596 |
| 2017 | 3,673 | +1.043 | +0.837 to +1.249 |
| 2018 | 3,855 | +1.125 | +0.930 to +1.320 |
| 2019 | 3,783 | +0.875 | +0.682 to +1.068 |
| 2020 | 1,681 | +0.948 | +0.661 to +1.234 |
| 2021 | 3,555 | +1.098 | +0.904 to +1.292 |
| 2022 | 3,593 | +1.011 | +0.818 to +1.203 |
| 2023 | 3,779 | +1.066 | +0.875 to +1.256 |
| 2024 | 3,879 | +1.042 | +0.854 to +1.229 |
| 2025 | 3,631 | +0.978 | +0.789 to +1.168 |
| 2026 partial | 1,610 | +1.165 | +0.876 to +1.455 |
| Hard | 24,140 | +1.155 | +1.077 to +1.232 |
| Clay | 10,083 | +1.028 | +0.909 to +1.147 |
| Grass | 4,412 | +0.801 | +0.637 to +0.966 |

Both WTA seeds favor the direct empirical exposure distribution on proper score and interval coverage. The paired
intervals shown are normal-theory match-level intervals; seed stability does not make them tournament-cluster intervals.

### Surface segments

| Tour | Surface | Matches | Simulator MAE | Player-rolling MAE | Tour/surface mean MAE | Sim minus rolling MAE (95% interval) |
|---|---|---:|---:|---:|---:|---:|
| ATP | Hard | 20,470 | 19.125 | 17.534 | 17.492 | +1.590 (+1.493 to +1.687) |
| ATP | Clay | 11,452 | 19.375 | 17.887 | 17.812 | +1.488 (+1.358 to +1.619) |
| ATP | Grass | 3,177 | 19.356 | 18.216 | 18.145 | +1.139 (+0.924 to +1.355) |
| WTA | Hard | 24,140 | 20.209 | 17.867 | 17.822 | +2.341 (+2.235 to +2.447) |
| WTA | Clay | 10,083 | 20.515 | 18.418 | 18.264 | +2.097 (+1.935 to +2.258) |
| WTA | Grass | 4,412 | 19.876 | 18.084 | 18.000 | +1.792 (+1.573 to +2.012) |

## What this establishes—and what it does not

- Expected service-point volume from the current point model and scoring simulator loses to both simple direct baselines
  on both tours, with a large positive bias. The loss persists across every test year from 2015 through the partial 2026
  season and on hard, clay and grass.
- The full-distribution replay loses to the direct empirical baseline on both tours' CRPS and under-covers all three
  reported intervals. The WTA gap is larger than ATP.
- This target-specific evidence supports routing P0/P1 through direct exposure for now. The Gate B replay below finds
  incremental historical count-distribution value from P1, but it does not show whether event-labeled match simulation
  improves on the best direct P1 model.
- The service-point Gate A decision is a no-go for the current simulator on the evaluated completed best-of-three
  population: both direct baselines win expected-volume MAE, the direct distribution wins CRPS, and simulator intervals
  under-cover. The direction is stable across two simulation seeds per tour, every year and each major surface. A deeper
  format/history-depth diagnostic remains before extending that decision beyond this evaluated population.
- The historical service-point target has now been used for development/model diagnosis on these years. Treat this run as
  development evidence, not an untouched holdout. Prospective forecasts frozen before match start remain the independent
  confirmation path.

## Gate B: direct ace and double-fault baselines

This prior-only walk-forward replay compares P0, a player count-per-match rate shrunk to the tour rate, with P1, a
player event rate per opportunity multiplied by a direct service-point exposure forecast. It covers completed main-tour
best-of-three matches from 2015 through the available part of 2026. Every model is scored on the same eligible matches
within each tour and target; the WTA double-fault sample is smaller because first-serve-in data is required to derive
second-serve opportunities.

P0 uses a two-year half-life, all-surface player rates and eight prior pseudo-matches. P1 uses the Gate A direct
player/surface service-point mean and variance, shrunk to the tour/surface exposure distribution with eight
pseudo-matches. Ace rates are per service point, shrunk toward the tour rate with 500 pseudo-points. Double-fault rates
are per second-serve opportunity (`svpt - 1stIn`), shrunk with 250 pseudo-opportunities. The first-serve-in rate used to
forecast double-fault exposure has a 200-service-point prior. These priors and rates were fixed for this replay, but the
P1 distribution that includes exposure variance was added after earlier P0/P1 outcomes had been inspected. Treat this as
iterative development evidence, not an untouched comparison.

Each target has a plug-in Poisson distribution and a wider Gamma-Poisson/negative-binomial candidate. P0's latter
integrates its Gamma rate posterior. P1's latter moment-matches extra count-mean variance from the empirical exposure
distribution and the event-rate posterior; it assumes rate and opportunity are independent. It is an approximation to
the full exposure mixture, not a point-by-point event simulation.

| Tour | Target | Matches (player-match targets) | P0 Gamma-Poisson CRPS / log score | P1 Gamma-Poisson CRPS / log score | P1 − P0 CRPS (tournament-cluster 95% interval) | Mean absolute error, P0 → P1 | P1 central 50/80/90% coverage |
|---|---|---:|---:|---:|---:|---:|---:|
| ATP | Aces | 35,099 (70,198) | 2.0505 / 2.7950 | 1.9934 / 2.6152 | −0.0571 (−0.0593 to −0.0546) | 2.834 → 2.826 | 50.5% / 76.3% / 86.7% |
| ATP | Double faults | 35,099 (70,198) | 1.1047 / 2.0422 | 1.0955 / 2.0044 | −0.0092 (−0.0099 to −0.0084) | 1.586 → 1.585 | 63.6% / 87.8% / 95.1% |
| WTA | Aces | 38,637 (77,274) | 1.2221 / 2.1133 | 1.2005 / 2.0280 | −0.0216 (−0.0228 to −0.0205) | 1.748 → 1.745 | 60.6% / 85.9% / 92.7% |
| WTA | Double faults | 38,628 (77,256) | 1.3444 / 2.2682 | 1.3308 / 2.2086 | −0.0136 (−0.0150 to −0.0124) | 1.910 → 1.912 | 62.7% / 86.3% / 94.1% |

Lower CRPS, negative log score, and mean absolute error are better. The tournament-cluster intervals use 1,000 paired
bootstrap resamples (711 ATP events and 609 WTA events). P1's CRPS improvement over P0 is present in every annual fold
from 2015 through partial 2026 and on hard, clay and grass. It also holds in the cold, middle and deep P0 history groups.
P1's Gamma-Poisson distribution has the best CRPS and log score of the four candidates for all four tour/target cells.
It also lowers Brier score at each tested count threshold (aces >=4/6/8/10; double faults >=1/2/4/6). Those fixed
thresholds are distribution diagnostics, not sportsbook lines.

The gain is primarily distributional: mean-count errors move only slightly, and WTA double-fault MAE is marginally
worse under P1. Calibration still needs work. P1 intervals over-cover for double faults on both tours and WTA aces,
while ATP ace intervals remain below nominal coverage at 80% and 90%. Treat P1 Gamma-Poisson as the leading candidate in
this direct-historical-exposure replay, not the overall direct-model winner, a production-ready projection, or a
commercially cleared model. The count targets in this replay are development evidence; prospective forecasts frozen
before play are still needed for independent confirmation.

### Threshold exceedance reliability

The current read-only dev-database replay gives the mean predicted exceedance probability versus the observed rate at
each fixed count threshold. Cells show **predicted% → observed%; calibration gap** in percentage points, where the gap is
observed minus predicted; brackets give its 95% tournament-cluster bootstrap interval (10,000 resamples). P0 and P1
refer to their Gamma-Poisson distributions. These are aggregate threshold checks, not probability-bin reliability curves.

ATP has 70,198 player-match targets across 711 tournament IDs. WTA has 77,274 ace targets and 77,256 double-fault
targets across 609 tournament IDs.

| Tour | Target | Model | >=4 (aces) / >=1 (DF) | >=6 (aces) / >=2 (DF) | >=8 (aces) / >=4 (DF) | >=10 (aces) / >=6 (DF) |
|---|---|---|---:|---:|---:|---:|
| ATP | Aces | P0 | 70.45 → 60.06; −10.39 [−11.36, −9.44] | 42.94 → 40.24; −2.70 [−3.66, −1.74] | 22.28 → 25.82; +3.54 [+2.75, +4.36] | 10.54 → 16.00; +5.46 [+4.84, +6.08] |
| ATP | Aces | P1 | 66.40 → 60.06; −6.34 [−7.29, −5.39] | 41.41 → 40.24; −1.17 [−2.15, −0.20] | 23.31 → 25.82; +2.51 [+1.71, +3.33] | 12.44 → 16.00; +3.56 [+2.95, +4.18] |
| ATP | Double faults | P0 | 91.78 → 87.39; −4.40 [−4.83, −3.97] | 72.82 → 67.10; −5.72 [−6.47, −4.98] | 29.48 → 29.67; +0.19 [−0.60, +0.97] | 7.57 → 10.63; +3.07 [+2.59, +3.55] |
| ATP | Double faults | P1 | 89.24 → 87.39; −1.85 [−2.28, −1.42] | 69.13 → 67.10; −2.03 [−2.78, −1.30] | 29.60 → 29.67; +0.08 [−0.71, +0.86] | 9.47 → 10.63; +1.16 [+0.69, +1.64] |
| WTA | Aces | P0 | 28.67 → 28.31; −0.36 [−1.10, +0.37] | 9.42 → 13.31; +3.90 [+3.41, +4.39] | 2.71 → 6.12; +3.41 [+3.11, +3.71] | 0.72 → 2.78; +2.06 [+1.88, +2.24] |
| WTA | Aces | P1 | 28.39 → 28.31; −0.09 [−0.83, +0.65] | 10.71 → 13.31; +2.61 [+2.10, +3.11] | 3.82 → 6.12; +2.30 [+1.99, +2.61] | 1.35 → 2.78; +1.43 [+1.24, +1.61] |
| WTA | Double faults | P0 | 96.24 → 93.05; −3.19 [−3.45, −2.94] | 85.27 → 79.13; −6.13 [−6.64, −5.63] | 49.09 → 45.42; −3.67 [−4.38, −2.93] | 19.40 → 21.47; +2.07 [+1.48, +2.67] |
| WTA | Double faults | P1 | 93.84 → 93.05; −0.80 [−1.04, −0.54] | 80.50 → 79.13; −1.37 [−1.88, −0.87] | 46.39 → 45.42; −0.98 [−1.68, −0.25] | 21.20 → 21.47; +0.27 [−0.32, +0.89] |

P1 narrows the average threshold calibration gap relative to P0 in these cells, but several intervals still exclude zero,
especially for ATP ace tails and WTA ace thresholds above four. This supports the earlier calibration caveat; it does
not establish prospective or sportsbook-line calibration.

#### WTA integer-threshold extension

Using the same frozen chronological replay, I evaluated every integer cutoff from **aces >=1 through >=21** and
**double faults >=1 through >=20**. The tested range ends at the last cutoff with at least 30 observed exceedances
(39 ace targets at >=21; 36 double-fault targets at >=20). `n` is the eligible target population and `hits` is the
number at or above that row's cutoff. Values are **predicted% → observed%; gap [95% cluster-bootstrap interval]** in
percentage points, where gap is observed minus predicted. Each interval uses 10,000 resamples of 609 tournament IDs.
Rows marked sparse have fewer than 100 observed hits; cutoffs above the stated ranges have fewer than 30 and are omitted.

| Ace cutoff | n | Hits | P0: predicted → observed; gap [95% CI] pp | P1: predicted → observed; gap [95% CI] pp | Tail |
|---:|---:|---:|---:|---:|---|
| >=1 | 77,274 | 60,001 | 88.00 → 77.65; −10.35 [−10.99, −9.73] | 85.51 → 77.65; −7.87 [−8.47, −7.27] | |
| >=2 | 77,274 | 43,985 | 67.32 → 56.92; −10.40 [−11.25, −9.54] | 64.17 → 56.92; −7.25 [−8.08, −6.42] | |
| >=3 | 77,274 | 31,296 | 45.89 → 40.50; −5.39 [−6.25, −4.52] | 43.98 → 40.50; −3.48 [−4.33, −2.62] | |
| >=4 | 77,274 | 21,875 | 28.67 → 28.31; −0.36 [−1.10, +0.37] | 28.39 → 28.31; −0.09 [−0.83, +0.66] | |
| >=5 | 77,274 | 15,009 | 16.81 → 19.42; +2.62 [+2.03, +3.21] | 17.64 → 19.42; +1.78 [+1.19, +2.38] | |
| >=6 | 77,274 | 10,288 | 9.42 → 13.31; +3.90 [+3.40, +4.38] | 10.71 → 13.31; +2.61 [+2.09, +3.11] | |
| >=7 | 77,274 | 7,042 | 5.11 → 9.11; +4.00 [+3.61, +4.39] | 6.41 → 9.11; +2.70 [+2.29, +3.10] | |
| >=8 | 77,274 | 4,728 | 2.71 → 6.12; +3.41 [+3.11, +3.71] | 3.82 → 6.12; +2.30 [+2.00, +2.61] | |
| >=9 | 77,274 | 3,203 | 1.41 → 4.14; +2.74 [+2.51, +2.97] | 2.27 → 4.14; +1.88 [+1.65, +2.11] | |
| >=10 | 77,274 | 2,144 | 0.72 → 2.77; +2.06 [+1.88, +2.24] | 1.35 → 2.77; +1.43 [+1.24, +1.61] | |
| >=11 | 77,274 | 1,452 | 0.36 → 1.88; +1.52 [+1.38, +1.66] | 0.80 → 1.88; +1.07 [+0.94, +1.21] | |
| >=12 | 77,274 | 983 | 0.17 → 1.27; +1.10 [+0.99, +1.21] | 0.48 → 1.27; +0.79 [+0.68, +0.90] | |
| >=13 | 77,274 | 668 | 0.08 → 0.86; +0.78 [+0.70, +0.87] | 0.29 → 0.86; +0.58 [+0.49, +0.66] | |
| >=14 | 77,274 | 447 | 0.04 → 0.58; +0.54 [+0.48, +0.61] | 0.18 → 0.58; +0.40 [+0.34, +0.47] | |
| >=15 | 77,274 | 318 | 0.02 → 0.41; +0.40 [+0.34, +0.45] | 0.11 → 0.41; +0.30 [+0.25, +0.36] | |
| >=16 | 77,274 | 211 | 0.01 → 0.27; +0.27 [+0.22, +0.31] | 0.07 → 0.27; +0.21 [+0.17, +0.25] | |
| >=17 | 77,274 | 145 | 0.00 → 0.19; +0.18 [+0.15, +0.22] | 0.04 → 0.19; +0.15 [+0.11, +0.18] | |
| >=18 | 77,274 | 105 | 0.00 → 0.14; +0.13 [+0.11, +0.16] | 0.03 → 0.14; +0.11 [+0.08, +0.14] | |
| >=19 | 77,274 | 71 | 0.00 → 0.09; +0.09 [+0.07, +0.12] | 0.02 → 0.09; +0.07 [+0.05, +0.10] | Sparse |
| >=20 | 77,274 | 57 | 0.00 → 0.07; +0.07 [+0.05, +0.10] | 0.01 → 0.07; +0.06 [+0.04, +0.08] | Sparse |
| >=21 | 77,274 | 39 | 0.00 → 0.05; +0.05 [+0.03, +0.07] | 0.01 → 0.05; +0.04 [+0.03, +0.06] | Sparse |

| Double-fault cutoff | n | Hits | P0: predicted → observed; gap [95% CI] pp | P1: predicted → observed; gap [95% CI] pp | Tail |
|---:|---:|---:|---:|---:|---|
| >=1 | 77,256 | 71,885 | 96.24 → 93.05; −3.19 [−3.45, −2.94] | 93.84 → 93.05; −0.80 [−1.05, −0.54] | |
| >=2 | 77,256 | 61,136 | 85.27 → 79.13; −6.13 [−6.63, −5.63] | 80.50 → 79.13; −1.37 [−1.87, −0.87] | |
| >=3 | 77,256 | 47,908 | 68.13 → 62.01; −6.12 [−6.79, −5.43] | 63.36 → 62.01; −1.35 [−2.02, −0.67] | |
| >=4 | 77,256 | 35,088 | 49.09 → 45.42; −3.67 [−4.39, −2.95] | 46.39 → 45.42; −0.98 [−1.68, −0.26] | |
| >=5 | 77,256 | 24,513 | 32.18 → 31.73; −0.45 [−1.14, +0.25] | 32.07 → 31.73; −0.34 [−1.02, +0.36] | |
| >=6 | 77,256 | 16,588 | 19.40 → 21.47; +2.07 [+1.50, +2.67] | 21.20 → 21.47; +0.27 [−0.30, +0.87] | |
| >=7 | 77,256 | 10,897 | 10.87 → 14.11; +3.23 [+2.78, +3.71] | 13.53 → 14.11; +0.58 [+0.11, +1.07] | |
| >=8 | 77,256 | 7,092 | 5.71 → 9.18; +3.47 [+3.11, +3.84] | 8.40 → 9.18; +0.78 [+0.42, +1.16] | |
| >=9 | 77,256 | 4,486 | 2.84 → 5.81; +2.97 [+2.70, +3.25] | 5.11 → 5.81; +0.70 [+0.42, +0.99] | |
| >=10 | 77,256 | 2,798 | 1.35 → 3.62; +2.28 [+2.07, +2.49] | 3.06 → 3.62; +0.56 [+0.35, +0.79] | |
| >=11 | 77,256 | 1,706 | 0.61 → 2.21; +1.60 [+1.44, +1.76] | 1.81 → 2.21; +0.39 [+0.23, +0.57] | |
| >=12 | 77,256 | 1,001 | 0.27 → 1.30; +1.03 [+0.92, +1.14] | 1.07 → 1.30; +0.23 [+0.11, +0.35] | |
| >=13 | 77,256 | 645 | 0.11 → 0.83; +0.72 [+0.64, +0.81] | 0.63 → 0.83; +0.21 [+0.12, +0.30] | |
| >=14 | 77,256 | 392 | 0.05 → 0.51; +0.46 [+0.40, +0.53] | 0.37 → 0.51; +0.14 [+0.07, +0.21] | |
| >=15 | 77,256 | 274 | 0.02 → 0.35; +0.34 [+0.28, +0.39] | 0.22 → 0.35; +0.13 [+0.08, +0.19] | |
| >=16 | 77,256 | 181 | 0.01 → 0.23; +0.23 [+0.19, +0.27] | 0.13 → 0.23; +0.10 [+0.06, +0.14] | |
| >=17 | 77,256 | 116 | 0.00 → 0.15; +0.15 [+0.12, +0.18] | 0.08 → 0.15; +0.07 [+0.03, +0.10] | |
| >=18 | 77,256 | 75 | 0.00 → 0.10; +0.10 [+0.07, +0.12] | 0.05 → 0.10; +0.04 [+0.02, +0.07] | Sparse |
| >=19 | 77,256 | 50 | 0.00 → 0.06; +0.06 [+0.05, +0.08] | 0.04 → 0.06; +0.03 [+0.01, +0.05] | Sparse |
| >=20 | 77,256 | 36 | 0.00 → 0.05; +0.05 [+0.03, +0.06] | 0.03 → 0.05; +0.02 [+0.00, +0.04] | Sparse |

P1 remains closer to the observed exceedance rate than P0 across these added WTA cutoffs, while ace and double-fault
tails still diverge from observed rates. Sparse-tail intervals should be read cautiously. This is a diagnostic only and
does not select a threshold.

### Reconciliation with the earlier E2-based result

The October 14 P0/P1 report used a different P1 and is not contradicted by the table above. In that experiment, P1's
expected count was the frozen E2 simulator service-point expectation multiplied by a player event rate. Its negative-
binomial dispersion was fitted using realized service-point exposure, so the forecast distribution did not carry E2's
match-level exposure uncertainty. It evaluated 2019–2026 and scored mean log probability on 53,284 ATP sides and 51,018
WTA sides per target. P0 also used different rate/shrinkage and dispersion estimates than this replay.

| Tour | Target | Earlier P0 NB log score | Earlier P1 NB log score | P1 − P0 log score | Earlier corrected E2-mixture result |
|---|---|---:|---:|---:|---|
| ATP | Aces | −2.6330 | −2.6231 | +0.0098 | X_bbin beats P0 by +0.0153 and P1 by +0.0055 |
| ATP | Double faults | −2.0521 | −2.0387 | +0.0134 | X_bbin beats P0 by +0.0195 and P1 by +0.0061 |
| WTA | Aces | −1.9872 | −2.0001 | −0.0129 | P0 remains better than X_bbin by 0.0065; X_bbin beats P1 |
| WTA | Double faults | −2.2179 | −2.2323 | −0.0144 | P0 remains the point estimate leader; X_bbin vs P0 is inconclusive (95% interval −0.0046 to +0.0010) |

Positive paired log-score differences favor the candidate. The correction integrated E2's exposure distribution with a
beta-binomial count model (`X_bbin`); it did not change the earlier P1 NB result. It improved the ATP candidate and
narrowed the WTA gap, but did not establish a WTA improvement over P0. These scores and calibration diagnostics were
preserved in the October 14 research worktree's `count-mixtures.json`; that artifact is not on `dev`.

The current replay instead forecasts exposure from prior direct player/surface service-point history and includes that
exposure variance in a moment-matched P1 Gamma-Poisson distribution. Its 2015–partial-2026 CRPS results favor P1 in all
four cells. This is useful evidence for a direct-exposure challenger, but the exposure model, count-rate specification,
P0 comparator, score and date window all changed. It cannot establish that the E2-based P1 finding has reversed or
identify which change caused the difference. Do not pool these scores or describe them as one P1 version.

**Gate B disposition:** retain the earlier versioned result for E2-based P1: ATP P1 NB beat P0 NB, while WTA P0 NB beat
P1 NB for aces and double faults. The later E2-integrated X_bbin correction is the ATP challenger, with WTA ace still
favoring P0 and WTA double-fault evidence inconclusive. Track direct-historical-exposure P1 as a separate challenger.
No additional full historical replay is needed merely to restate those findings. Before selecting a single direct-count
incumbent, compare the frozen variants on identical dates and targets, then check threshold reliability, randomized PIT,
tail and interval calibration by tour, surface, season, history depth and count band. Keep prospective, immutable grading
as the independent confirmation stream.

### Reproduction and outputs

Run `backend/tennis_props_rate_backtest.py` once per tour. It writes a row-level CSV and aggregate JSON; the full local
outputs used for the direct-exposure replay were kept under `/tmp/tennis-p0p1-{atp,wta}.*`. The earlier E2-mixture
outputs were in a separate research worktree and local scratch area, not in this branch. The source data is the local
development database opened read-only. It remains research-only under the source licence described in the data audit.

## Reproduction

The expected-volume walk-forward implementation is `backend/tennis_props_exposure_backtest.py`; full distributions use
`backend/tennis_props_exposure_distribution_backtest.py`; Gate B uses `backend/tennis_props_rate_backtest.py`. Their
output records include paired forecasts and actual targets. The exact expected service-point calculation was checked
against independent point-by-point Monte Carlo for
two serve-probability pairs and both opening-server cases; the exact expected service-point means agreed within one point
per player over 12,000 simulated matches per case. The game deuce tail uses a closed-form expectation; tiebreak tail
probability below `1e-15` is pruned using the simulator's existing tolerance.

### Cross-market Brier comparison (2022–2024)

The same 2022–2024 date-block holdout now compares match-winner, total-games, ace, and double-fault forecasts. The
direct point-derived match-winner model remains behind Elo (Brier 0.22336 vs 0.20878 raw Elo; calibrated Elo is
0.20691). The exact point simulator also loses to a non-simulation total-games distribution at each tested diagnostic
threshold for both tours. For ace and double-fault count cutoffs, the direct-exposure P1 Gamma–Poisson improves Brier
over the match-rate P0 Gamma–Poisson at most cutoffs; ATP DF ≥4 and WTA DF ≥6 are inconclusive under tournament
clustering. These cutoffs are diagnostics, not sportsbook lines. The full model scores, sample sizes, and paired
tournament-bootstrap intervals are in the [cross-target Brier report](../research/tennis/point-events/2026-10-16/prop_brier_comparison.md).

The direct match-winner calibration uses both player orders for each validation match and the complementary outcome,
so source-side ordering cannot create a side bias. Point-level ace/DF event flags were not used for the count-prop
forecasts; those use the broad main-tour match-stat archive.
