# NHL V3 rate variation diagnostic

Diagnostic only. This report does not select a candidate, change a gate, or alter the frozen simulator.
The analysis uses the 2021 development population (1,312 games); 2022 is excluded because it has already been exposed.
All confidence intervals use a game-ID cluster bootstrap, keeping both teams together. The 16 stored Monte Carlo draws per game are held fixed.

## Rate-path bucket audit

The frozen `quality_level` reference is 31.198301 SOG per team-game. Attack cuts are LOW at or below 0.90×, AVERAGE above 0.90× and below 1.10×, and HIGH at or above 1.10×. Defense reverses the direction: STRONG at or below 0.90× allowed, AVERAGE above 0.90× and below 1.10×, WEAK at or above 1.10×. Teams without a prior sample map to AVERAGE.

There are 1389 distinct realized eight-part rate keys across 148,665 accepted 2021 attempts. Team attack bucket counts by each club's modal pregame assignment are LOW 1, AVERAGE 27, HIGH 4. The JSON also contains every team's assignment frequency and the team-game counts in each bucket.

`state_key` contains only categorical quality levels, and `shot_rate` exponentiates a linear predictor over those dimensions. There is no continuous team-level term in the frozen rate path (`stochastic_model.py:158-208,229-238`). The current forecasts therefore cannot distinguish teams that share the same attack and opponent-defense bucket values under the same state.

## Between-team variance

| Outcome | Observed between-team variance | Frozen forecast between-team variance | Gap | Approx. additive log-scale SD for gap |
|---|---:|---:|---:|---:|
| Attempts | 18.844 | 1.966 | 16.877 | 0.0725 |
| SOG | 7.157 | 0.694 | 6.463 | 0.0804 |

For frozen forecast means, the bucket-frequency versus home-share descriptive Shapley split is 1.926 vs 0.000 variance units for attempts, with 0.040 unallocated; for SOG it is 0.662 vs 0.005, with 0.027 unallocated.
As a descriptive same-fold ceiling check, bucket frequencies plus site explain 16.691 of observed attempt team-mean variance (95% interval 13.635 to 20.309); 2.152 is unallocated. For SOG these values are 6.971 (95% interval 5.666 to 8.391) and 0.186. This fit uses the same 2021 outcomes and is descriptive-after-selection; it does not show that the frozen model can realize this relationship out of sample.

The variance gaps have game-cluster bootstrap 95% intervals: attempts [14.61183025995668, 21.54838871233349], SOG [5.580848116467589, 8.291102002078677]. The approximate log-scale SD is sqrt(gap variance) divided by the observed mean count; it is a sizing diagnostic, not a fitted latent term.

The 16.877 attempt and 6.463 SOG forecast gaps are the residuals relative to the current frozen forecasts. They are not proven variance that a continuous term must supply: the 2021 descriptive bucket projection explains most observed team-mean dispersion. The state key still cannot distinguish teams within the same buckets, but this measurement points to weak or misaligned fitted category effects and other generator structure as possibilities. No new term is implemented.

## Home-away dependence and shared tempo sensitivity

Observed attempt covariance/correlation is -44.710/-0.382; the generated mixture is -8.820/-0.119. For SOG the corresponding values are -11.460/-0.242 and -0.655/-0.019.

Regulation and OT calculate a total exponential shot-arrival clock, then choose the shooting side in proportion to its rate (`stochastic_model.py:483-488,561-566`; side allocation at `:416-426`). This is equivalent to independent team Poisson clocks. There is no shared latent tempo and no fixed cap on combined attempts. A shared positive game multiplier adds positive covariance; the arithmetic below shows that even modest variation moves the forecast toward positive dependence, opposite the observed negative covariance.

| Outcome | Shared multiplier SD/CV | Added covariance | Generated covariance after multiplier | 95% game-cluster interval |
|---|---:|---:|---:|---:|
| attempts | 0.05 | +7.948 | -0.872 | [-1.965, +0.169] |
| attempts | 0.10 | +31.790 | +22.971 | [+21.866, +24.010] |
| attempts | 0.15 | +71.528 | +62.709 | [+61.584, +63.768] |
| sog | 0.05 | +2.415 | +1.760 | [+1.276, +2.253] |
| sog | 0.10 | +9.660 | +9.005 | [+8.519, +9.495] |
| sog | 0.15 | +21.734 | +21.079 | [+20.577, +21.574] |

## Reproduction and scope

Command: `/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2b-scoring-2026-10-21/rate_variation.py --bootstrap-replicates 2000`
Analysis script SHA-256: `93248b38df63789057b0e5f0b56edc1e7cc057f6ebddb56ee8ab71e4fd6e16ca`
Pinned source scan covers 1,510,104 full-population event rows and 148,665 eligible 2021 attempts. Exact source pins, per-team values, intervals, and reproduction checks are in `rate_variation.json`.

No model, gate, promotion rule, Phase 2A result, or 2022 result was changed or tuned.
