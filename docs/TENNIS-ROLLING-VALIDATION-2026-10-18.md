# Tennis rolling-origin validation and incumbent selection, 2026-10-18

- **Status:** Development evidence. This gives CP2 evidence only. It does not give CP4 (prospective) evidence, and it
  does not promote anything. CP5 is Micah's decision.
- **Data status:** The whole 2015 to 2026 window is development data. The 2023 to 2026 window has been inspected, and
  2015 to 2022 was used by the earlier replays, the total-games histogram design and the Elo choices. No year is an
  untouched holdout.
- **Protocol:** [`research/tennis/rolling/2026-10-18/PROTOCOL.md`](../research/tennis/rolling/2026-10-18/PROTOCOL.md),
  committed as `0ed74421` before any rolling result was computed. The selection rule, primary scores, references,
  the 9-of-12-years survival test and the M2 and E2 rules were all fixed there.
- **Code:** `research/tennis/rolling/2026-10-18/rolling_origin.py` (records, summaries, selection, anchors),
  `diagnostics.py` (post-hoc, not used for selection), `render_rolling_tables.py` (tables generated from JSON).
- **Branch:** `feat/tennis-track-b-2026-10-18`.

## Result in brief

| Target | Reference | Incumbent | Margin over runner-up (pooled, match-clustered 95%) | Years negative | Tour check |
|---|---|---|---|---|---|
| Match winner (Brier) | M1 Elo, K = 32 | **M2 on 2000 history** (the blend formula, not the deployed version) | −0.00120 [−0.00155, −0.00084] against M1, which is the runner-up | 12 of 12 | ATP clear; WTA interval includes zero |
| Total games (CRPS) | Direct, format only | **Direct, format, surface and competitiveness** | −0.00936 [−0.01144, −0.00737] against direct, format and surface | 12 of 12 | ATP and WTA both clear |
| Aces (CRPS) | C0, prior-year tour and surface mean | **P1 Gamma-Poisson (exposure)** | −0.03850 [−0.03930, −0.03774] against P0 Gamma-Poisson | 12 of 12 | ATP and WTA both clear |
| Double faults (CRPS) | C0 | **P1 Gamma-Poisson (exposure)** | −0.01152 [−0.01217, −0.01093] against P0 Gamma-Poisson | 12 of 12 | ATP and WTA both clear |

Negative differences favour the first-named model. Every candidate was scored on identical rows within its target.

**M2 is not promoted by its presence in the lock table.** The version that is live in `tennis_model_locks` (history from
2020-01-01) fails the rolling table. It is recorded as **unvalidated in production**, and the failure is a defect (see
"M2's fate" below).

## M2's fate

- **Deployed M2 (Elo history from 2020-01-01, `backend/tennis_daily_projections.py`).** Pooled Brier difference to M1
  is +0.01660 [+0.01565, +0.01755], and it is better than M1 in only 2 of 12 years (2025 and 2026). ATP +0.01385
  [+0.01236, +0.01529]; WTA +0.01905 [+0.01770, +0.02035]. It fails the pre-declared rule. Verdict: **unvalidated in
  production, and worse than the reference.**
- **The same blend formula with Elo history from 2000-01-01 (M2 on 2000 history).** Pooled difference to M1 is
  −0.00120 [−0.00155, −0.00084], better in 12 of 12 years. It earns the incumbent status under the pre-declared rule.
  ATP alone is −0.00218 [−0.00272, −0.00162]. WTA alone is −0.00032 [−0.00081, +0.00014], which is not clear, so the
  winner gain is an ATP result on this evidence. The absolute gain is small: about 0.12 Brier points. With tournament
  clusters (1,355 events) the pooled interval is [−0.00161, −0.00080], so the match-clustered result does not depend
  on how the clustering is done.
- **Why the deployed version fails (post-hoc diagnostic).** The two versions differ in two ways: the history start
  and whether rows without a surface update the global rating. The diagnostic separates them. The start effect (2020
  minus 2000, same rows) is +0.0178 pooled [+0.0169, +0.0187], and +0.00175 [+0.0011, +0.0024] on 2023 to 2026. The
  population effect is exactly zero, because the 2000 to 2026 main-tour window has no rows with a null surface. The
  deployed defect is the start date, not the update population.
- **What this means for the lock table.** The deployed lock version is a different model from the one that earns
  status. Keeping `tennis-global-surface-elo-blend-v2` in the lock table as if it were validated is the defect. Whether
  to stop writing it, or to pin the 2000-history version as a new prospective version, is a decision for Micah (CP5).
  Nothing has been changed in the lock table or the database.
- **Deployed M2 after warm-up.** On 2023 to 2026 alone, the deployed version is +0.00081 [−0.00007, +0.00170] against
  M1. That is not a clear loss, but it is not a clear win either. It has not earned status.

## Rolling-origin tables

Every table is generated from `research/tennis/rolling/2026-10-18/rolling_summary.json` by
`render_rolling_tables.py`. The header states the data status. Years are evaluation years; each year Y is forecast using
only information dated before Y. The pooled column pools all twelve years and both tours.

**Development data.** 2015 to 2026 has been inspected. These tables give CP2 evidence only.

<!-- generated by render_rolling_tables.py from rolling_summary.json; do not edit by hand -->

<!-- generated by render_rolling_tables.py from rolling_summary.json; do not edit by hand -->

#### Match winner: Brier per match, both tours, both sides of each row pooled

| Model | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M1 Elo (reference) | 0.21250 | 0.21582 | 0.21964 | 0.22587 | 0.22466 | 0.22358 | 0.21927 | 0.22012 | 0.22002 | 0.22170 | 0.22418 | 0.22011 | 0.22042 |
| Constant 0.5 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 |
| M2, 2000 history | 0.21177 | 0.21464 | 0.21829 | 0.22442 | 0.22270 | 0.22114 | 0.21816 | 0.21916 | 0.21935 | 0.22144 | 0.22290 | 0.21778 | 0.21923 |
| M2 as deployed (2020 history) | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.25000 | 0.24022 | 0.22880 | 0.22643 | 0.22343 | 0.22307 | 0.22350 | 0.21705 | 0.23703 |

Paired difference against the reference (candidate minus reference; negative is better), with match-clustered 95% intervals:

| Candidate | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled, 95% interval | Years negative |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Constant 0.5 | +0.03750 | +0.03418 | +0.03036 | +0.02413 | +0.02534 | +0.02642 | +0.03073 | +0.02988 | +0.02998 | +0.02830 | +0.02582 | +0.02989 | +0.02958 [+0.02834, +0.03085] | 0 of 12 |
| M2, 2000 history | -0.00072 | -0.00119 | -0.00135 | -0.00145 | -0.00197 | -0.00244 | -0.00111 | -0.00096 | -0.00067 | -0.00026 | -0.00128 | -0.00233 | -0.00120 [-0.00155, -0.00084] | 12 of 12 |
| M2 as deployed (2020 history) | +0.03750 | +0.03418 | +0.03036 | +0.02413 | +0.02534 | +0.01664 | +0.00953 | +0.00631 | +0.00341 | +0.00137 | -0.00068 | -0.00306 | +0.01660 [+0.01556, +0.01760] | 2 of 12 |

Pooled difference by tour, with match-clustered 95% intervals:

| Candidate | ATP | WTA |
|---|---:|---:|
| Constant 0.5 | +0.02525 [+0.02335, +0.02706] | +0.03342 [+0.03191, +0.03510] |
| M2, 2000 history | -0.00218 [-0.00273, -0.00162] | -0.00032 [-0.00079, +0.00015] |
| M2 as deployed (2020 history) | +0.01385 [+0.01236, +0.01529] | +0.01905 [+0.01770, +0.02035] |

Secondary metrics, pooled over both tours (not used for selection):

| Model | Log loss |
|---|---:|
| M1 Elo (reference) | 0.6315 |
| Constant 0.5 | 0.6931 |
| M2, 2000 history | 0.6282 |
| M2 as deployed (2020 history) | 0.6657 |

Sensitivity, pooled over both tours: tournament-clustered 95% interval beside the match-clustered one (PROTOCOL: sensitivity only).

| Candidate | Match-clustered 95% | Tournament-clustered 95% |
|---|---:|---:|
| Constant 0.5 | +0.02958 [+0.02834, +0.03085] | +0.02958 [+0.02816, +0.03116] |
| M2, 2000 history | -0.00120 [-0.00155, -0.00084] | -0.00120 [-0.00161, -0.00080] |
| M2 as deployed (2020 history) | +0.01660 [+0.01556, +0.01760] | +0.01660 [+0.01505, +0.01807] |


**Selection (winner).** top candidate beats the runner-up clearly and in at least 9 of 12 years. Incumbent: **M2, 2000 history**. Top candidate M2, 2000 history against runner-up M1 Elo (reference): difference -0.00120 [-0.00154, -0.00083] over 79058 matches, negative in 12 of 12 years. Tournament-clustered interval for the same margin: [-0.00160, -0.00080] over 1355 tournaments. Clearly better than the reference: M2_2000.

#### Total games: CRPS on the total, both tours, both sides of each row pooled

| Model | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Direct, format only (reference) | 3.340 | 3.289 | 3.349 | 3.317 | 3.301 | 3.382 | 3.296 | 3.328 | 3.334 | 3.288 | 3.295 | 3.289 | 3.315 |
| Direct, format and surface | 3.336 | 3.289 | 3.347 | 3.315 | 3.299 | 3.384 | 3.291 | 3.326 | 3.336 | 3.287 | 3.291 | 3.288 | 3.313 |
| Direct, format, surface and competitiveness | 3.325 | 3.278 | 3.344 | 3.313 | 3.289 | 3.369 | 3.280 | 3.317 | 3.322 | 3.274 | 3.280 | 3.279 | 3.304 |
| Point simulator (exact scoring) | 3.601 | 3.594 | 3.588 | 3.550 | 3.484 | 3.602 | 3.547 | 3.522 | 3.568 | 3.546 | 3.525 | 3.538 | 3.554 |

Paired difference against the reference (candidate minus reference; negative is better), with match-clustered 95% intervals:

| Candidate | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled, 95% interval | Years negative |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Direct, format and surface | -0.005 | -0.000 | -0.002 | -0.002 | -0.002 | +0.002 | -0.005 | -0.003 | +0.002 | -0.001 | -0.004 | -0.001 | -0.002 [-0.003, -0.001] | 10 of 12 |
| Direct, format, surface and competitiveness | -0.015 | -0.011 | -0.005 | -0.003 | -0.012 | -0.013 | -0.016 | -0.011 | -0.011 | -0.014 | -0.015 | -0.009 | -0.011 [-0.013, -0.009] | 12 of 12 |
| Point simulator (exact scoring) | +0.261 | +0.305 | +0.239 | +0.234 | +0.183 | +0.220 | +0.251 | +0.193 | +0.234 | +0.258 | +0.230 | +0.250 | +0.239 [+0.227, +0.251] | 0 of 12 |

Pooled difference by tour, with match-clustered 95% intervals:

| Candidate | ATP | WTA |
|---|---:|---:|
| Direct, format and surface | -0.002 [-0.004, -0.001] | -0.001 [-0.002, -0.000] |
| Direct, format, surface and competitiveness | -0.008 [-0.011, -0.005] | -0.014 [-0.017, -0.011] |
| Point simulator (exact scoring) | +0.165 [+0.148, +0.183] | +0.309 [+0.290, +0.326] |

Secondary metrics, pooled over both tours (not used for selection):

| Model | Log score (negative log probability of the observed total) | Mean absolute error |
|---|---:|---:|
| Direct, format only (reference) | 3.050 | 4.933 |
| Direct, format and surface | 3.051 | 4.933 |
| Direct, format, surface and competitiveness | 3.054 | 4.917 |
| Point simulator (exact scoring) | 3.133 | 5.506 |

Sensitivity, pooled over both tours: tournament-clustered 95% interval beside the match-clustered one (PROTOCOL: sensitivity only).

| Candidate | Match-clustered 95% | Tournament-clustered 95% |
|---|---:|---:|
| Direct, format and surface | -0.002 [-0.003, -0.001] | -0.002 [-0.003, -0.001] |
| Direct, format, surface and competitiveness | -0.011 [-0.013, -0.009] | -0.011 [-0.014, -0.009] |
| Point simulator (exact scoring) | +0.239 [+0.227, +0.251] | +0.239 [+0.224, +0.254] |


**Selection (games).** top candidate beats the runner-up clearly and in at least 9 of 12 years. Incumbent: **Direct, format, surface and competitiveness**. Top candidate Direct, format, surface and competitiveness against runner-up Direct, format and surface: difference -0.00936 [-0.01144, -0.00737] over 70216 matches, negative in 12 of 12 years. Tournament-clustered interval for the same margin: [-0.01159, -0.00723] over 1297 tournaments. Clearly better than the reference: direct_surface, direct_surface_competitive.

#### Aces per player-match: CRPS, both tours, both sides of each row pooled

| Model | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| C0 prior-year tour and surface mean, Poisson (reference) | 2.138 | 1.907 | 1.881 | 1.964 | 1.980 | 1.903 | 1.909 | 1.922 | 1.864 | 1.905 | 1.898 | 1.914 | 1.929 |
| P0 Gamma-Poisson | 1.749 | 1.523 | 1.570 | 1.627 | 1.632 | 1.583 | 1.587 | 1.599 | 1.583 | 1.635 | 1.663 | 1.716 | 1.616 |
| P0 Poisson | 1.753 | 1.526 | 1.573 | 1.631 | 1.636 | 1.587 | 1.591 | 1.603 | 1.586 | 1.638 | 1.666 | 1.719 | 1.620 |
| P1 Gamma-Poisson (exposure) | 1.703 | 1.489 | 1.532 | 1.591 | 1.594 | 1.541 | 1.547 | 1.558 | 1.546 | 1.599 | 1.626 | 1.670 | 1.578 |
| P1 Poisson (exposure) | 1.747 | 1.523 | 1.569 | 1.628 | 1.632 | 1.582 | 1.587 | 1.600 | 1.584 | 1.636 | 1.666 | 1.717 | 1.617 |

Paired difference against the reference (candidate minus reference; negative is better), with match-clustered 95% intervals:

| Candidate | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled, 95% interval | Years negative |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 Gamma-Poisson | -0.389 | -0.384 | -0.311 | -0.337 | -0.348 | -0.319 | -0.323 | -0.324 | -0.281 | -0.270 | -0.235 | -0.198 | -0.312 [-0.320, -0.305] | 12 of 12 |
| P0 Poisson | -0.385 | -0.381 | -0.308 | -0.333 | -0.345 | -0.315 | -0.319 | -0.320 | -0.277 | -0.267 | -0.231 | -0.195 | -0.309 [-0.316, -0.302] | 12 of 12 |
| P1 Gamma-Poisson (exposure) | -0.434 | -0.418 | -0.350 | -0.373 | -0.387 | -0.361 | -0.363 | -0.364 | -0.318 | -0.306 | -0.272 | -0.243 | -0.351 [-0.358, -0.344] | 12 of 12 |
| P1 Poisson (exposure) | -0.391 | -0.384 | -0.312 | -0.336 | -0.348 | -0.320 | -0.322 | -0.323 | -0.279 | -0.269 | -0.232 | -0.197 | -0.312 [-0.320, -0.305] | 12 of 12 |

Pooled difference by tour, with match-clustered 95% intervals:

| Candidate | ATP | WTA |
|---|---:|---:|
| P0 Gamma-Poisson | -0.392 [-0.404, -0.379] | -0.240 [-0.247, -0.234] |
| P0 Poisson | -0.387 [-0.400, -0.375] | -0.238 [-0.244, -0.232] |
| P1 Gamma-Poisson (exposure) | -0.449 [-0.462, -0.436] | -0.262 [-0.268, -0.256] |
| P1 Poisson (exposure) | -0.392 [-0.405, -0.379] | -0.239 [-0.246, -0.233] |

Secondary metrics, pooled over both tours (not used for selection):

| Model | Log score (negative log probability) |
|---|---:|
| C0 prior-year tour and surface mean, Poisson (reference) | 2.8141 |
| P0 Gamma-Poisson | 2.4378 |
| P0 Poisson | 2.4536 |
| P1 Gamma-Poisson (exposure) | 2.3075 |
| P1 Poisson (exposure) | 2.4506 |

Sensitivity, pooled over both tours: tournament-clustered 95% interval beside the match-clustered one (PROTOCOL: sensitivity only).

| Candidate | Match-clustered 95% | Tournament-clustered 95% |
|---|---:|---:|
| P0 Gamma-Poisson | -0.312 [-0.320, -0.305] | -0.312 [-0.328, -0.297] |
| P0 Poisson | -0.309 [-0.316, -0.302] | -0.309 [-0.324, -0.293] |
| P1 Gamma-Poisson (exposure) | -0.351 [-0.358, -0.344] | -0.351 [-0.366, -0.335] |
| P1 Poisson (exposure) | -0.312 [-0.320, -0.305] | -0.312 [-0.327, -0.296] |


**Selection (counts_aces).** top candidate beats the runner-up clearly and in at least 9 of 12 years. Incumbent: **P1 Gamma-Poisson (exposure)**. Top candidate P1 Gamma-Poisson (exposure) against runner-up P0 Gamma-Poisson: difference -0.03850 [-0.03930, -0.03774] over 73736 matches, negative in 12 of 12 years. Tournament-clustered interval for the same margin: [-0.04023, -0.03686] over 1320 tournaments. Clearly better than the reference: p0_poisson, p0_gamma_poisson, p1_poisson, p1_gamma_poisson.

#### Double faults per player-match: CRPS, both tours, both sides of each row pooled

| Model | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| C0 prior-year tour and surface mean, Poisson (reference) | 1.290 | 1.324 | 1.389 | 1.360 | 1.334 | 1.364 | 1.408 | 1.371 | 1.323 | 1.340 | 1.344 | 1.248 | 1.346 |
| P0 Gamma-Poisson | 1.186 | 1.226 | 1.280 | 1.245 | 1.235 | 1.249 | 1.282 | 1.230 | 1.198 | 1.211 | 1.242 | 1.129 | 1.230 |
| P0 Poisson | 1.187 | 1.228 | 1.281 | 1.247 | 1.236 | 1.251 | 1.284 | 1.231 | 1.200 | 1.212 | 1.243 | 1.130 | 1.232 |
| P1 Gamma-Poisson (exposure) | 1.175 | 1.217 | 1.267 | 1.235 | 1.223 | 1.236 | 1.269 | 1.217 | 1.186 | 1.199 | 1.232 | 1.117 | 1.219 |
| P1 Poisson (exposure) | 1.189 | 1.229 | 1.282 | 1.249 | 1.237 | 1.252 | 1.284 | 1.231 | 1.200 | 1.214 | 1.245 | 1.131 | 1.233 |

Paired difference against the reference (candidate minus reference; negative is better), with match-clustered 95% intervals:

| Candidate | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Pooled, 95% interval | Years negative |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 Gamma-Poisson | -0.105 | -0.098 | -0.110 | -0.114 | -0.099 | -0.115 | -0.126 | -0.142 | -0.125 | -0.130 | -0.102 | -0.119 | -0.116 [-0.119, -0.113] | 12 of 12 |
| P0 Poisson | -0.103 | -0.096 | -0.108 | -0.113 | -0.098 | -0.113 | -0.124 | -0.140 | -0.124 | -0.128 | -0.101 | -0.118 | -0.114 [-0.117, -0.111] | 12 of 12 |
| P1 Gamma-Poisson (exposure) | -0.115 | -0.107 | -0.123 | -0.125 | -0.110 | -0.128 | -0.139 | -0.154 | -0.137 | -0.141 | -0.112 | -0.131 | -0.127 [-0.130, -0.124] | 12 of 12 |
| P1 Poisson (exposure) | -0.102 | -0.095 | -0.108 | -0.111 | -0.097 | -0.112 | -0.124 | -0.140 | -0.123 | -0.127 | -0.099 | -0.117 | -0.113 [-0.116, -0.110] | 12 of 12 |

Pooled difference by tour, with match-clustered 95% intervals:

| Candidate | ATP | WTA |
|---|---:|---:|
| P0 Gamma-Poisson | -0.082 [-0.085, -0.078] | -0.147 [-0.151, -0.142] |
| P0 Poisson | -0.080 [-0.084, -0.077] | -0.145 [-0.150, -0.140] |
| P1 Gamma-Poisson (exposure) | -0.091 [-0.094, -0.087] | -0.160 [-0.165, -0.156] |
| P1 Poisson (exposure) | -0.080 [-0.084, -0.077] | -0.143 [-0.148, -0.138] |

Secondary metrics, pooled over both tours (not used for selection):

| Model | Log score (negative log probability) |
|---|---:|
| C0 prior-year tour and surface mean, Poisson (reference) | 2.2960 |
| P0 Gamma-Poisson | 2.1606 |
| P0 Poisson | 2.1684 |
| P1 Gamma-Poisson (exposure) | 2.1114 |
| P1 Poisson (exposure) | 2.1695 |

Sensitivity, pooled over both tours: tournament-clustered 95% interval beside the match-clustered one (PROTOCOL: sensitivity only).

| Candidate | Match-clustered 95% | Tournament-clustered 95% |
|---|---:|---:|
| P0 Gamma-Poisson | -0.116 [-0.119, -0.113] | -0.116 [-0.121, -0.111] |
| P0 Poisson | -0.114 [-0.117, -0.111] | -0.114 [-0.119, -0.109] |
| P1 Gamma-Poisson (exposure) | -0.127 [-0.130, -0.124] | -0.127 [-0.132, -0.123] |
| P1 Poisson (exposure) | -0.113 [-0.116, -0.110] | -0.113 [-0.118, -0.109] |


**Selection (counts_double_faults).** top candidate beats the runner-up clearly and in at least 9 of 12 years. Incumbent: **P1 Gamma-Poisson (exposure)**. Top candidate P1 Gamma-Poisson (exposure) against runner-up P0 Gamma-Poisson: difference -0.01152 [-0.01217, -0.01093] over 73727 matches, negative in 12 of 12 years. Tournament-clustered interval for the same margin: [-0.01235, -0.01079] over 1320 tournaments. Clearly better than the reference: p0_poisson, p0_gamma_poisson, p1_poisson, p1_gamma_poisson.

## Tour check (post-hoc, not used for selection)

The pre-declared rule uses both tours pooled. The protocol also asks that each selected margin be reported per tour.
These numbers come from `research/tennis/rolling/2026-10-18/diagnostics.json`, pooled over 2015 to 2026.

| Selected margin | ATP | WTA |
|---|---|---|
| M2 on 2000 history against M1 | −0.00218 [−0.00272, −0.00162] | −0.00032 [−0.00081, +0.00014] |
| Direct, format, surface and competitiveness against direct, format and surface | −0.00598 [−0.00806, −0.00354] | −0.01258 [−0.01560, −0.00926] |
| P1 Gamma-Poisson against P0 Gamma-Poisson, aces | −0.05708 [−0.05854, −0.05570] | −0.02162 [−0.02231, −0.02092] |
| P1 Gamma-Poisson against P0 Gamma-Poisson, double faults | −0.00918 [−0.00979, −0.00856] | −0.01365 [−0.01461, −0.01268] |

No tour sign flips. The only non-clear tour result is the winner margin on WTA.

## Secondary metrics

Secondary metrics are shown in the tables above and were not used for selection. Two points matter. On total games, the
format-only distribution has the best log score (3.0498 against 3.0545 for the selected model), while the selected
model has the best CRPS and the best mean absolute error. The CRPS choice was declared before the run, so the log-score
disagreement is recorded rather than used. For the winner, M2 on 2000 history has the lowest log loss (0.6282,
against M1 0.6315).

## Verification anchors

The run enforces these anchors and would have stopped on any mismatch. All passed.

- M1 Elo Brier on 2023 to 2026: ATP 0.22802 and WTA 0.21596, matching `docs/TENNIS-MATCH-BACKTEST-2026-10-14.md`.
- Simulator total-games CRPS on 2023 to 2026: ATP 3.5327 and WTA 3.5572, matching
  `research/tennis/total-games/2026-10-16/{atp,wta}.json`. The simulator does not depend on the histogram start.
- Gamma-Poisson replay CRPS on 2015 to 2026: ATP aces P0 2.0505 and P1 1.9934; ATP double faults P0 1.1047 and P1
  1.0955; WTA aces P0 1.2221 and P1 1.2005; WTA double faults P0 1.3444 and P1 1.3308.

Record integrity was checked on the saved arrays. Every winner and total-games row is its own cluster. Every
count cluster has exactly two rows, both from the same tour and year. No cluster mixes years or tours.

## Changes that come with the wider histogram start

The total-games histograms start in 2000 here, not 2022. Pre-2022 Grand Slam matches stay excluded, as in the source
module. On 2023 to 2026 the direct results move slightly against the earlier document:

| Model (2023 to 2026) | Earlier document | This run |
|---|---:|---:|
| ATP, direct format | 3.363 | 3.366 |
| ATP, direct, format, surface and competitiveness | 3.359 | 3.360 |
| WTA, direct format | 3.246 | 3.247 |
| WTA, direct, format, surface and competitiveness | 3.231 | 3.229 |

The simulator is unchanged. The selection margins are much larger than these shifts.

## E2: excluded

E2 is excluded from this table. The reason is the protocol's E2 rule, which requires both regeneration from committed code
and the count distributions that the candidate table needs. The second condition fails.

- The published E2 aggregates (`research/tennis/props/2026-10-14/e2-count-mixtures.json`,
  `e2-exposure-diagnostics.json`) contain the E2 P1 negative-binomial and X_bbin results, and the E2 error diagnostics.
- The code that produces those aggregates is not committed. A search of all 104 local branches for `X_bbin`, `X_thin`
  or `e2_mae` in `backend/` finds nothing. The two generators, `tennis_props_count_mixtures.py` and
  `tennis_props_diagnostics.py`, exist only uncommitted in `/root/lp-tennis-props/backend/`.
- So the count distributions cannot be recomputed from committed code, and the published aggregates cannot be checked
  against it. Regenerating the E2 mean alone would not help, because it is the count distributions that enter the table.

I did not attempt to re-fit E2, which the task rules out. E2 is therefore not a candidate here, and it is not compared on
identical rows. The exclusion is recorded in the learnings log (L32).

## Checkpoints

The same block is added to `docs/BRIEF-tennis-prediction-model.md` under "Checkpoints (2026-10-18)".

- **CP1 Baseline established: passed.** Constant 0.5 and M1 for the winner. Format-only histogram for total games.
  C0, the prior-year tour and surface rate, for aces and double faults. All are scored on identical rows.
- **CP2 Candidate validated chronologically: passed for the incumbents, on development data.** Winner: M2 on 2000
  history. Total games: direct, format, surface and competitiveness. Aces and double faults: P1 Gamma-Poisson. Each was
  fit only on information before each year, and scored with a clustered paired interval against its reference. The
  deployed M2 (2020 history) fails CP2.
- **CP3 Distribution calibrated: not passed.** P1 Gamma-Poisson is under-dispersed on ATP aces, and it has a thin upper
  tail on WTA aces (`docs/TENNIS-PROPS-CALIBRATION-2026-10-18.md`). Total-games and count calibration on the rolling
  table has not been run.
- **CP4 Prospective confirmation: not passed.** No frozen, pre-event forecast has been scored against outcomes unknown
  at the time.
- **CP5 Production integration approved: not passed.** Micah's decision. No surface, route or version has been pinned.

## What was deliberately not done

- No model was promoted, merged to `dev`, or written into the lock table. The lock table and the database were not
  changed. Nothing was deployed.
- The deployed M2 was not fixed. The defect is recorded, and the fix is a CP5 decision.
- No new features, no B5 (improved simulator), no B6 (sportsbook lines).
- E2 was not re-fitted and was not scored (see above).
- No protocol rule was changed after the results were seen. The one implementation detail, that the runner-up is the
  best model other than the top candidate, produces the same runner-up as the protocol's wording for all four targets,
  since each top candidate was also the best model overall.
- No commit was pushed. The branch on `origin` already contained `80f1162c`. The commits made in this task are local.

## Limits

- Development evidence only, on a window that has been inspected. CP4 is untouched.
- The winner gain is small in absolute terms and is an ATP result. The 50/50 blend weight is fixed, as specified in the
  live code, and was not tuned on rolling data.
- The reference for counts, C0, is weak. Beating C0 is easy for any model with player information. The decisive
  comparison is among the candidates, P0 against P1, and those margins are smaller.
- The total-games reference is itself a prior histogram. Its CRPS is close to the competitiveness model's.
- Each evaluated year is out of sample for its own forecast, but the choices (the Elo K, the 50/50 weight, the
  histogram decay and the P1 variance design) were made on earlier data from these same years.

## Reproduce

```bash
python3 -I research/tennis/rolling/2026-10-18/rolling_origin.py --db backend/data/picks.dev.db \
  --out-dir research/tennis/rolling/2026-10-18 --records-dir <scratch dir for per-row arrays>
python3 -I research/tennis/rolling/2026-10-18/diagnostics.py --db backend/data/picks.dev.db \
  --records-dir <the same scratch dir> --out research/tennis/rolling/2026-10-18/diagnostics.json
python3 -I research/tennis/rolling/2026-10-18/render_rolling_tables.py \
  --summary research/tennis/rolling/2026-10-18/rolling_summary.json \
  --out research/tennis/rolling/2026-10-18/ROLLING-TABLES.md
```

The full build ran for roughly 25 to 30 minutes of wall time (not timed precisely), most of it in the total-games
simulator. The machine had 2.1 GB available at the start of the run.
