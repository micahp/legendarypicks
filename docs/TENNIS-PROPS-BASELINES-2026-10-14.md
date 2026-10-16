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
