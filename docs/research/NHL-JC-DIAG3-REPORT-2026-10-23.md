# NHL JC-DIAG3: pair-geometry shrink diagnosis

**Population and boundary.** This diagnostic covers 10 development games with leave-one-whole-game-out predictions within that sample, 200 rollout starts (172 group-scored at +45), 2,164 +45 within-team pairs (1,064 Home and 1,100 Away), and 454,983 eligible one-skater training windows. Horizons are ordinal Image Id increments, not seconds. No independent tracking population exists on disk. Nothing here licenses adoption, a validated NHL simulator claim, or a Legendary Picks probability change.

Every interval below resamples the 10 whole-game clusters 10,000 times (seed 20261024, equal game weight); pairs and starts are not independent uncertainty units. All findings are descriptive. No refit, resimulation, policy scoring, or candidate selection was performed.

## Preregistration and provenance gate

Preregistration was committed before the gate and measurements: `6de9fb88b031606ff2191aecf83cc970378c39ba`; SHA-256 `96a933c0e0bdff517e84c3598896a4d6dc0dccea358958dd8409f72d3b1789de`. The provenance gate passed all 8 frozen input hashes, the preregistration hash, and 13 value/support assertions before Q1–Q4.

| Frozen input | SHA-256 |
|---|---|
| JC result | `0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c` |
| fold models | `194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a` |
| movement comparison | `1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8` |
| scenario archive | `a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce` |
| rollout starts | `07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de` |
| JC-DIAG result | `f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c` |
| JC-DIAG2 prereg | `2c0e395badf81de7df0ee488e2bc0f4fa239400ae6d6b077594007c08206d234` |
| JC-DIAG2 result | `54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed` |
| JC-DIAG3 prereg | `96a933c0e0bdff517e84c3598896a4d6dc0dccea358958dd8409f72d3b1789de` |

| Gate assertion | Observed | Status |
|---|---:|---|
| +45 M1 signed error; 95% CI | -3.990319961147472; [-4.745503058078117, -3.277490265327321] | PASS |
| +45 M2 signed error; 95% CI | -4.018689087597857; [-4.7651974061864095, -3.325853562183953] | PASS |
| +45 M1 individual radial gain | 1.1295843676250077 | PASS |
| +15 M1 Home signed bias | -0.819339742276739 | PASS |
| +45 raw-frame pairs | Home 1,064; Away 1,100; total 2,164 | PASS |
| DIAG2 P1 EqualTeam M1 observed / null | 0.8305414523474803 / 0.6201172173403376 | PASS |
| DIAG2 P4 fixed distance cutpoints | [17.038243596734116, 25.896550730297974, 36.18400154397977] | PASS |
| DIAG2 P3 frozen support | 2164 | PASS |
| DIAG2 P4 frozen support | 2164 | PASS |

The +45 denominators and both inherited 2,164-pair bin supports were independently recomputed from frozen frames and reconciled to JC/DIAG2. All source hashes and exact assertion details are in the result JSON.

## Q1 — through-origin slopes

Each fit compares signed radial pair error `e_candidate = κ e_M0` with no intercept. Home/Away fits weight common pair rows equally. EqualTeam gives each eligible start/team cell equal total weight (pair weight `1 / cell pair count`) and requires both team cells. `κ` below is the pooled fit; the game vector gives the ten game-level fits in G1–G10 order. Equal-game means and intervals are the preregistered uncertainty estimand. R² is the uncentered through-origin form.

| h | Group | Model | Raw / fit pairs | Pooled κ | Equal-game κ [95% CI] | Pearson / Spearman / R² | Game κ (G1–G10) |
|---:|---|---|---:|---:|---:|---:|---|
| +15 | Home | M1 | 1222 / 1213 | 0.9797 | 0.9738 [0.922, 1.029] | 0.946 / 0.942 / 0.786 | 1.0259,0.8880,0.9590,0.8520,0.8744,1.0321,0.9647,1.0739,1.1393,0.9283 |
| +15 | Home | M2 | 1222 / 1213 | 0.9773 | 0.9725 [0.921, 1.029] | 0.940 / 0.933 / 0.777 | 1.0250,0.9071,0.9470,0.8385,0.8733,1.0299,0.9520,1.0743,1.1407,0.9369 |
| +15 | Away | M1 | 1320 / 1317 | 1.0012 | 1.0039 [0.958, 1.053] | 0.950 / 0.942 / 0.806 | 0.9503,0.9440,1.0700,0.9867,1.0199,0.8803,1.1528,1.0990,0.9522,0.9839 |
| +15 | Away | M2 | 1320 / 1317 | 0.9976 | 0.9997 [0.954, 1.050] | 0.946 / 0.937 / 0.798 | 0.9496,0.9484,1.0669,0.9739,1.0228,0.8795,1.1556,1.0858,0.9482,0.9667 |
| +15 | EqualTeam | M1 | 2542 / 2436 | 0.9684 | 0.9755 [0.939, 1.014] | 0.948 / 0.941 / 0.784 | 0.9918,0.8824,0.9926,0.9256,0.9266,0.9143,1.0201,1.0965,1.0097,0.9957 |
| +15 | EqualTeam | M2 | 2542 / 2436 | 0.9641 | 0.9707 [0.934, 1.008] | 0.942 / 0.934 / 0.775 | 0.9912,0.8896,0.9855,0.9046,0.9241,0.9111,1.0152,1.0877,1.0095,0.9880 |
| +45 | Home | M1 | 1064 / 1044 | 0.9273 | 0.9207 [0.863, 0.980] | 0.950 / 0.943 / 0.767 | 0.9205,0.8362,0.9641,0.8442,0.7659,0.8327,0.9492,0.9784,1.0882,1.0270 |
| +45 | Home | M2 | 1064 / 1044 | 0.9256 | 0.9190 [0.861, 0.979] | 0.949 / 0.941 / 0.763 | 0.9213,0.8325,0.9616,0.8411,0.7689,0.8294,0.9440,0.9746,1.0881,1.0283 |
| +45 | Away | M1 | 1100 / 1087 | 0.9254 | 0.9241 [0.885, 0.963] | 0.955 / 0.945 / 0.776 | 0.8413,0.8416,0.9843,0.9608,0.8556,0.8866,1.0101,0.9917,0.8911,0.9775 |
| +45 | Away | M2 | 1100 / 1087 | 0.9242 | 0.9228 [0.885, 0.961] | 0.954 / 0.944 / 0.773 | 0.8411,0.8479,0.9828,0.9594,0.8523,0.8868,0.9998,0.9921,0.8896,0.9765 |
| +45 | EqualTeam | M1 | 2164 / 1966 | 0.9109 | 0.9188 [0.872, 0.968] | 0.954 / 0.946 / 0.762 | 0.8565,0.8271,0.9673,0.9022,0.8183,0.8506,0.9213,1.0342,0.9914,1.0187 |
| +45 | EqualTeam | M2 | 2164 / 1966 | 0.9099 | 0.9178 [0.872, 0.966] | 0.953 / 0.945 / 0.759 | 0.8570,0.8299,0.9643,0.9032,0.8187,0.8486,0.9148,1.0325,0.9908,1.0180 |

Game order: G1=2025-10-11 Team A@D; G2=2025-10-17 F@L; G3=2025-10-24 B@A; G4=2025-10-24 E@D; G5=2025-10-28 C@A; G6=2025-10-29 G@L; G7=2025-11-02 D@A; G8=2025-11-16 H@K; G9=2025-11-19 I@K; G10=2025-11-28 J@K.

At +15 all six equal-game intervals include κ=1. At +45 all six intervals fall below 1. Exact-zero M0 errors were 0 in every Q1 fit; no finite zero-denominator pair was individually excluded. Cells were excluded only for fewer than 3 pairs: +15 Home 9 cells/9 pairs, Away 3/3; +45 Home 20/20, Away 13/13. EqualTeam additionally excludes the opposite valid cell when its partner fails: +15, 12 cells/94 pairs; +45, 27/165. No cell with at least 3 pairs had a zero M0 squared-error denominator; cells below the minimum were excluded on count before fitting.

## Q2 — ratio distribution at +45

The median `|e_M0|` threshold is **6.1827 ft**. The eligible-cell support is 2131 pairs; exact-zero M0 denominators: 0. Negative ratios are retained. Median and share intervals are whole-game bootstrap intervals; IQR is the point-sample 25th–75th percentile range.

| Model | Cohort | n | Median ratio [95% CI] | Ratio IQR | Share in [0.3, 0.7] [95% CI] | Negative ratios |
|---|---|---:|---:|---:|---:|---:|
| M1 | All eligible pairs | 2131 | 0.940 [0.825, 1.034] | [0.304, 1.469] | 15.3% [12.9, 17.7] | 396 |
| M1 | \|M0 error\| ≥ median | 1066 | 0.945 [0.830, 1.049] | [0.570, 1.278] | 24.1% [19.3, 29.2] | 41 |
| M2 | All eligible pairs | 2131 | 0.938 [0.815, 1.035] | [0.301, 1.469] | 15.3% [12.9, 17.9] | 396 |
| M2 | \|M0 error\| ≥ median | 1066 | 0.942 [0.827, 1.049] | [0.567, 1.277] | 24.1% [19.2, 29.3] | 41 |

The full-support ratio median is near 0.94, but the IQR is broad and 396/2,131 ratios (18.6%) are negative. In the high-magnitude half, 41/1,066 ratios are negative and about 24% lie in [0.3, 0.7]. A single contraction factor is not a good description of every pair.

## Q3 — residual structure after one slope

For each candidate, residuals use its fixed +45 Q1 EqualTeam pooled slope (M1 κ=0.9109; M2 κ=0.9099). No within-bin refit is used. Q3 support after the start/team ≥3-pair gate is 2,131 pairs across 10 games. M0 +1 exact-zero error is 0/2,164 before that gate and 0/2,131 after it. Distance quartile cutpoints are 17.038243596734116, 25.896550730297974, and 36.18400154397977 ft. M0 +1 error-decile cutpoints are 0.02013880768063752, 0.03778431147562884, 0.057149271788077625, 0.0772826427731225, 0.10184994154651683, 0.12700537055808211, 0.16006325254241388, 0.2074288029626061, and 0.2889645922798206 ft. All values below are equal-game means with 10-game cluster 95% intervals.

| Split | Candidate | Pairs / starts / games | Residual mean ft [95% CI] | Raw signed Δ ft [95% CI] |
|---|---|---:|---:|---:|
| Overall | M1 | 2131 / 169 / 10 | -4.251 [-4.534, -3.971] | -4.265 [-4.562, -3.969] |
| Overall | M2 | 2131 / 169 / 10 | -4.273 [-4.551, -3.994] | -4.287 [-4.583, -3.989] |
| Distance Q1 | M1 | 537 / 152 / 10 | -2.657 [-2.888, -2.422] | -2.137 [-2.389, -1.922] |
| Distance Q2 | M1 | 531 / 158 / 10 | -3.478 [-3.911, -3.034] | -3.293 [-3.661, -2.893] |
| Distance Q3 | M1 | 531 / 153 / 10 | -4.484 [-4.742, -4.257] | -4.619 [-4.907, -4.395] |
| Distance Q4 | M1 | 532 / 145 / 10 | -5.982 [-6.316, -5.603] | -6.456 [-6.755, -6.086] |
| Distance Q1 | M2 | 537 / 152 / 10 | -2.682 [-2.936, -2.430] | -2.157 [-2.425, -1.925] |
| Distance Q2 | M2 | 531 / 158 / 10 | -3.510 [-3.939, -3.059] | -3.322 [-3.692, -2.918] |
| Distance Q3 | M2 | 531 / 153 / 10 | -4.505 [-4.756, -4.290] | -4.641 [-4.923, -4.430] |
| Distance Q4 | M2 | 532 / 145 / 10 | -6.048 [-6.379, -5.660] | -6.527 [-6.831, -6.143] |
| M0 +1 decile 1 | M1 | 215 / 113 / 10 | -3.631 [-3.959, -3.317] | -3.574 [-3.968, -3.233] |
| M0 +1 decile 2 | M1 | 211 / 105 / 10 | -4.107 [-4.498, -3.798] | -4.063 [-4.499, -3.697] |
| M0 +1 decile 3 | M1 | 215 / 106 / 10 | -3.857 [-4.253, -3.489] | -3.751 [-4.200, -3.339] |
| M0 +1 decile 4 | M1 | 214 / 116 / 10 | -3.970 [-4.470, -3.483] | -3.979 [-4.487, -3.432] |
| M0 +1 decile 5 | M1 | 214 / 117 / 10 | -4.421 [-4.631, -4.142] | -4.330 [-4.645, -3.995] |
| M0 +1 decile 6 | M1 | 215 / 122 / 10 | -4.052 [-4.478, -3.549] | -4.016 [-4.437, -3.492] |
| M0 +1 decile 7 | M1 | 216 / 119 / 10 | -4.117 [-4.762, -3.601] | -4.076 [-4.655, -3.599] |
| M0 +1 decile 8 | M1 | 213 / 112 / 10 | -4.109 [-4.722, -3.540] | -4.134 [-4.792, -3.539] |
| M0 +1 decile 9 | M1 | 212 / 113 / 10 | -4.350 [-4.838, -3.905] | -4.393 [-4.916, -3.921] |
| M0 +1 decile 10 | M1 | 206 / 80 / 10 | -4.549 [-4.867, -4.194] | -4.675 [-5.128, -4.239] |
| M0 +1 decile 1 | M2 | 215 / 113 / 10 | -3.647 [-3.964, -3.334] | -3.589 [-3.979, -3.245] |
| M0 +1 decile 2 | M2 | 211 / 105 / 10 | -4.132 [-4.521, -3.809] | -4.087 [-4.513, -3.711] |
| M0 +1 decile 3 | M2 | 215 / 106 / 10 | -3.871 [-4.272, -3.500] | -3.764 [-4.213, -3.340] |
| M0 +1 decile 4 | M2 | 214 / 116 / 10 | -3.983 [-4.467, -3.517] | -3.992 [-4.491, -3.464] |
| M0 +1 decile 5 | M2 | 214 / 117 / 10 | -4.452 [-4.666, -4.166] | -4.361 [-4.685, -4.014] |
| M0 +1 decile 6 | M2 | 215 / 122 / 10 | -4.049 [-4.487, -3.520] | -4.012 [-4.446, -3.466] |
| M0 +1 decile 7 | M2 | 216 / 119 / 10 | -4.157 [-4.784, -3.646] | -4.115 [-4.680, -3.640] |
| M0 +1 decile 8 | M2 | 213 / 112 / 10 | -4.146 [-4.706, -3.604] | -4.171 [-4.773, -3.595] |
| M0 +1 decile 9 | M2 | 212 / 113 / 10 | -4.418 [-4.880, -3.979] | -4.462 [-4.958, -3.989] |
| M0 +1 decile 10 | M2 | 206 / 80 / 10 | -4.574 [-4.888, -4.226] | -4.702 [-5.141, -4.275] |

Residual means remain negative in all deciles and distance quartiles. Overall residual and raw signed delta differ by only about 0.014 ft at the point estimate. The distance Q1-to-Q4 residual contrast remains about −3.33 ft (M1) and −3.37 ft (M2), versus raw deltas of about −4.32 and −4.37 ft: the fitted slope flattens but does not remove the distance pattern. These are descriptive contrasts, not causal attribution.

## Q4 — stability across games

EqualTeam +45 per-game κ and residual signs (game order G1–G10 above):

| Game | M1 κ | M1 residual sign | M2 κ | M2 residual sign |
|---|---:|---|---:|---|
| 2025-10-11.Team.A.@.Team.D | 0.8565 | negative | 0.8570 | negative |
| 2025-10-17.Team.F.@.Team.L | 0.8271 | negative | 0.8299 | negative |
| 2025-10-24.Team.B.@.Team.A | 0.9673 | negative | 0.9643 | negative |
| 2025-10-24.Team.E.@.Team.D | 0.9022 | negative | 0.9032 | negative |
| 2025-10-28.Team.C.@.Team.A | 0.8183 | negative | 0.8187 | negative |
| 2025-10-29.Team.G.@.Team.L | 0.8506 | negative | 0.8486 | negative |
| 2025-11-02.Team.D.@.Team.A | 0.9213 | negative | 0.9148 | negative |
| 2025-11-16.Team.H.@.Team.K | 1.0342 | negative | 1.0325 | negative |
| 2025-11-19.Team.I.@.Team.K | 0.9914 | negative | 0.9908 | negative |
| 2025-11-28.Team.J.@.Team.K | 1.0187 | negative | 1.0180 | negative |

Leave-one-game-out EqualTeam +45 κ values in G1–G10 order:

| Model | LOO κ (omit G1,…,G10 respectively) |
|---|---|
| M1 | 0.9165, 0.9224, 0.9034, 0.9116, 0.9213, 0.9215, 0.9100, 0.8996, 0.9019, 0.9020 |
| M2 | 0.9154, 0.9210, 0.9027, 0.9105, 0.9201, 0.9207, 0.9095, 0.8987, 0.9008, 0.9011 |

All 10 game kappas are positive; 8/10 are below 1 and 2/10 are slightly above 1. LOO κ ranges are 0.8996–0.9224 (M1) and 0.8987–0.9210 (M2), so the pooled relation is not carried by one or two games. Yet the EqualTeam residual mean is negative in all 10 games. The positive association is stable; a pure multiplicative contraction is insufficient.

## What this does and does not license

The results are consistent with a stable positive relationship near κ≈0.91 at +45, but the broad ratio distribution, negative ratios, and systematic negative residuals show that one global multiplier does not account for candidate pair geometry. Residuals do not identify whether the remaining component is a common/additive bias, state error, or pair-specific behavior, so JC-DIAG2’s pair-intent mechanism remains possible but unproven. Discriminating those explanations requires independent multi-game tracking with verified timestamps, stable identities, visibility/state-quality measures, and per-pair policy-intent or constraint-activity labels.

## Reproduction

```sh
nice -n 10 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_pair_shrink.py --gate-only
nice -n 10 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_pair_shrink.py
nice -n 10 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_pair_shrink.py --output /tmp/jc-diag3-pair-shrink-repeat.json
```

The recorded result and fresh-path rerun are byte-identical: both SHA-256 values are `e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd`, each 10,708,907 bytes. The full run took 20.63 seconds at nice 10, with 316,660 KB peak RSS and no swap use by the process. `git diff --check HEAD^ HEAD`, results commit, and push are recorded in the task completion summary.
