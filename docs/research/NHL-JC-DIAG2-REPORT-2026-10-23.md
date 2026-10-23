# Population and boundary

This is a descriptive analysis of **10 development games**, evaluated with leave-one-whole-game-out predictions. The frozen study has 200 rollout starts, of which 172 are group-scored at +45, and 454,983 eligible one-skater training windows. Horizons are ordinal Image Id increments, **not seconds**. There is no independent tracking population on disk. Nothing here licenses adoption, an NHL simulator claim, or a Legendary Picks probability change.

All reported pair errors are in rink-coordinate feet. Uncertainty intervals resample the ten whole-game clusters, not the 172 starts or pair rows. Every finding is descriptive and scores no candidate. No controller, policy, threshold, source artifact, or JC decision was changed or rerun.

## Preregistration and provenance gate

The preregistration was committed before any new measurement as `b5b439310d0c97964f209af8cd29e9e04831b5fe` (`docs/research/NHL-JC-DIAG2-PREREG-2026-10-23.md`, SHA-256 `2c0e395badf81de7df0ee488e2bc0f4fa239400ae6d6b077594007c08206d234`). The evaluator first verified eight frozen source hashes, including the JC result, comparison, fold models, scenario archive, rollout-start source, prior JC-DIAG preregistration/results, and this preregistration. Those hashes are recorded in the result JSON.

The task-named `results/rollout_starts-2026-10-23.json` was absent in the worktree. The prior JC evaluator’s pinned `/root/lp-research-data/nhl-multi-agent-movement-2026-10-23/rollout_starts.json.gz` was used (SHA-256 `07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de`). The JSON records both paths and that resolution.

All requested provenance assertions passed before P1–P4 ran:

| Frozen JC-DIAG value | Expected | Re-read from pinned result | Result |
|---|---:|---:|---|
| +45 M1 signed pair error; 95% interval | -3.990319961 [-4.745503058, -3.277490265] | -3.990319961147472 [-4.745503058078117, -3.277490265327321] | PASS |
| +45 M2 signed pair error; 95% interval | -4.018689088 [-4.765197406, -3.325853562] | -4.018689087597857 [-4.7651974061864095, -3.325853562183953] | PASS |
| +45 M1 individual radial gain (ft) | +1.129584368 | +1.1295843676250077 | PASS |
| +15 M1 Home signed pair bias (ft) | -0.8193 | -0.819339742276739 | PASS |
| +45 pair denominator | Home 1,064 + Away 1,100 = 2,164 | Home 1,064 + Away 1,100 = 2,164 | PASS |

The raw-frame reconstruction independently reproduced the +45 Home/Away pair denominators before P1–P4 were aggregated.

## P1 — Within-start persistence from +15 to +45

For each eligible start/team/model, the statistic is the fraction of the later horizon’s negative signed-error **mass** contributed by pairs whose signed error was already negative at the earlier horizon. It is not the fraction of pair IDs. The permutation null shuffles +45 signed errors across pair IDs within that same start and team, preserving the error values and total negative mass; 10,000 shuffles per start/team/transition were used, with the same permutation map across M0/M1/M2. The table gives equal-game estimates and 95% game-cluster intervals. “Excess” is observed minus permutation-null share, in percentage points.

| Team | Model | Starts / pairs in estimate | Observed mass share (95% CI) | Permutation null (95% CI) | Excess, pp (95% CI) |
|---|---|---:|---:|---:|---:|
| Home | M0 | 136 / 984 | 73.2% [67.9, 78.5] | 45.6% [41.1, 50.3] | +27.6 [22.0, 34.0] |
| Home | M1 | 142 / 1,008 | 82.0% [77.3, 86.7] | 61.7% [57.0, 66.7] | +20.3 [16.8, 23.4] |
| Home | M2 | 142 / 1,008 | 82.0% [77.1, 86.8] | 61.9% [57.1, 66.7] | +20.2 [16.6, 23.4] |
| Away | M0 | 152 / 1,056 | 78.1% [74.5, 81.5] | 49.4% [46.7, 52.4] | +28.7 [24.9, 32.0] |
| Away | M1 | 156 / 1,075 | 84.0% [80.5, 87.0] | 61.8% [57.8, 65.6] | +22.1 [18.7, 26.2] |
| Away | M2 | 156 / 1,075 | 84.5% [80.7, 87.8] | 62.0% [58.1, 65.8] | +22.4 [19.3, 25.9] |
| Equal-team | M0 | 122 / 1,704 | 76.3% [72.7, 80.2] | 47.8% [45.2, 51.1] | +28.5 [25.4, 32.6] |
| Equal-team | M1 | 131 / 1,834 | 83.1% [80.4, 85.9] | 62.0% [58.7, 65.7] | +21.0 [18.0, 24.0] |
| Equal-team | M2 | 131 / 1,834 | 83.4% [80.4, 86.7] | 62.1% [58.6, 66.2] | +21.3 [18.4, 24.0] |

Across the 172 +45-scored starts, +15/+45 common-pair denominators range from 1 to 15 per start/team (median 6): 1,064 Home and 1,100 Away pair observations. Twenty Home and 13 Away start/team cells had fewer than three common pairs and were marked non-estimable. Among the remaining cells, zero later negative mass made another 23 M0, 13 M1 and 13 M2 start/team values non-estimable. The JSON contains each start/team pair denominator, exclusion reason, negative-mass denominator, and per-game value.

Negative mass is substantially persistent for M1/M2: about 83% is on pairs already negative at +15, versus about 62% under random reassignment. M0 also shows persistence above its own null (76% versus 48%), so persistence is not unique to the interaction models. These intervals reflect ten games, not hundreds of independent player pairs.

## P2 — Persistence across adjacent horizons

The same +45-eligible 172 starts were used for both transitions. The pairs are common to the two endpoints of each transition. The table reports observed share, permutation-null share, and observed-minus-null difference, each with a 95% whole-game interval.

### +15 to +30 ordinal increments

| Team | Model | Starts / pairs | Observed (95% CI) | Null (95% CI) | Excess, pp (95% CI) |
|---|---|---:|---:|---:|---:|
| Home | M0 | 144 / 1,044 | 83.3% [81.3, 85.5] | 45.6% [41.6, 50.0] | +37.7 [33.3, 42.3] |
| Home | M1 | 150 / 1,078 | 92.8% [90.8, 94.9] | 62.4% [58.3, 66.7] | +30.4 [27.8, 32.9] |
| Home | M2 | 150 / 1,078 | 93.2% [91.4, 94.9] | 62.3% [58.1, 66.7] | +30.8 [28.0, 33.6] |
| Away | M0 | 152 / 1,153 | 87.8% [84.8, 90.9] | 51.9% [49.8, 54.4] | +35.9 [31.8, 40.5] |
| Away | M1 | 160 / 1,190 | 91.5% [88.8, 93.6] | 63.3% [59.6, 66.6] | +28.2 [25.1, 31.9] |
| Away | M2 | 161 / 1,196 | 91.8% [89.0, 94.1] | 63.2% [59.8, 66.3] | +28.6 [25.8, 31.8] |
| Equal-team | M0 | 127 / 1,859 | 85.4% [83.6, 87.0] | 49.5% [47.1, 52.6] | +35.9 [33.4, 38.2] |
| Equal-team | M1 | 140 / 2,042 | 92.5% [91.5, 93.5] | 63.3% [60.3, 66.5] | +29.1 [26.5, 31.9] |
| Equal-team | M2 | 141 / 2,051 | 92.9% [91.6, 94.3] | 63.4% [60.3, 66.8] | +29.5 [27.1, 32.0] |

### +30 to +45 ordinal increments

| Team | Model | Starts / pairs | Observed (95% CI) | Null (95% CI) | Excess, pp (95% CI) |
|---|---|---:|---:|---:|---:|
| Home | M0 | 135 / 978 | 90.1% [87.7, 92.7] | 49.8% [47.5, 52.0] | +40.4 [37.6, 43.4] |
| Home | M1 | 141 / 1,002 | 92.7% [88.7, 95.9] | 64.2% [61.1, 66.8] | +28.5 [26.4, 30.3] |
| Home | M2 | 141 / 1,002 | 92.8% [89.0, 95.9] | 64.8% [61.8, 67.4] | +28.0 [25.8, 29.8] |
| Away | M0 | 151 / 1,050 | 90.6% [86.9, 94.2] | 51.8% [48.5, 55.4] | +38.8 [36.5, 41.2] |
| Away | M1 | 155 / 1,069 | 94.7% [92.8, 96.6] | 67.4% [63.9, 71.1] | +27.3 [24.5, 30.2] |
| Away | M2 | 155 / 1,069 | 95.2% [93.2, 97.0] | 68.0% [64.3, 71.7] | +27.2 [24.6, 29.9] |
| Equal-team | M0 | 121 / 1,692 | 90.5% [88.0, 92.9] | 50.8% [48.3, 53.5] | +39.7 [37.8, 42.0] |
| Equal-team | M1 | 130 / 1,822 | 93.6% [91.1, 95.8] | 65.8% [62.8, 68.8] | +27.7 [25.6, 29.9] |
| Equal-team | M2 | 130 / 1,822 | 94.0% [91.5, 96.2] | 66.4% [63.3, 69.3] | +27.6 [25.4, 29.6] |

By equal-team point estimates, observed persistence rises from +15→+30 to +30→+45 for M0 (85.4% to 90.5%), M1 (92.5% to 93.6%), and M2 (92.9% to 94.0%). Home M1/M2 are nearly flat and slightly lower at the later transition (92.8% to 92.7%; 93.2% to 92.8%), while Away persistence rises for both. Intervals overlap; this is a descriptive direction only, with no trend test. The equal-team observed-minus-null excess falls slightly for M1 and M2 across adjacent transitions, so the larger observed share at the later horizon partly accompanies a larger null persistence rate.

The per-transition common-pair counts per start/team range from 0 to 15, with median 6. For +15→+30, fewer than three pairs excluded 16 Home and 8 Away cells; for +30→+45, 21 Home and 14 Away cells. Zero later negative mass among cells with enough pairs additionally excluded M0/M1/M2 counts of 24/10/9 for +15→+30 and 23/13/13 for +30→+45. Each transition retained eligible values from all ten games. Exact start-level support is in the JSON.

## P3 — Baseline M0 error deciles

The 2,164 within-team pairs common to +1, +15, and +45 across all three recorded models were assigned to deciles by their own M0 absolute signed error at +1. The nine cutpoints in feet were `0.0201, 0.0378, 0.0571, 0.0773, 0.1018, 0.1270, 0.1601, 0.2074, 0.2890`; cutpoint ties went to the higher bin. Each decile contains 216 or 217 pairs and all ten games. Tables show pair counts and represented starts, candidate-minus-M0 signed-error delta, candidate-minus-M0 absolute-error delta, and each decile’s share of total positive weighted absolute-error delta. Intervals use whole-game bootstrap clusters.

### +15 ordinal increments

| Decile | Pairs / starts | M1 signed Δ ft [95% CI] | M1 absolute Δ ft [95% CI] | M1 positive share [95% CI] | M2 signed Δ ft [95% CI] | M2 absolute Δ ft [95% CI] | M2 positive share [95% CI] |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 217 / 115 | -0.891 [-1.017, -0.770] | +0.208 [+0.110, +0.304] | 8.3% [6.4, 10.4] | -0.860 [-0.987, -0.737] | +0.230 [+0.130, +0.330] | 8.4% [6.5, 10.4] |
| 2 | 216 / 109 | -1.083 [-1.211, -0.977] | +0.155 [-0.059, +0.366] | 8.7% [5.9, 12.2] | -1.093 [-1.228, -0.963] | +0.183 [-0.035, +0.408] | 8.8% [5.9, 12.2] |
| 3 | 216 / 106 | -0.986 [-1.127, -0.853] | +0.310 [+0.140, +0.477] | 8.7% [7.4, 10.2] | -0.982 [-1.116, -0.850] | +0.303 [+0.126, +0.483] | 8.5% [7.3, 9.9] |
| 4 | 217 / 116 | -1.078 [-1.236, -0.908] | +0.240 [-0.012, +0.486] | 9.9% [7.4, 12.3] | -1.058 [-1.219, -0.899] | +0.264 [+0.040, +0.493] | 9.9% [7.2, 12.3] |
| 5 | 216 / 119 | -1.135 [-1.254, -1.017] | +0.309 [+0.142, +0.478] | 10.7% [8.9, 12.4] | -1.143 [-1.265, -1.013] | +0.295 [+0.113, +0.473] | 10.7% [8.9, 12.4] |
| 6 | 216 / 122 | -1.080 [-1.229, -0.908] | +0.416 [+0.197, +0.632] | 11.1% [8.4, 14.2] | -1.078 [-1.236, -0.888] | +0.423 [+0.202, +0.643] | 11.0% [8.2, 14.2] |
| 7 | 217 / 119 | -1.102 [-1.278, -0.958] | +0.142 [-0.034, +0.329] | 9.8% [7.8, 11.6] | -1.133 [-1.302, -0.989] | +0.176 [-0.004, +0.363] | 9.9% [7.8, 11.7] |
| 8 | 216 / 115 | -1.149 [-1.355, -0.979] | +0.123 [-0.174, +0.429] | 9.6% [7.4, 12.0] | -1.155 [-1.324, -0.996] | +0.139 [-0.156, +0.444] | 9.7% [7.6, 12.0] |
| 9 | 216 / 117 | -1.201 [-1.350, -1.061] | +0.136 [-0.053, +0.344] | 12.0% [9.1, 14.7] | -1.251 [-1.397, -1.101] | +0.130 [-0.096, +0.383] | 12.2% [9.1, 15.1] |
| 10 | 217 / 86 | -1.219 [-1.319, -1.108] | +0.019 [-0.251, +0.342] | 11.0% [7.9, 14.2] | -1.258 [-1.345, -1.161] | +0.036 [-0.235, +0.357] | 11.0% [7.7, 14.7] |

### +45 ordinal increments

| Decile | Pairs / starts | M1 signed Δ ft [95% CI] | M1 absolute Δ ft [95% CI] | M1 positive share [95% CI] | M2 signed Δ ft [95% CI] | M2 absolute Δ ft [95% CI] | M2 positive share [95% CI] |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 217 / 115 | -3.592 [-3.988, -3.244] | +0.190 [-0.342, +0.694] | 7.9% [6.7, 9.0] | -3.609 [-3.996, -3.259] | +0.138 [-0.482, +0.706] | 7.8% [6.7, 9.0] |
| 2 | 216 / 109 | -4.052 [-4.489, -3.692] | +0.307 [-0.364, +0.974] | 9.5% [7.0, 12.3] | -4.066 [-4.501, -3.697] | +0.309 [-0.352, +0.925] | 9.5% [7.0, 12.3] |
| 3 | 216 / 106 | -3.732 [-4.190, -3.308] | +1.146 [+0.543, +1.686] | 9.3% [7.4, 11.3] | -3.745 [-4.203, -3.310] | +1.074 [+0.475, +1.609] | 9.1% [7.3, 11.1] |
| 4 | 217 / 116 | -4.023 [-4.504, -3.527] | +0.258 [-0.211, +0.685] | 8.8% [6.8, 11.3] | -4.036 [-4.508, -3.560] | +0.271 [-0.175, +0.682] | 8.8% [6.8, 11.3] |
| 5 | 216 / 119 | -4.275 [-4.590, -3.957] | +0.894 [+0.346, +1.437] | 10.9% [9.4, 12.5] | -4.306 [-4.629, -3.973] | +0.912 [+0.364, +1.453] | 10.9% [9.4, 12.4] |
| 6 | 216 / 122 | -3.998 [-4.420, -3.471] | +0.899 [-0.022, +1.769] | 9.6% [6.8, 12.9] | -3.995 [-4.427, -3.443] | +0.898 [-0.023, +1.769] | 9.5% [6.7, 12.9] |
| 7 | 217 / 119 | -4.087 [-4.667, -3.609] | +0.705 [+0.010, +1.364] | 10.4% [8.5, 12.7] | -4.127 [-4.692, -3.646] | +0.734 [+0.041, +1.380] | 10.4% [8.5, 12.6] |
| 8 | 216 / 115 | -4.223 [-4.858, -3.667] | -0.088 [-0.655, +0.605] | 8.3% [5.9, 11.5] | -4.257 [-4.852, -3.717] | -0.048 [-0.630, +0.643] | 8.3% [6.0, 11.6] |
| 9 | 216 / 117 | -4.367 [-4.805, -3.959] | +0.402 [-0.070, +0.855] | 11.7% [8.7, 14.4] | -4.437 [-4.857, -4.026] | +0.407 [-0.100, +0.894] | 12.0% [9.0, 14.6] |
| 10 | 217 / 86 | -4.659 [-5.062, -4.290] | +0.161 [-0.996, +1.179] | 13.7% [9.5, 18.1] | -4.700 [-5.075, -4.352] | +0.214 [-0.918, +1.223] | 13.7% [9.4, 18.2] |

Signed candidate-minus-M0 error is negative in every decile at both horizons: the candidates are more compact than M0 across the baseline-error range. Absolute-error increases at +45 are not concentrated only in the highest M0-error decile; the largest point estimates are in deciles 3, 5, and 6, while decile 10 is smaller and uncertain. Decile contributions are broadly distributed rather than dominated by one tail.

No pair had an exactly zero M0 signed error at +1 (0 of 2,164). Thus the preregistered exact-right group is empty, and there is no direct exact-correct versus incorrect comparison. Among all nonzero-error pairs, mean signed deltas were -1.170 ft for M1 and -1.178 ft for M2 at +15; mean absolute-error deltas were +0.162 [0.051, 0.299] and +0.171 [0.060, 0.309] ft. At +45 the signed deltas were -4.341 [-4.539, -4.148] and -4.364 [-4.556, -4.173] ft; absolute-error deltas were +0.375 [0.051, 0.689] and +0.377 [0.069, 0.677] ft. The lowest baseline-error decile is the nearest available comparison to pairs M0 got right, but it is not an exact-right group.

## P4 — Observed cutoff-distance quartiles

The observed cutoff pair-distance quartile edges are 17.038, 25.897, and 36.184 ft. Each quartile contains 541 pairs and all ten games; starts per quartile range from 147 to 160. Values are candidate-minus-M0 signed-error delta, absolute-error delta, and the share of total positive weighted absolute-error delta.

| Quartile | Pairs / starts | M1 signed Δ [95% CI] | M1 absolute Δ [95% CI] | M1 positive share [95% CI] | M2 signed Δ [95% CI] | M2 absolute Δ [95% CI] | M2 positive share [95% CI] |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 541 / 153 | -2.140 [-2.393, -1.926] | +1.273 [1.052, 1.464] | 17.2% [14.8, 19.5] | -2.162 [-2.430, -1.930] | +1.305 [1.091, 1.490] | 17.4% [14.9, 19.8] |
| 2 | 541 / 160 | -3.284 [-3.653, -2.878] | +1.189 [0.844, 1.551] | 25.5% [22.1, 28.8] | -3.318 [-3.685, -2.907] | +1.203 [0.858, 1.559] | 25.5% [22.1, 28.7] |
| 3 | 541 / 157 | -4.697 [-4.977, -4.474] | +0.482 [-0.104, 1.098] | 27.7% [22.8, 33.1] | -4.714 [-4.983, -4.502] | +0.496 [-0.068, 1.091] | 27.6% [22.8, 32.7] |
| 4 | 541 / 147 | -6.442 [-6.737, -6.090] | -0.693 [-1.354, -0.161] | 29.6% [25.5, 33.9] | -6.514 [-6.817, -6.143] | -0.702 [-1.377, -0.164] | 29.6% [25.5, 33.8] |

Candidate signed errors become progressively more compact relative to M0 as initial observed pair distance increases. Absolute error increases for quartiles 1 and 2, is not separated from zero for quartile 3, and decreases for the longest-distance quartile. Thus the strongest signed compression is in the longest starting pairs, while its absolute-error effect depends on the M0 error direction. This split uses observed cutoff distance only; no role, line, or position labels were inferred.

## Implications for the JC-DIAG shortlist

1. **Relative-position or shared-intent drift remains plausible.** Most later negative-error mass is attached to pairs already negative at the prior horizon, and persistence is above the within-start permutation reference for M0, M1, and M2. It is not uniquely attributable to M1/M2 because M0 also has persistent pair errors. Instrumenting per-pair policy intent on a future, independently tracked sample would help separate shared behavior from common state drift.
2. **Accumulated state error remains plausible, but “only pairs M0 already got most wrong” is not supported.** Added signed error is negative throughout the M0-error deciles, while positive absolute-error contributions are spread across deciles and are not dominated by decile 10. Exact-zero M0 pairs are absent, so the exact-right comparison cannot be made. Independent tracking with validated timestamps, measurement uncertainty, and stable identities is needed to separate model drift from input/state error.
3. **Cutoff pair length is associated with the direction of the delta, not a single absolute-loss mechanism.** Longer initial pairs receive more negative candidate-minus-M0 signed deltas, yet the longest-distance quartile has lower absolute error than M0. Per-pair pre/post constraint-activity labels would be needed to attribute this pattern to a constraint projection; this archive does not contain them.

These ten development games distinguish persistent pair relationships from random pair reassignment in the recorded trajectories, but they do not identify a causal mechanism or validate a new policy. The next discriminating evidence is independent multi-game tracking with verified subsecond timestamps, better identity/visibility coverage, per-pair constraint activity labels, and source-supported roles if role-specific explanations are to be tested.

## Reproduction

The evaluator is `research/nhl-multi-agent-movement-2026-10-23/diagnose_pair_persistence.py`. The deterministic result is `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag2-pair-persistence-2026-10-23-v1.json`. The full source and per-start denominators, permutation means, bootstrap intervals, bin cutpoints, and exclusions are in that JSON.

```sh
nice -n 10 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_pair_persistence.py --gate-only
nice -n 10 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_pair_persistence.py
```

The recorded result JSON and fresh-path rerun are byte-identical: both SHA-256 values are `54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed`, each 5,596,565 bytes. The rerun completed in 20.01 seconds at nice 10 (273,544 KB maximum RSS; zero swaps). The evaluator SHA-256 is `5d97f67aece534c0a8b12ca8e04e7ff423e2eda3aa84a014136022978d8b30c0`. Gate-only and full runs each passed all eight frozen input hashes and all published-value assertions. `git diff --check`, commit, push, and remote SHA are reported in the task completion summary.
