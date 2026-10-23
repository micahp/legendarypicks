# NHL joint-coherence attribution (JC-DIAG)

## Population and boundary

This is a descriptive analysis of **10 development games**, evaluated with leave-one-whole-game-out predictions. The frozen comparison has 200 rollout starts, of which 172 have group scores at +45; the one-skater training population contains 454,983 eligible windows. Horizons are ordinal Image Id suffix increments, **not seconds**. There is no independent tracking population on disk. These measurements do not license adoption, an NHL simulator claim, or a Legendary Picks probability change.

The evaluator reads the frozen M0/M1/M2 outputs and recorded target coordinates. It did not refit, resimulate, alter policies, rerun the JC decision rule, or change thresholds. The ten games remain development-only. Distances are rink-coordinate feet; intervals below are 95% whole-game cluster bootstrap percentile intervals (10,000 draws, seed `20261024`, equal game weighting). No pairs or starts were treated as independent bootstrap clusters.

## Provenance gate and correction

Before Q1–Q6, the evaluator checked the frozen JC result SHA-256 `0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c` and recomputed all seven preregistered scalars. The manager’s correction arrived before any attribution metric was run: the original **3.1037 ft** M2 one-step value was a transcription typo. The value is **3.1045 ft**, from `one_step_endpoint_radial_error_plus_15_ordinal_increments_not_seconds.models.M2.equal_game_mean_ft`; the exact artifact and recomputed value is **3.1044985489019927 ft**. This is recorded in the JSON `provenance_gate.manager_correction_before_attribution` block. Preregistration commit `02714e04ced87df97ae394387d98bb7dc0b32c93` remains unchanged.

All seven assertions passed:

| Frozen scalar | Expected | Recomputed | Result |
|---|---:|---:|---|
| One-step radial M0 (ft) | 3.2222 | 3.2222472896652037 | PASS |
| One-step radial M1 (ft) | 3.1186 | 3.1186422140690984 | PASS |
| One-step radial M2 (ft; corrected) | 3.1045 | 3.1044985489019927 | PASS |
| +45 team-spacing delta M1 (ft) | +0.9365 | +0.9365140450302766 | PASS |
| +45 team-spacing delta M2 (ft) | +0.9445 | +0.9445402815284087 | PASS |
| +45 pooled-centroid delta M1 (ft) | -1.8550 | -1.854959413051429 | PASS |
| +1 team-spacing delta M2 (ft) | +0.0139 | +0.013933067827544443 | PASS |

The evaluator is `research/nhl-multi-agent-movement-2026-10-23/attribute_joint_coherence.py`. The versioned results are `research/nhl-multi-agent-movement-2026-10-23/results/jc-attribution-jcdiag-2026-10-23-v1.json`; it records source hashes, per-start/per-game measurements, exact denominators, uncertainty, field availability, and the manager correction.

## Q1 — Team-spacing error decomposition

Signed pair bias is predicted minus observed within-team pair distance; a negative value means under-spreading. “Cell absolute” is the absolute value of each start’s mean signed pair error, averaged within game and equally across games. “Pair absolute” averages absolute error over pairs within each start before game aggregation. All 10 games contribute to the team cells. Counts are eligible pair observations across scored starts.

| Horizon | Side | Starts / pairs | Signed bias M0 / M1 / M2 (ft) | Cell absolute M0 / M1 / M2 (ft) | Paired cell-absolute delta M1 / M2 (ft) |
|---:|---|---:|---|---|---|
| +1 | Home | 200 / 1,474 | +0.0174 [-0.0034, 0.0369] / -0.0194 [-0.0404, 0.0005] / -0.0148 [-0.0373, 0.0060] | 0.1012 [0.0899, 0.1132] / 0.1067 [0.0945, 0.1214] / 0.1093 [0.0990, 0.1216] | +0.0055 [-0.0012, 0.0124] / +0.0081 [0.0010, 0.0146] |
| +1 | Away | 200 / 1,552 | +0.0211 [0.0045, 0.0372] / -0.0128 [-0.0311, 0.0050] / -0.0171 [-0.0355, 0.0016] | 0.0906 [0.0819, 0.0997] / 0.0953 [0.0851, 0.1056] / 0.1104 [0.0984, 0.1226] | +0.0047 [0.0010, 0.0090] / +0.0198 [0.0119, 0.0281] |
| +15 | Home | 190 / 1,299 | +0.3936 [0.1304, 0.6696] / -0.8193 [-1.0695, -0.5455] / -0.8189 [-1.0705, -0.5413] | 1.6051 [1.3959, 1.8551] / 1.8797 [1.5874, 2.2436] / 1.8811 [1.6004, 2.2323] | +0.2746 [0.0907, 0.4702] / +0.2761 [0.1044, 0.4573] |
| +15 | Away | 190 / 1,406 | +0.1268 [-0.0548, 0.3133] / -1.0463 [-1.2572, -0.8446] / -1.0589 [-1.2732, -0.8518] | 1.5741 [1.3621, 1.7919] / 1.8303 [1.7076, 1.9440] / 1.8410 [1.7292, 1.9492] | +0.2562 [0.1030, 0.4186] / +0.2668 [0.1079, 0.4317] |
| +30 | Home | 179 / 1,147 | +0.7249 [-0.0005, 1.4204] / -2.1466 [-2.8469, -1.4920] / -2.1586 [-2.8500, -1.5144] | 3.6302 [3.2032, 4.1001] / 4.3583 [4.0352, 4.7044] / 4.3701 [4.0533, 4.7008] | +0.7282 [0.3654, 1.0525] / +0.7399 [0.3791, 1.0584] |
| +30 | Away | 179 / 1,251 | +0.2274 [-0.1809, 0.6265] / -2.5260 [-2.8024, -2.2990] / -2.5421 [-2.8268, -2.3047] | 3.4887 [3.0614, 3.9211] / 3.9567 [3.5825, 4.4033] / 3.9646 [3.5815, 4.4206] | +0.4680 [0.1332, 0.8099] / +0.4759 [0.1253, 0.8332] |
| +45 | Home | 172 / 1,064 | +1.0368 [-0.0329, 2.1257] / -3.4369 [-4.4759, -2.3707] / -3.4572 [-4.4867, -2.4067] | 5.9954 [5.3633, 6.6632] / 6.7554 [6.2376, 7.2337] / 6.7617 [6.2502, 7.2332] | +0.7600 [0.1651, 1.3388] / +0.7663 [0.1885, 1.3380] |
| +45 | Away | 172 / 1,100 | -0.4448 [-1.3790, 0.4472] / -4.6539 [-5.3350, -3.9250] / -4.6798 [-5.3574, -3.9690] | 5.0752 [4.6423, 5.4999] / 6.1882 [5.6066, 6.7886] / 6.1980 [5.6307, 6.7918] | +1.1130 [0.5285, 1.7172] / +1.1228 [0.5554, 1.7174] |

Across both sides, paired candidate-minus-M0 increases in mean absolute per-pair error (ft) were:

| Horizon | M1 delta [95% CI] | M2 delta [95% CI] |
|---:|---:|---:|
| +1 | +0.0076 [0.0040, 0.0110] | +0.0214 [0.0145, 0.0298] |
| +15 | +0.2546 [0.1606, 0.3500] | +0.2661 [0.1740, 0.3599] |
| +30 | +0.3951 [0.2009, 0.5723] | +0.4062 [0.2237, 0.5751] |
| +45 | +0.3962 [0.1206, 0.6897] | +0.4033 [0.1394, 0.6895] |

The exact M0/M1/M2 pair-absolute estimates and intervals are retained in the JSON. No frozen cutoff player record has an explicit recognized role field: the checked fields were `position`, `position_group`, `role`, `player_role`, and `position_code`; the cutoff player schema has only `history, id, jersey, raw_id, team, x, y`. Therefore defence–defence, defence–forward, forward–forward, and role-by-team cells are non-estimable. Roles were not inferred.

## Q2 — Signed pair-error distribution

Shares and quantiles are first calculated within each start, then averaged within game and equally across games. `Over / under / tie` is the share of pairs with positive / negative / exactly zero signed distance error. Values are shares; signed quantiles and means are feet. Every tested horizon had zero exact ties. The table shows q10/q25/q50/q75/q90 point estimates; the JSON has the preregistered game-cluster interval for each share, signed mean, quantile, and absolute-error statistic.

| Horizon | Model | Over / under / tie | Signed mean [95% CI] | Signed q10 / q25 / q50 / q75 / q90 (ft) | Mean absolute error [95% CI] |
|---:|---|---|---:|---|---:|
| +1 | M0 | 0.542 / 0.458 / 0 | +0.0176 [0.0008, 0.0337] | -0.1459 / -0.0700 / +0.0143 / +0.1022 / +0.1895 | 0.1412 [0.1345, 0.1471] |
| +1 | M1 | 0.477 / 0.523 / 0 | -0.0159 [-0.0336, 0.0012] | -0.1906 / -0.1095 / -0.0168 / +0.0744 / +0.1634 | 0.1487 [0.1407, 0.1568] |
| +1 | M2 | 0.479 / 0.521 / 0 | -0.0156 [-0.0335, 0.0017] | -0.2151 / -0.1181 / -0.0159 / +0.0840 / +0.1873 | 0.1626 [0.1523, 0.1748] |
| +2 | M0 | 0.539 / 0.461 / 0 | +0.0327 [0.0052, 0.0591] | -0.3031 / -0.1397 / +0.0289 / +0.2024 / +0.3720 | 0.2810 [0.2657, 0.2975] |
| +2 | M1 | 0.463 / 0.537 / 0 | -0.0398 [-0.0692, -0.0118] | -0.4008 / -0.2230 / -0.0382 / +0.1412 / +0.3147 | 0.2970 [0.2817, 0.3120] |
| +2 | M2 | 0.462 / 0.538 / 0 | -0.0411 [-0.0710, -0.0122] | -0.4195 / -0.2361 / -0.0392 / +0.1501 / +0.3320 | 0.3088 [0.2925, 0.3252] |
| +45 | M0 | 0.507 / 0.493 / 0 | +0.1331 [-0.6971, 0.9446] | -9.6281 / -5.2925 / +0.1273 / +5.7855 / +9.8177 | 8.0549 [7.6501, 8.5039] |
| +45 | M1 | 0.339 / 0.661 / 0 | -3.9903 [-4.7455, -3.2775] | -13.5580 / -9.1900 / -3.7728 / +1.4129 / +5.5575 | 8.4511 [7.9355, 9.0044] |
| +45 | M2 | 0.338 / 0.662 / 0 | -4.0187 [-4.7652, -3.3259] | -13.5844 / -9.2175 / -3.7999 / +1.3512 / +5.5226 | 8.4582 [7.9400, 9.0112] |

At +2, compact signed mean coexists with worse absolute error because the distribution is not concentrated at zero: under-spread pairs are more common, but both tails are wider. M1/M2 absolute medians are 0.2554/0.2603 ft versus 0.2380 for M0, and absolute q90s are 0.5663/0.5973 versus 0.5425 ft. Thus positive and negative errors partly cancel in the signed mean while the absolute error rises. At +45, about 66% of candidate pair errors are negative, with median around -3.8 ft and substantial positive q75/q90 tails. This is compatible with a broadly compact mean and large absolute errors; it does not identify why the individual pairs diverge.

## Q3 — Source-axis decomposition

These are absolute coordinate-separation errors along the source X and Y axes, not an additive decomposition of Euclidean distance. Axes remain labeled X/Y: no attack-direction or longitudinal/lateral interpretation is inferred. Estimates use the equal-team aggregation; pair and start counts are common to both axes at each horizon.

| Horizon | Axis | Starts / pairs | Signed error M0 / M1 / M2 (ft) | Absolute error M0 / M1 / M2 (ft) | Paired absolute-error delta M1 / M2 (ft) |
|---:|:---:|---:|---|---|---|
| +1 | X | 200 / 3,026 | +0.0110 [0.0008, 0.0210] / -0.0052 [-0.0163, 0.0054] / -0.0069 [-0.0199, 0.0046] | 0.1102 [0.1024, 0.1185] / 0.1215 [0.1136, 0.1296] / 0.1376 [0.1269, 0.1498] | +0.0113 [0.0088, 0.0140] / +0.0274 [0.0186, 0.0381] |
| +1 | Y | 200 / 3,026 | +0.0080 [-0.0094, 0.0237] / -0.0206 [-0.0382, -0.0044] / -0.0199 [-0.0364, -0.0045] | 0.1574 [0.1485, 0.1669] / 0.1641 [0.1535, 0.1755] / 0.1743 [0.1616, 0.1870] | +0.0067 [0.0042, 0.0093] / +0.0168 [0.0110, 0.0224] |
| +15 | X | 190 / 2,705 | +0.1862 [0.0176, 0.3419] / -0.4707 [-0.6380, -0.3009] / -0.4851 [-0.6569, -0.3102] | 2.0218 [1.8558, 2.1701] / 2.3844 [2.2094, 2.5610] / 2.4034 [2.2329, 2.5757] | +0.3626 [0.2697, 0.4517] / +0.3816 [0.2865, 0.4698] |
| +15 | Y | 190 / 2,705 | +0.1360 [-0.1140, 0.3996] / -0.7503 [-1.0052, -0.4896] / -0.7527 [-1.0051, -0.4936] | 2.8894 [2.7489, 3.0288] / 2.9978 [2.8657, 3.1259] / 2.9855 [2.8505, 3.1157] | +0.1085 [0.0407, 0.1697] / +0.0961 [0.0286, 0.1597] |
| +30 | X | 179 / 2,398 | +0.2801 [-0.1585, 0.6520] / -1.3651 [-1.8009, -0.9978] / -1.3878 [-1.8474, -1.0055] | 4.4809 [4.1613, 4.8082] / 4.9207 [4.5783, 5.3281] / 4.9332 [4.5883, 5.3451] | +0.4398 [0.2653, 0.6240] / +0.4523 [0.2811, 0.6313] |
| +30 | Y | 179 / 2,398 | +0.3159 [-0.4287, 1.0805] / -1.6492 [-2.3598, -0.9312] / -1.6568 [-2.3630, -0.9425] | 5.9962 [5.6155, 6.3789] / 6.0924 [5.7352, 6.4551] / 6.0847 [5.7266, 6.4480] | +0.0963 [-0.0573, 0.2293] / +0.0885 [-0.0607, 0.2205] |
| +45 | X | 172 / 2,164 | -0.0129 [-0.4428, 0.4167] / -2.7371 [-3.1241, -2.3326] / -2.7746 [-3.1852, -2.3593] | 7.1591 [6.6913, 7.6066] / 7.3662 [6.9107, 7.8808] / 7.3735 [6.9141, 7.8949] | +0.2071 [-0.0275, 0.4281] / +0.2145 [-0.0171, 0.4351] |
| +45 | Y | 172 / 2,164 | +0.3061 [-0.8487, 1.5300] / -2.5746 [-3.5960, -1.4964] / -2.5834 [-3.5992, -1.5058] | 8.3468 [7.8752, 8.8199] / 8.2119 [7.6396, 8.7976] / 8.1989 [7.6239, 8.7878] | -0.1349 [-0.4379, 0.1239] / -0.1479 [-0.4487, 0.1110] |

The candidate signed axis errors become negative on both axes. At +45, absolute X-axis error is slightly higher for M1/M2, but the paired intervals include zero; absolute Y-axis error is slightly lower, also with intervals including zero. Earlier, the increase in absolute X error is clearer, while Y-axis absolute-error increases are smaller and become unseparated from zero by +30. This suggests the measured pair failure is not attributable to a single source axis. It is not evidence of physical lateral or longitudinal stretching.

## Q4 — Concentration of +45 spacing loss

Each entry is candidate minus M0 start-level absolute team-spacing error, averaged within game. Positive values mean larger spacing error. Both candidates have 9 positive and 1 negative game delta. The game delta lists and summaries are the ten whole-game clusters, not 172 independent game estimates.

| Game | M1 delta (ft) | M2 delta (ft) |
|---|---:|---:|
| 2025-10-11 Team A @ Team D | +1.622948 | +1.609450 |
| 2025-10-17 Team F @ Team L | -0.558937 | -0.407391 |
| 2025-10-24 Team B @ Team A | +0.195816 | +0.191574 |
| 2025-10-24 Team E @ Team D | +0.972982 | +0.958341 |
| 2025-10-28 Team C @ Team A | +0.066859 | +0.098262 |
| 2025-10-29 Team G @ Team L | +0.425077 | +0.407979 |
| 2025-11-02 Team D @ Team A | +2.045478 | +2.030122 |
| 2025-11-16 Team H @ Team K | +1.333054 | +1.324736 |
| 2025-11-19 Team I @ Team K | +1.946568 | +1.952177 |
| 2025-11-28 Team J @ Team K | +1.315295 | +1.280153 |

| Summary | M1 | M2 |
|---|---:|---:|
| Equal-game net gap, 95% CI (ft) | +0.9365 [0.4152, 1.4291] | +0.9445 [0.4498, 1.4215] |
| Leave-one-game-out mean range (ft) | [0.8133, 1.1027] | [0.8239, 1.0948] |
| Top 3 positive games / total positive game delta (95% CI) | 5.6150 / 9.9241 = 56.58% [40.75%, 79.99%] | 5.5917 / 9.8528 = 56.75% [40.91%, 79.43%] |
| Top 3 positive sum / net game gap | 59.96% [41.01%, 104.00%] | 59.20% [41.10%, 95.23%] |
| Worst 18 of 172 starts / positive weighted loss (95% CI) | 0.6334 / 1.9247 = 32.91% [26.54%, 39.61%] | 0.6340 / 1.9314 = 32.82% [26.57%, 39.17%] |
| Worst-decile contribution / net gap | 67.63% [42.27%, 152.13%] | 67.12% [42.56%, 140.65%] |
| Equal-game mean after dropping worst 18 (154 starts retained) | +0.3277 ft; sign unchanged | +0.3370 ft; sign unchanged |

The Q4 intervals use the preregistered resampling rules: in each draw the game top-three share is recomputed from sampled games; for start shares, all starts are carried with each sampled game occurrence and the worst `ceil(0.10*N)` are selected again. Undefined-ratio draw counts and valid counts are recorded in the JSON. The increase is distributed over most games and is not reversed by removing the worst start decile, though the worst decile accounts for about one-third of positive weighted loss.

## Q5 — Individual versus group dissociation at +45

Individual gain is M0 endpoint radial error minus candidate error, so positive means lower individual radial error. Group loss is the Q4 team-spacing delta, so positive means worse team spacing. Correlation is pooled over per-start values, with whole-game bootstrap intervals.

| Candidate | Individual radial gain (ft, 95% CI) | Team-spacing loss (ft, 95% CI) | Spearman rho (95% CI) |
|---|---:|---:|---:|
| M1 | +1.1296 [0.5668, 1.6668] | +0.9365 [0.4152, 1.4291] | -0.2342 [-0.3819, -0.1042] |
| M2 | +1.1389 [0.5696, 1.6824] | +0.9445 [0.4498, 1.4215] | -0.2330 [-0.3827, -0.1002] |

| Sign quadrant (equal-game weighted share) | M1 share; raw starts; 95% CI | M2 share; raw starts; 95% CI |
|---|---:|---:|
| Individual gain and group loss both positive | 0.3345; 58; [0.2727, 0.3996] | 0.3405; 59; [0.2873, 0.3985] |
| Gain only | 0.2699; 46; [0.2132, 0.3303] | 0.2699; 46; [0.2132, 0.3303] |
| Loss only | 0.2941; 50; [0.2397, 0.3566] | 0.2881; 49; [0.2421, 0.3395] |
| Neither positive | 0.1015; 18; [0.0542, 0.1508] | 0.1015; 18; [0.0542, 0.1508] |

The negative rank association is a between-start composition pattern, not evidence that individual gain causes spacing loss within a start. About one-third of starts show both positive, while gain-only and loss-only starts are each common. It is not a uniform per-start trade. All four categories are represented across all ten games; 172 starts were scored. The bootstrap had 10,000 valid draws and no constant-vector failures for either correlation.

## Q6 — Archived constraint-activity mechanism screen

The archived M1/M2 frame model fields are only `players` and `puck`. Comparison samples contain aggregate constraint fields `boundary_projections`, `delta_projections`, `separation_projections`, `speed_projections`, and `turn_projections`; no explicit player- or pair-linked activity labels are present. The archive therefore cannot identify whether the pairs with worse spacing were the pairs touched by a constraint. No labels were inferred from displacement, and no resimulation was performed.

## Diagnostic conclusion and mechanism shortlist

The largest measured group-level signal is horizon-growing within-team compaction: candidate signed pair-distance error is negative by +15 and reaches about -4 ft on average by +45, on both source axes. Pair absolute error also rises. At the same time, individual endpoint radial error improves by about 1.1 ft. Q5 shows this is not a simple within-start trade: the gain/loss rank correlation is negative and only about one-third of starts exhibit both signs. Q3 does not isolate one axis, and Q6 cannot attribute the result to a particular physical constraint. This population does not resolve the mechanism.

The following is a ranked **measurement shortlist**, not a candidate or policy ranking:

1. **Relative-position / shared-intent drift.** Supported as the first phenomenon to explain by negative pair bias on both axes, growing with horizon, and by widespread positive game deltas (9/10). It would be weakened if a new independently held-out, source-aligned sample failed to reproduce the compaction. Discriminate with source-provenanced player roles and reliable multi-player state labels, then inspect per-pair errors by role and team context under a frozen protocol.
2. **State-estimation or timing mismatch.** The same horizon growth is compatible with accumulated prediction drift, but Image Id increments are not validated time intervals, so rates and reaction delays cannot be estimated. Discriminate with independently verified frame timestamps/cadence and uninterrupted observations, without fitting timing from target outcomes.
3. **Constraint projection contribution.** M2 and M1 show similar group deterioration, but aggregate projection counts do not identify affected players or pairs. The current archive neither supports nor rules out constraint attribution. Any future run intended to test this needs explicit, step-linked pre/post constraint activity labels and must be evaluated on independent games; the frozen policies here remain untouched.
4. **Role/lineup composition.** Q1 cannot separate defence and forward pair types because no explicit D/F labels exist in the frozen cutoff records. Source-verified, game-period-scoped roles and on-ice membership would enable the missing pair-type decomposition; jersey-number or shape-based inference is not acceptable.

No adoption or policy decision follows. Independent tracking, verified timebase and identity/role provenance, and a preregistered evaluation on games outside these ten are still required.

## Reproduction

From the worktree root, the evaluator was run with the system Python that has NumPy installed:

```sh
nice -n 10 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/attribute_joint_coherence.py
```

The required deterministic rerun to a fresh output path and byte comparison are reported with the commit checks. The evaluator writes no timestamps or runtime into the versioned results.
