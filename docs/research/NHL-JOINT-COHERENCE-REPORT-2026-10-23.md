# NHL joint movement coherence (JC) report

## Population and adoption boundary

This is a ten-game development study: 10 leave-one-whole-game-out clusters, 200 fixed rollout starts (20 per game), and 454,983 eligible one-skater windows. All horizons are Image Id suffix increments, not seconds. The ten inspected games are development data; no independent tracking population is available. **This milestone cannot license adoption, an NHL simulator claim, or a change to Legendary Picks probabilities.**

JC scores the already archived M0 independent, M1 interaction, and M2 constrained paths. It does not refit or alter any policy, constraint, coefficient, or gate. Future labels are used only for evaluation. M0/M1/M2 keep their existing meanings; JC names the milestone.

## Frozen sources and scoring coverage

The latest preregistration is `748e0090d18ee4a6cac09aa57429d347f9d5efae` on Legendary Picks and `7e55ba30f40f83c8c251abf450512d740c89a1fd` on Gridiron Physics (file SHA-256 `5ec697c63d80a1afe3ee2cb95b2c7a30ea633c0a9fb7ff9483983e2bd1501773`). Prediction inputs are the frozen scenario archive `a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce` and the 200 exact start IDs in the rollout-start manifest `07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de`. The original input archive contained 206 recorded scenarios; category-only examples were not added to the scored start population.

A state scores only when at least two commonly labeled skaters remain on each team. No target coordinates are imputed. The complete-case group population declines with horizon:

| Horizon (ordinal increments, not seconds) | Scored starts / 200 | Game clusters / 10 |
|---|---:|---:|
| +1 ordinal increments (not seconds) | 200 | 10 |
| +15 ordinal increments (not seconds) | 190 | 10 |
| +30 ordinal increments (not seconds) | 179 | 10 |
| +45 ordinal increments (not seconds) | 172 | 10 |

Every primary horizon has scored states in all ten games, so its game-cluster intervals use all ten clusters. Counts and pair denominators below are identical across M0/M1/M2 at a given horizon because the models are paired on the same common labels.

## Individual and group dissociation

Each estimate is an equal-game mean with a 95% whole-game bootstrap interval. One-step endpoint radial error is the frozen +15 ordinal-increment predictor result (not seconds); rollout radial error is the autonomous path endpoint at the row's ordinal horizon. Group metrics compare each generated group with the observed target group. Distances are in rink-coordinate feet.

| Model | Horizon (ordinal increments, not seconds) | One-step radial error, ft | Rollout radial error, ft | Pooled centroid error, ft | Home / Away centroid error, ft | Team-spacing error, ft | All-pair error mean / P90, ft | Nearest-opponent quantile gap, ft | Scored states / games; common skaters; all pairs (total; mean/state); within-team pairs (total; mean/state) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| M0 | +1 ordinal increments (not seconds) | 3.222 [3.127, 3.327] | 0.200 [0.188, 0.215] | 0.147 [0.131, 0.163] | 0.160 [0.144, 0.177] / 0.151 [0.136, 0.166] | 0.096 [0.087, 0.105] | 0.140 [0.134, 0.145] / 0.285 [0.269, 0.301] | 0.114 [0.103, 0.124] | 200/10; 8.56; 6653 (33.27/state); 3026 (15.13/state) |
| M1 | +1 ordinal increments (not seconds) | 3.119 [3.021, 3.222] | 0.205 [0.192, 0.220] | 0.143 [0.124, 0.162] | 0.157 [0.137, 0.178] / 0.148 [0.132, 0.163] | 0.101 [0.091, 0.112] | 0.148 [0.140, 0.155] / 0.298 [0.280, 0.318] | 0.122 [0.111, 0.134] | 200/10; 8.56; 6653 (33.27/state); 3026 (15.13/state) |
| M2 | +1 ordinal increments (not seconds) | 3.104 [3.008, 3.207] | 0.216 [0.200, 0.234] | 0.143 [0.124, 0.162] | 0.160 [0.140, 0.181] / 0.156 [0.135, 0.177] | 0.110 [0.100, 0.121] | 0.163 [0.153, 0.174] / 0.335 [0.308, 0.364] | 0.151 [0.133, 0.170] | 200/10; 8.56; 6653 (33.27/state); 3026 (15.13/state) |
| M0 | +15 ordinal increments (not seconds) | 3.222 [3.127, 3.327] | 3.645 [3.432, 3.945] | 2.557 [2.366, 2.789] | 2.779 [2.602, 2.992] / 2.745 [2.540, 3.007] | 1.590 [1.411, 1.796] | 2.479 [2.342, 2.625] / 4.894 [4.571, 5.189] | 1.704 [1.589, 1.815] | 190/10; 8.29; 5937 (31.25/state); 2705 (14.24/state) |
| M1 | +15 ordinal increments (not seconds) | 3.119 [3.021, 3.222] | 3.637 [3.414, 3.931] | 2.207 [1.979, 2.451] | 2.533 [2.243, 2.832] / 2.418 [2.205, 2.665] | 1.855 [1.684, 2.053] | 2.743 [2.593, 2.892] / 5.388 [5.084, 5.687] | 1.861 [1.744, 1.973] | 190/10; 8.29; 5937 (31.25/state); 2705 (14.24/state) |
| M2 | +15 ordinal increments (not seconds) | 3.104 [3.008, 3.207] | 3.645 [3.419, 3.937] | 2.207 [1.979, 2.450] | 2.525 [2.232, 2.827] / 2.425 [2.213, 2.668] | 1.861 [1.698, 2.055] | 2.748 [2.594, 2.899] / 5.408 [5.106, 5.701] | 1.858 [1.750, 1.965] | 190/10; 8.29; 5937 (31.25/state); 2705 (14.24/state) |
| M0 | +30 ordinal increments (not seconds) | 3.222 [3.127, 3.327] | 8.397 [7.919, 8.954] | 6.105 [5.765, 6.501] | 6.678 [6.347, 7.031] / 6.435 [5.975, 6.971] | 3.559 [3.236, 3.904] | 5.376 [5.071, 5.675] / 10.511 [9.913, 11.102] | 2.857 [2.697, 3.087] | 179/10; 8.03; 5244 (29.30/state); 2398 (13.40/state) |
| M1 | +30 ordinal increments (not seconds) | 3.119 [3.021, 3.222] | 7.931 [7.434, 8.534] | 5.025 [4.633, 5.475] | 5.757 [5.273, 6.250] / 5.391 [4.971, 5.952] | 4.158 [3.906, 4.464] | 5.823 [5.514, 6.134] / 11.282 [10.679, 11.831] | 3.054 [2.878, 3.249] | 179/10; 8.03; 5244 (29.30/state); 2398 (13.40/state) |
| M2 | +30 ordinal increments (not seconds) | 3.104 [3.008, 3.207] | 7.927 [7.429, 8.514] | 5.020 [4.632, 5.465] | 5.750 [5.267, 6.236] / 5.388 [4.973, 5.942] | 4.167 [3.916, 4.472] | 5.814 [5.503, 6.125] / 11.288 [10.677, 11.848] | 3.006 [2.837, 3.181] | 179/10; 8.03; 5244 (29.30/state); 2398 (13.40/state) |
| M0 | +45 ordinal increments (not seconds) | 3.222 [3.127, 3.327] | 13.575 [12.844, 14.369] | 10.240 [9.493, 11.014] | 10.874 [10.183, 11.627] / 10.838 [9.953, 11.800] | 5.535 [5.134, 5.947] | 7.927 [7.559, 8.310] / 15.565 [14.832, 16.395] | 3.729 [3.422, 4.070] | 172/10; 7.80; 4750 (27.62/state); 2164 (12.58/state) |
| M1 | +45 ordinal increments (not seconds) | 3.119 [3.021, 3.222] | 12.178 [11.425, 13.011] | 8.385 [7.765, 9.002] | 9.231 [8.539, 9.904] / 8.999 [8.280, 9.802] | 6.472 [6.047, 6.924] | 8.340 [7.876, 8.825] / 16.072 [15.188, 17.035] | 3.851 [3.513, 4.213] | 172/10; 7.80; 4750 (27.62/state); 2164 (12.58/state) |
| M2 | +45 ordinal increments (not seconds) | 3.104 [3.008, 3.207] | 12.170 [11.393, 12.986] | 8.376 [7.759, 8.984] | 9.227 [8.528, 9.903] / 8.987 [8.283, 9.772] | 6.480 [6.064, 6.923] | 8.326 [7.867, 8.811] / 16.083 [15.182, 17.063] | 3.779 [3.469, 4.101] | 172/10; 7.80; 4750 (27.62/state); 2164 (12.58/state) |

The pooled centroid error is the distance between simulated and observed group-mean displacement vectors. Team spacing is the equal-team mean absolute error in within-team mean pair distance. All-pair errors compare every unique within-team and opposing-team pair; the P90 is computed per scored state before equal-game aggregation. Nearest-opponent gap is the mean absolute difference across the five preregistered quantiles. The full 45-step profile and per-scenario player/group/pair denominators are in the versioned JSON artifact.

## Paired differences versus M0

Cells show candidate minus M0 with paired 95% game-cluster intervals; negative values improve agreement. The rollout radial column is individual endpoint error. Each horizon is an ordinal suffix increment, not seconds.

| Candidate | Horizon (ordinal increments, not seconds) | Rollout radial Δ, ft | Pooled centroid Δ, ft | Home / Away centroid Δ, ft | Team-spacing Δ, ft | All-pair mean / P90 Δ, ft | Nearest-opponent gap Δ, ft |
|---|---|---:|---:|---:|---:|---:|---:|
| M1 | +1 ordinal increments (not seconds) | 0.0049 [0.0010, 0.0097] | -0.0040 [-0.0094, 0.0021] | -0.0023 [-0.0083, 0.0046] / -0.0030 [-0.0077, 0.0019] | 0.0051 [0.0003, 0.0103] | 0.0078 [0.0050, 0.0110] / 0.0135 [0.0085, 0.0183] | 0.0084 [0.0064, 0.0110] |
| M2 | +1 ordinal increments (not seconds) | 0.0153 [0.0089, 0.0231] | -0.0040 [-0.0093, 0.0021] | 0.0007 [-0.0055, 0.0066] / 0.0047 [-0.0042, 0.0163] | 0.0139 [0.0090, 0.0192] | 0.0230 [0.0152, 0.0323] / 0.0501 [0.0329, 0.0701] | 0.0378 [0.0240, 0.0532] |
| M1 | +15 ordinal increments (not seconds) | -0.0073 [-0.1367, 0.1245] | -0.3496 [-0.5128, -0.1613] | -0.2464 [-0.4503, -0.0225] / -0.3273 [-0.4780, -0.1476] | 0.2654 [0.1410, 0.3980] | 0.2632 [0.1829, 0.3372] / 0.4941 [0.3307, 0.6457] | 0.1573 [0.1178, 0.1975] |
| M2 | +15 ordinal increments (not seconds) | 0.0002 [-0.1268, 0.1352] | -0.3505 [-0.5136, -0.1626] | -0.2541 [-0.4613, -0.0255] / -0.3201 [-0.4753, -0.1334] | 0.2714 [0.1511, 0.4007] | 0.2680 [0.1875, 0.3434] / 0.5139 [0.3545, 0.6648] | 0.1537 [0.1117, 0.1965] |
| M1 | +30 ordinal increments (not seconds) | -0.4657 [-0.7532, -0.1610] | -1.0802 [-1.4249, -0.6941] | -0.9204 [-1.3722, -0.4148] / -1.0439 [-1.3065, -0.7636] | 0.5981 [0.3246, 0.8794] | 0.4467 [0.2667, 0.6042] / 0.7705 [0.4948, 1.0852] | 0.1963 [0.1004, 0.2900] |
| M2 | +30 ordinal increments (not seconds) | -0.4694 [-0.7579, -0.1602] | -1.0846 [-1.4286, -0.6980] | -0.9278 [-1.3770, -0.4230] / -1.0474 [-1.3105, -0.7659] | 0.6079 [0.3302, 0.8892] | 0.4385 [0.2670, 0.5889] / 0.7761 [0.5055, 1.0828] | 0.1487 [0.0379, 0.2469] |
| M1 | +45 ordinal increments (not seconds) | -1.3968 [-1.8731, -0.9010] | -1.8550 [-2.5736, -1.1472] | -1.6436 [-2.5123, -0.7739] / -1.8389 [-2.3788, -1.2759] | 0.9365 [0.4118, 1.4291] | 0.4131 [0.0956, 0.6905] / 0.5079 [-0.0456, 1.0223] | 0.1219 [-0.0843, 0.3319] |
| M2 | +45 ordinal increments (not seconds) | -1.4046 [-1.8820, -0.8984] | -1.8640 [-2.5855, -1.1551] | -1.6471 [-2.5191, -0.7772] / -1.8513 [-2.3946, -1.2864] | 0.9445 [0.4456, 1.4217] | 0.3993 [0.0939, 0.6685] / 0.5189 [-0.0304, 1.0436] | 0.0495 [-0.1553, 0.2529] |

## Exact-step spacing diagnostics

The preregistered signed profile scans every +1 through +45 ordinal increment (not seconds). The onset below is the earliest unadjusted 95% game-cluster interval excluding zero; the 45 stepwise looks are descriptive and unadjusted for multiplicity. Positive team bias means the generated team's mean pair distance is larger than observed; negative means more compact. Positive nearest-opponent bias means generated nearest-opponent quantiles are farther apart.

| Model | Signed diagnostic | Earliest step (ordinal increments, not seconds) | Bias, ft (95% game interval) |
|---|---|---:|---:|
| M0 | Home within-team spacing | +2 (ordinal increments, not seconds; positive) | 0.036 [0.005, 0.066] |
| M0 | Away within-team spacing | +1 (ordinal increments, not seconds; positive) | 0.021 [0.005, 0.037] |
| M0 | Equal-team spacing | +1 (ordinal increments, not seconds; positive) | 0.019 [0.002, 0.035] |
| M0 | Nearest-opponent quantiles | none through +45 | no unadjusted interval excluded zero |
| M1 | Home within-team spacing | +2 (ordinal increments, not seconds; negative) | -0.044 [-0.076, -0.012] |
| M1 | Away within-team spacing | +3 (ordinal increments, not seconds; negative) | -0.072 [-0.122, -0.017] |
| M1 | Equal-team spacing | +2 (ordinal increments, not seconds; negative) | -0.037 [-0.065, -0.012] |
| M1 | Nearest-opponent quantiles | +1 (ordinal increments, not seconds; negative) | -0.011 [-0.021, -0.001] |
| M2 | Home within-team spacing | +2 (ordinal increments, not seconds; negative) | -0.040 [-0.073, -0.008] |
| M2 | Away within-team spacing | +2 (ordinal increments, not seconds; negative) | -0.036 [-0.068, -0.003] |
| M2 | Equal-team spacing | +2 (ordinal increments, not seconds; negative) | -0.038 [-0.066, -0.013] |
| M2 | Nearest-opponent quantiles | +1 (ordinal increments, not seconds; positive) | 0.025 [0.005, 0.047] |

At the first displayed steps, M1's nearest-opponent signed bias is negative at +1 ordinal increment (not seconds), while M2's is positive at +1; both interaction-based policies show negative equal-team spacing bias by +2 ordinal increments (not seconds). These are sub-foot descriptive biases with unadjusted stepwise intervals, not validated physical separation or confirmatory evidence. Use the viewer's scrubber and group-metric panel to inspect the same archived observed and generated frames.

## JC rule and decision

The frozen rule requires at least three of four group families to improve at both +1 and +45 ordinal increments (not seconds), with each paired interval wholly below zero, and no more than 2% one-step endpoint radial-error degradation.

| Candidate | One-step radial change vs M0 | Families improved at +1 (ordinal, not seconds) | Families improved at +45 (ordinal, not seconds) | Verdict |
|---|---:|---:|---:|---|
| M1 | -3.22% (Δ -0.104 ft, 95% CI [-0.109, -0.099]) | 0/4 | 1/4 | FAIL |
| M2 | -3.65% (Δ -0.118 ft, 95% CI [-0.124, -0.112]) | 0/4 | 1/4 | FAIL |

Neither candidate passes. Both improve the frozen one-step endpoint benchmark, but neither improves any group family at +1; at +45, only pooled centroid error improves. Team-spacing error worsens at all four primary horizons for both candidates. Pairwise mean error also worsens throughout; its +45 P90 interval spans zero, so the all-pair family does not count. The individual endpoint gains therefore do not establish coherent joint movement.

## Visual archive and limitations

The Gridiron Physics branch registers the enriched archive under `jc-2026-10-23-v1`, leaving the prior `bc91d1610de5` and `43a81ff70918` archives, clips and validation records intact. The existing four-pane Observed/M0/M1/M2 viewer now shows per-step group metrics and preserves the 2D rink-side view as a camera projection, not measured 3D movement. Seven new category clips and screenshots are stored under the JC archive ID.

The release provides no validated subsecond timebase, cross-game player identity, complete lineups, event alignment, possession labels, continuous puck flight, contact geometry, or tracking-error ground truth. Group spacing floors remain empirical 2D proxies. No physical speed, traction, reaction time, collision, or possession conclusion follows from these results.

## Reproducibility

Evaluation JSON: `research/nhl-multi-agent-movement-2026-10-23/results/joint-coherence-jc-2026-10-23-v1.json`, SHA-256 `0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c`. The exact evaluator source SHA-256 is `440e6adcaa23c6d7b31ba06190a4252ac8c8dd28225cbcb29ef934d09c932d47`. It reads the frozen start, scenario, one-step comparison and fold-model inputs; it does not simulate trajectories. The evaluation was rerun to a separate temporary path and compared byte-for-byte.

The report values are equal-game means with 95% whole-game percentile bootstrap intervals (10,000 draws; seed 20261024). All horizons are ordinal suffix increments, not seconds. JC is a development diagnostic only; independent games are still required.
