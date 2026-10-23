# NHL JC-DIAG6: distance-conditioned pair persistence

**Base:** `c84b570ce761879f19f76c46eb6a429bd6a03e9c`. **Preregistration commit:** `0950f166977aac0d90835bede2392395f2802b5c`.
**Branch:** `research/nhl-multi-agent-movement-2026-10-23`.

## 1. Registered reading (Q5; frozen before DIAG6 results)

For each candidate, if the conditioned Q1 primary gap interval includes zero, the result is consistent with the frozen monotone distance response explaining the surviving persistence; state that a pair-intent label program is not justified by this evidence and that the next research spend is a distance-dependent candidate correction, not labels. If the interval excludes zero, report the conditioned gap and retained fraction: residual sign structure remains beyond the frozen distance response, but no behavioral mechanism is identified and labels are not justified by this evidence. If Q1 excludes zero while Q3 attributes at least half of pair covariance to between-bin structure, or Q1 includes zero while Q3 attributes less than half to between-bin structure, classify the result as mixed and do not narrate a winner. Apply this reading separately to both candidates and raw/rank Q3 diagnostics; if they disagree, report the disagreement as mixed.

## 2. Population and boundary

10 development games, leave-one-whole-game-out predictions, 200 rollout starts (172 group-scored at +45), 2,164 +45 within-team pairs (1,064 Home / 1,100 Away), 142 EqualTeam +45 start/team cells, and 311 eligible +45 team cells; horizons are ordinal Image Id increments, **not seconds**; no independent tracking population; pairs and starts are not independent.

The data are the same frozen ten-game development population. Distance is the start-time pair separation; all horizons are ordinal observation steps. No DIAG1–DIAG5 artifact was rewritten.

## 3. Provenance gate

Gate: **PASS**; 17/17 source hashes and 41/41 value/support assertions passed before Q1.

| Frozen input | Expected SHA-256 | Actual SHA-256 | Status |
|---|---|---|---|
| jc_results | `0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c` | `0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c` | PASS |
| fold_models | `194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a` | `194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a` | PASS |
| movement_comparison | `1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8` | `1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8` | PASS |
| scenario_archive | `a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce` | `a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce` | PASS |
| rollout_starts | `07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de` | `07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de` | PASS |
| jc_diag_results | `f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c` | `f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c` | PASS |
| jc_diag2_preregistration | `2c0e395badf81de7df0ee488e2bc0f4fa239400ae6d6b077594007c08206d234` | `2c0e395badf81de7df0ee488e2bc0f4fa239400ae6d6b077594007c08206d234` | PASS |
| jc_diag2_results | `54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed` | `54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed` | PASS |
| jc_diag3_preregistration | `96a933c0e0bdff517e84c3598896a4d6dc0dccea358958dd8409f72d3b1789de` | `96a933c0e0bdff517e84c3598896a4d6dc0dccea358958dd8409f72d3b1789de` | PASS |
| jc_diag3_results | `e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd` | `e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd` | PASS |
| jc_diag4_preregistration | `66dd39e8b48e266c7b06bf751921234f04f8b696e8f752117030f2766e05e1a0` | `66dd39e8b48e266c7b06bf751921234f04f8b696e8f752117030f2766e05e1a0` | PASS |
| jc_diag4_results | `cf9681fa36416ce56996b66c1179c7f17a30a4ed544a0b07b5cd59d896cdc947` | `cf9681fa36416ce56996b66c1179c7f17a30a4ed544a0b07b5cd59d896cdc947` | PASS |
| jc_diag4_evaluator | `2be67e32762b43ed3cfcfaab69c0297e185c254d241c68255b7361a9d921e56a` | `2be67e32762b43ed3cfcfaab69c0297e185c254d241c68255b7361a9d921e56a` | PASS |
| jc_diag5_preregistration | `18b0d649eff4fd43a6250f0dba3297acdc89f5f1950aea5365c370db9bf6fd70` | `18b0d649eff4fd43a6250f0dba3297acdc89f5f1950aea5365c370db9bf6fd70` | PASS |
| jc_diag5_results | `9510d70d418c09da63a6218077b8c1e2b7cc9a11e3b7ed82e63a5457c1039099` | `9510d70d418c09da63a6218077b8c1e2b7cc9a11e3b7ed82e63a5457c1039099` | PASS |
| jc_diag5_evaluator | `2e4c38da94253c24b45d499bdca2bfe74520c204420d22043b386ffe061d8742` | `2e4c38da94253c24b45d499bdca2bfe74520c204420d22043b386ffe061d8742` | PASS |
| jc_diag6_preregistration | `f4d9ba3340895804f346795c479f4171e37aae5ef44570f149cf3efdb0206d48` | `f4d9ba3340895804f346795c479f4171e37aae5ef44570f149cf3efdb0206d48` | PASS |

| Gate assertion | Expected | Actual | Status |
|---|---:|---:|---|
| DIAG5_delta_M1_observed_equal_game_mean | `0.9439834180392761` | `0.9439834180392761` | PASS |
| DIAG5_delta_M1_null_equal_game_mean | `0.5580181646361151` | `0.5580181646361151` | PASS |
| DIAG5_delta_M1_gap_equal_game_mean | `0.38596525340316096` | `0.38596525340316096` | PASS |
| DIAG5_delta_M1_gap_95ci | `[0.3463601234633309, 0.4272949930088017]` | `[0.3463601234633309, 0.4272949930088017]` | PASS |
| DIAG5_delta_M2_observed_equal_game_mean | `0.9148093223665719` | `0.9148093223665719` | PASS |
| DIAG5_delta_M2_null_equal_game_mean | `0.5588313480429111` | `0.5588313480429111` | PASS |
| DIAG5_delta_M2_gap_equal_game_mean | `0.35597797432366096` | `0.35597797432366096` | PASS |
| DIAG5_delta_M2_gap_95ci | `[0.31904827206561803, 0.3941714862120028]` | `[0.31904827206561803, 0.3941714862120028]` | PASS |
| DIAG5_M0_raw_observed_equal_game_mean | `0.7630291734469827` | `0.7630291734469827` | PASS |
| DIAG5_M0_raw_null_equal_game_mean | `0.47819563088399875` | `0.47819563088399875` | PASS |
| DIAG5_M0_raw_gap_equal_game_mean | `0.28483354256298404` | `0.28483354256298404` | PASS |
| DIAG5_M1_candidate_only_observed_equal_game_mean | `0.7821033211298534` | `0.7821033211298534` | PASS |
| DIAG5_M1_candidate_only_null_equal_game_mean | `0.506411577441676` | `0.506411577441676` | PASS |
| DIAG5_M1_candidate_only_gap_equal_game_mean | `0.2756917436881776` | `0.2756917436881776` | PASS |
| DIAG5_M2_candidate_only_observed_equal_game_mean | `0.7822050082063668` | `0.7822050082063668` | PASS |
| DIAG5_M2_candidate_only_null_equal_game_mean | `0.5085816609973904` | `0.5085816609973904` | PASS |
| DIAG5_M2_candidate_only_gap_equal_game_mean | `0.2736233472089765` | `0.2736233472089765` | PASS |
| DIAG5_M1_delta_distance_bin_means_plus45 | `[-2.136556824375522, -3.2929591833431737, -4.618518775773046, -6.456252087389958]` | `[-2.136556824375522, -3.2929591833431737, -4.618518775773046, -6.456252087389958]` | PASS |
| DIAG5_M1_delta_distance_bin_pair_counts_plus45 | `[537, 531, 531, 532]` | `[537, 531, 531, 532]` | PASS |
| DIAG4_evaluator_distance_cutpoints_exact | `[17.038243596734116, 25.896550730297974, 36.18400154397977]` | `[17.038243596734116, 25.896550730297974, 36.18400154397977]` | PASS |
| DIAG5_result_distance_cutpoints_exact | `[17.038243596734116, 25.896550730297974, 36.18400154397977]` | `[17.038243596734116, 25.896550730297974, 36.18400154397977]` | PASS |
| distance_cutpoint_binary_bytes_DIAG4_vs_DIAG5_vs_DIAG6 | `None` | `None` | PASS |
| raw_frame_plus45_pairs_by_team_and_total | `[1064, 1100, 2164]` | `[1064, 1100, 2164]` | PASS |
| raw_frame_population_games_starts_scored | `[10, 200, 172]` | `[10, 200, 172]` | PASS |
| raw_frame_plus45_denominator | `True` | `True` | PASS |
| DIAG5_M1_plus45_pair_rows | `2164` | `2164` | PASS |
| DIAG5_M1_plus45_eligible_team_cells | `311` | `311` | PASS |
| DIAG5_M1_plus45_EqualTeam_starts | `142` | `142` | PASS |
| DIAG5_M1_plus45_exact_zero_count | `0` | `0` | PASS |
| DIAG5_M1_plus45_zero_negative_mass_count | `156` | `156` | PASS |
| DIAG5_M2_plus45_pair_rows | `2164` | `2164` | PASS |
| DIAG5_M2_plus45_eligible_team_cells | `311` | `311` | PASS |
| DIAG5_M2_plus45_EqualTeam_starts | `142` | `142` | PASS |
| DIAG5_M2_plus45_exact_zero_count | `0` | `0` | PASS |
| DIAG5_M2_plus45_zero_negative_mass_count | `161` | `161` | PASS |
| DIAG5_result_evaluator_sha256 | `2e4c38da94253c24b45d499bdca2bfe74520c204420d22043b386ffe061d8742` | `2e4c38da94253c24b45d499bdca2bfe74520c204420d22043b386ffe061d8742` | PASS |
| DIAG5_result_preregistration_sha256 | `18b0d649eff4fd43a6250f0dba3297acdc89f5f1950aea5365c370db9bf6fd70` | `18b0d649eff4fd43a6250f0dba3297acdc89f5f1950aea5365c370db9bf6fd70` | PASS |
| DIAG5_embedded_provenance_gate_passed | `True` | `True` | PASS |
| DIAG5_Q1_Q5_calculated_flag | `True` | `True` | PASS |
| DIAG5_embedded_22_check_validation_passed | `True` | `True` | PASS |
| DIAG5_embedded_postcompute_check_count | `22` | `22` | PASS |

## Q1. Distance-conditioned delta persistence

Q1 uses raw candidate-minus-M0 deltas. A held-out `(team,horizon,bin)` prediction is the other-nine-game pair mean; team cells below 30 pairs use the same-horizon/bin mean pooled across both teams. Residual pairs remain on the original support.

| Transition | Series | Raw gap [95%] | Distance-conditioned gap [95%] | Conditioned observed [95%] | Conditioned null [95%] | EqualTeam starts | Matched cells / zero-mass raw:cond |
|---|---|---:|---:|---:|---:|---:|---:|
| plus15_to_plus45 | M1 delta | 0.0875 [0.0779, 0.0962] | 0.3752 [0.3284, 0.4184] | 0.9639 [0.9532, 0.9744] | 0.5887 [0.5499, 0.6313] | 124 | 279 / 1:32:32 |
| plus15_to_plus45 | M2 delta | 0.0938 [0.0822, 0.1038] | 0.3589 [0.3147, 0.4012] | 0.9427 [0.9213, 0.9623] | 0.5838 [0.5380, 0.6255] | 124 | 280 / 1:31:31 |
| plus15_to_plus30 | M1 delta | 0.0989 [0.0891, 0.1087] | 0.3979 [0.3531, 0.4366] | 0.9776 [0.9617, 0.9896] | 0.5797 [0.5480, 0.6140] | 132 | 294 / 1:26:26 |
| plus15_to_plus30 | M2 delta | 0.1060 [0.0947, 0.1171] | 0.3889 [0.3492, 0.4244] | 0.9598 [0.9419, 0.9773] | 0.5708 [0.5315, 0.6055] | 132 | 295 / 1:25:25 |
| plus30_to_plus45 | M1 delta | 0.0662 [0.0570, 0.0748] | 0.3762 [0.3306, 0.4187] | 0.9899 [0.9810, 0.9961] | 0.6136 [0.5714, 0.6604] | 123 | 277 / 1:32:32 |
| plus30_to_plus45 | M2 delta | 0.0698 [0.0598, 0.0788] | 0.3752 [0.3304, 0.4161] | 0.9877 [0.9788, 0.9942] | 0.6125 [0.5701, 0.6594] | 123 | 278 / 1:31:31 |

### Q1 distance-response fits and fallback audit

Every held-out game/team/horizon/bin fit is in the JSON, including its training pair counts, nine training games, prediction, held-out pair count, and fallback flag.

| Series | Team-specific fits | Pooled fallback fits | Fallback rate |
|---|---:|---:|---:|
| M0_raw | 240 | 0 | 0.000 |
| M1_candidate_DIAG4 | 240 | 0 | 0.000 |
| M2_candidate_DIAG4 | 240 | 0 | 0.000 |
| M1_delta_DIAG5 | 240 | 0 | 0.000 |
| M2_delta_DIAG5 | 240 | 0 | 0.000 |
| M1_delta_Q1_raw | 240 | 0 | 0.000 |
| M2_delta_Q1_raw | 240 | 0 | 0.000 |

### Distance-bin pair counts

| Horizon | Bin 1 | Bin 2 | Bin 3 | Bin 4 | Total |
|---:|---:|---:|---:|---:|---:|
| +15 | 617 | 598 | 635 | 692 | 2542 |
| +30 | 579 | 570 | 571 | 609 | 2329 |
| +45 | 541 | 541 | 541 | 541 | 2164 |

Cutpoint byte check: `a049b73dc4b2beed033eefcc2217ffe8f92ebcdea4da1464d3d5ae14f1e138b0`; exact match to DIAG4 and DIAG5: **True**.

## Q2. Raw versus distance-conditioned P1

For candidate-only rows the DIAG4 team×horizon offset is applied first. For delta rows the DIAG5 team×horizon offset is applied first. Each row's raw and conditioned gaps use the same matched cells; retained-fraction intervals use the shared game bootstrap matrix.

| Transition | Series | Raw gap [95%] | Conditioned gap [95%] | Retained fraction [95%] | Matched EqualTeam starts | Matched cells / zero-mass raw:conditioned:either |
|---|---|---:|---:|---:|---:|---:|
| plus15_to_plus45 | M0_raw | 0.2883 [0.2477, 0.3381] | 0.2684 [0.2346, 0.2983] | 0.9310 [0.8226, 1.0492] | 110 | 270 / 23:37:41 |
| plus15_to_plus45 | M1_candidate_DIAG4 | 0.2820 [0.2432, 0.3193] | 0.2750 [0.2346, 0.3136] | 0.9751 [0.9120, 1.0360] | 112 | 273 / 30:36:38 |
| plus15_to_plus45 | M2_candidate_DIAG4 | 0.2802 [0.2387, 0.3199] | 0.2758 [0.2300, 0.3201] | 0.9844 [0.9199, 1.0591] | 112 | 273 / 30:36:38 |
| plus15_to_plus45 | M1_delta_DIAG5 | 0.3870 [0.3468, 0.4289] | 0.3457 [0.3026, 0.3875] | 0.8934 [0.8418, 0.9474] | 100 | 247 / 56:32:64 |
| plus15_to_plus45 | M2_delta_DIAG5 | 0.3572 [0.3195, 0.3960] | 0.3373 [0.2993, 0.3729] | 0.9443 [0.8955, 0.9960] | 103 | 252 / 51:32:59 |
| plus15_to_plus30 | M0_raw | 0.3659 [0.3307, 0.3944] | 0.3592 [0.3307, 0.3860] | 0.9819 [0.9408, 1.0312] | 115 | 282 / 24:31:38 |
| plus15_to_plus30 | M1_candidate_DIAG4 | 0.3630 [0.3296, 0.3961] | 0.3589 [0.3294, 0.3888] | 0.9886 [0.9557, 1.0191] | 119 | 284 / 30:34:36 |
| plus15_to_plus30 | M2_candidate_DIAG4 | 0.3600 [0.3269, 0.3927] | 0.3562 [0.3241, 0.3879] | 0.9892 [0.9641, 1.0136] | 119 | 284 / 30:33:36 |
| plus15_to_plus30 | M1_delta_DIAG5 | 0.4041 [0.3625, 0.4469] | 0.3632 [0.3166, 0.4073] | 0.8988 [0.8465, 0.9543] | 105 | 262 / 51:27:58 |
| plus15_to_plus30 | M2_delta_DIAG5 | 0.3773 [0.3359, 0.4187] | 0.3580 [0.3145, 0.3993] | 0.9487 [0.9014, 1.0003] | 107 | 265 / 51:27:55 |
| plus30_to_plus45 | M0_raw | 0.3925 [0.3720, 0.4146] | 0.3807 [0.3518, 0.4101] | 0.9698 [0.9078, 1.0337] | 109 | 268 / 23:37:41 |
| plus30_to_plus45 | M1_candidate_DIAG4 | 0.3857 [0.3577, 0.4161] | 0.3907 [0.3631, 0.4183] | 1.0130 [0.9676, 1.0602] | 111 | 271 / 30:36:38 |
| plus30_to_plus45 | M2_candidate_DIAG4 | 0.3877 [0.3586, 0.4182] | 0.3925 [0.3632, 0.4209] | 1.0124 [0.9676, 1.0586] | 111 | 271 / 30:36:38 |
| plus30_to_plus45 | M1_delta_DIAG5 | 0.4047 [0.3652, 0.4439] | 0.3413 [0.3020, 0.3792] | 0.8435 [0.7865, 0.8981] | 99 | 245 / 56:32:64 |
| plus30_to_plus45 | M2_delta_DIAG5 | 0.4050 [0.3658, 0.4438] | 0.3465 [0.3101, 0.3836] | 0.8557 [0.8142, 0.8980] | 102 | 250 / 51:32:59 |

## Q3. Within-cell covariance decomposition

The four bin means and within-bin covariances use empirical pair-frequency weights, so between-bin plus within-bin equals the total within-cell covariance. Each series is aggregated EqualTeam, then by equal game; rank results use centered midranks within each cell.

| Series | Scale | Between-bin covariance [95%] | Within-bin covariance [95%] | Total covariance [95%] | Between-bin share [95%] | Within-bin share [95%] | Cells / starts |
|---|---|---:|---:|---:|---:|---:|---:|
| M0_raw | raw feet | 7.28822 [6.10130, 8.61398] | 7.59782 [6.30828, 8.87321] | 14.88604 [12.77764, 16.96908] | 0.490 [0.443, 0.539] | 0.510 [0.461, 0.557] | 284 / 142 |
| M0_raw | within-cell ranks | 1.25077 [1.01923, 1.50798] | 1.96153 [1.66040, 2.30502] | 3.21231 [2.71244, 3.76828] | 0.389 [0.360, 0.423] | 0.611 [0.577, 0.640] | 284 / 142 |
| M1_delta | raw feet | 1.10561 [0.96850, 1.28639] | 0.70624 [0.61970, 0.79511] | 1.81185 [1.65052, 2.00295] | 0.610 [0.563, 0.658] | 0.390 [0.342, 0.437] | 284 / 142 |
| M1_delta | within-cell ranks | 2.07900 [1.80774, 2.37604] | 2.67875 [2.31102, 3.03735] | 4.75776 [4.18918, 5.33611] | 0.437 [0.406, 0.469] | 0.563 [0.531, 0.594] | 284 / 142 |
| M2_delta | raw feet | 1.12564 [0.98686, 1.30630] | 0.77530 [0.66676, 0.89074] | 1.90094 [1.73444, 2.08912] | 0.592 [0.540, 0.646] | 0.408 [0.354, 0.460] | 284 / 142 |
| M2_delta | within-cell ranks | 2.03498 [1.77406, 2.32159] | 2.58619 [2.21219, 2.96053] | 4.62117 [4.04441, 5.21777] | 0.440 [0.411, 0.471] | 0.560 [0.529, 0.589] | 284 / 142 |

## Q4. Spread, game variation, sign, and zeros

### Raw and residual pair spread

A flag means either residual SD or IQR is at most half its raw value; in that series/horizon a null is underpowered for a refutation.

| Series | Horizon | Raw SD | Residual SD | SD ratio | Raw IQR | Residual IQR | IQR ratio | Underpowered flag |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M0_raw | +15 | 3.0877 | 3.0298 | 0.981 | 3.8622 | 3.7802 | 0.979 | False |
| M0_raw | +30 | 6.6866 | 6.3569 | 0.951 | 8.5037 | 8.0338 | 0.945 | False |
| M0_raw | +45 | 9.9083 | 9.0505 | 0.913 | 12.4979 | 11.6761 | 0.934 | False |
| M1_candidate_DIAG4 | +15 | 3.2835 | 3.2906 | 1.002 | 4.2112 | 4.2346 | 1.006 | False |
| M1_candidate_DIAG4 | +30 | 6.8550 | 6.7870 | 0.990 | 8.8417 | 8.6231 | 0.975 | False |
| M1_candidate_DIAG4 | +45 | 9.7091 | 9.4030 | 0.968 | 12.2278 | 12.3007 | 1.006 | False |
| M2_candidate_DIAG4 | +15 | 3.2905 | 3.2985 | 1.002 | 4.2367 | 4.3008 | 1.015 | False |
| M2_candidate_DIAG4 | +30 | 6.8572 | 6.7904 | 0.990 | 8.8878 | 8.7130 | 0.980 | False |
| M2_candidate_DIAG4 | +45 | 9.7012 | 9.3982 | 0.969 | 12.2447 | 12.2407 | 1.000 | False |
| M1_delta_DIAG5 | +15 | 1.0420 | 0.9381 | 0.900 | 1.3430 | 1.0779 | 0.803 | False |
| M1_delta_DIAG5 | +30 | 2.1662 | 1.9056 | 0.880 | 2.8801 | 2.2047 | 0.766 | False |
| M1_delta_DIAG5 | +45 | 3.0274 | 2.6061 | 0.861 | 4.0477 | 3.1099 | 0.768 | False |
| M2_delta_DIAG5 | +15 | 1.0921 | 0.9905 | 0.907 | 1.3963 | 1.1618 | 0.832 | False |
| M2_delta_DIAG5 | +30 | 2.2018 | 1.9419 | 0.882 | 2.9382 | 2.2731 | 0.774 | False |
| M2_delta_DIAG5 | +45 | 3.0550 | 2.6293 | 0.861 | 4.1024 | 3.1430 | 0.766 | False |
| M1_delta_Q1_raw | +15 | 1.0381 | 0.9337 | 0.899 | 1.3333 | 1.0804 | 0.810 | False |
| M1_delta_Q1_raw | +30 | 2.1602 | 1.8978 | 0.879 | 2.8531 | 2.1795 | 0.764 | False |
| M1_delta_Q1_raw | +45 | 3.0176 | 2.5923 | 0.859 | 4.0282 | 3.1071 | 0.771 | False |
| M2_delta_Q1_raw | +15 | 1.0883 | 0.9863 | 0.906 | 1.3833 | 1.1576 | 0.837 | False |
| M2_delta_Q1_raw | +30 | 2.1957 | 1.9342 | 0.881 | 2.9029 | 2.2543 | 0.777 | False |
| M2_delta_Q1_raw | +45 | 3.0451 | 2.6156 | 0.859 | 4.0590 | 3.1510 | 0.776 | False |

### Primary per-game gaps and retained fractions

Each held-out game is excluded from its own distance-response fit.

**M0_raw**

| Game | Raw gap | Conditioned gap | Retained fraction |
|---|---:|---:|---:|
| 2025-10-11.Team.A.@.Team.D | 0.2847 | 0.3323 | 1.1672 |
| 2025-10-17.Team.F.@.Team.L | 0.4738 | 0.3213 | 0.6781 |
| 2025-10-24.Team.B.@.Team.A | 0.2282 | 0.2329 | 1.0207 |
| 2025-10-24.Team.E.@.Team.D | 0.3226 | 0.2813 | 0.8722 |
| 2025-10-28.Team.C.@.Team.A | 0.3503 | 0.3190 | 0.9106 |
| 2025-10-29.Team.G.@.Team.L | 0.2681 | 0.2601 | 0.9700 |
| 2025-11-02.Team.D.@.Team.A | 0.2252 | 0.1571 | 0.6974 |
| 2025-11-16.Team.H.@.Team.K | 0.2131 | 0.2674 | 1.2545 |
| 2025-11-19.Team.I.@.Team.K | 0.2447 | 0.2148 | 0.8780 |
| 2025-11-28.Team.J.@.Team.K | 0.2719 | 0.2976 | 1.0944 |

**M1_candidate_DIAG4**

| Game | Raw gap | Conditioned gap | Retained fraction |
|---|---:|---:|---:|
| 2025-10-11.Team.A.@.Team.D | 0.3191 | 0.3348 | 1.0493 |
| 2025-10-17.Team.F.@.Team.L | 0.3504 | 0.3548 | 1.0128 |
| 2025-10-24.Team.B.@.Team.A | 0.2524 | 0.2610 | 1.0339 |
| 2025-10-24.Team.E.@.Team.D | 0.3134 | 0.3563 | 1.1370 |
| 2025-10-28.Team.C.@.Team.A | 0.2489 | 0.2523 | 1.0137 |
| 2025-10-29.Team.G.@.Team.L | 0.3872 | 0.3235 | 0.8354 |
| 2025-11-02.Team.D.@.Team.A | 0.1529 | 0.1402 | 0.9166 |
| 2025-11-16.Team.H.@.Team.K | 0.2475 | 0.2477 | 1.0010 |
| 2025-11-19.Team.I.@.Team.K | 0.2860 | 0.2452 | 0.8572 |
| 2025-11-28.Team.J.@.Team.K | 0.2626 | 0.2345 | 0.8928 |

**M2_candidate_DIAG4**

| Game | Raw gap | Conditioned gap | Retained fraction |
|---|---:|---:|---:|
| 2025-10-11.Team.A.@.Team.D | 0.3195 | 0.3354 | 1.0498 |
| 2025-10-17.Team.F.@.Team.L | 0.3647 | 0.3598 | 0.9867 |
| 2025-10-24.Team.B.@.Team.A | 0.2318 | 0.2424 | 1.0455 |
| 2025-10-24.Team.E.@.Team.D | 0.3067 | 0.3790 | 1.2361 |
| 2025-10-28.Team.C.@.Team.A | 0.2537 | 0.2567 | 1.0120 |
| 2025-10-29.Team.G.@.Team.L | 0.3856 | 0.3417 | 0.8862 |
| 2025-11-02.Team.D.@.Team.A | 0.1431 | 0.1300 | 0.9089 |
| 2025-11-16.Team.H.@.Team.K | 0.2467 | 0.2349 | 0.9525 |
| 2025-11-19.Team.I.@.Team.K | 0.2885 | 0.2457 | 0.8518 |
| 2025-11-28.Team.J.@.Team.K | 0.2613 | 0.2319 | 0.8876 |

**M1_delta_DIAG5**

| Game | Raw gap | Conditioned gap | Retained fraction |
|---|---:|---:|---:|
| 2025-10-11.Team.A.@.Team.D | 0.2870 | 0.2274 | 0.7924 |
| 2025-10-17.Team.F.@.Team.L | 0.4146 | 0.3679 | 0.8874 |
| 2025-10-24.Team.B.@.Team.A | 0.4532 | 0.3784 | 0.8351 |
| 2025-10-24.Team.E.@.Team.D | 0.4985 | 0.4688 | 0.9405 |
| 2025-10-28.Team.C.@.Team.A | 0.3671 | 0.3232 | 0.8804 |
| 2025-10-29.Team.G.@.Team.L | 0.3149 | 0.3256 | 1.0341 |
| 2025-11-02.Team.D.@.Team.A | 0.3460 | 0.3655 | 1.0564 |
| 2025-11-16.Team.H.@.Team.K | 0.3251 | 0.2364 | 0.7273 |
| 2025-11-19.Team.I.@.Team.K | 0.4017 | 0.3639 | 0.9058 |
| 2025-11-28.Team.J.@.Team.K | 0.4615 | 0.3998 | 0.8663 |

**M2_delta_DIAG5**

| Game | Raw gap | Conditioned gap | Retained fraction |
|---|---:|---:|---:|
| 2025-10-11.Team.A.@.Team.D | 0.2873 | 0.2328 | 0.8102 |
| 2025-10-17.Team.F.@.Team.L | 0.3491 | 0.3429 | 0.9822 |
| 2025-10-24.Team.B.@.Team.A | 0.4261 | 0.3993 | 0.9370 |
| 2025-10-24.Team.E.@.Team.D | 0.4230 | 0.4265 | 1.0082 |
| 2025-10-28.Team.C.@.Team.A | 0.3325 | 0.3212 | 0.9659 |
| 2025-10-29.Team.G.@.Team.L | 0.3086 | 0.3296 | 1.0682 |
| 2025-11-02.Team.D.@.Team.A | 0.3345 | 0.3556 | 1.0631 |
| 2025-11-16.Team.H.@.Team.K | 0.2583 | 0.2332 | 0.9027 |
| 2025-11-19.Team.I.@.Team.K | 0.4083 | 0.3618 | 0.8859 |
| 2025-11-28.Team.J.@.Team.K | 0.4441 | 0.3701 | 0.8334 |

### Conditioned sign reversal

The forward and sign-reversed statistics reuse the same eligible source cells, pair rows, and permutation maps. EqualTeam start counts differ where a reversed orientation has zero negative mass and its P1 statistic is undefined.

| Candidate | Direction | Observed [95%] | Null [95%] | Gap [95%] | EqualTeam starts |
|---|---|---:|---:|---:|---:|
| M1 | d | 0.9639 [0.9532, 0.9744] | 0.5887 [0.5499, 0.6313] | 0.3752 [0.3284, 0.4184] | 124 |
| M1 | minus_d | 0.9686 [0.9552, 0.9826] | 0.4731 [0.4301, 0.5152] | 0.4955 [0.4577, 0.5344] | 81 |
| M2 | d | 0.9427 [0.9213, 0.9623] | 0.5838 [0.5380, 0.6255] | 0.3589 [0.3147, 0.4012] | 124 |
| M2 | minus_d | 0.9527 [0.9340, 0.9699] | 0.4701 [0.4301, 0.5097] | 0.4826 [0.4471, 0.5217] | 83 |

Exact zeros / zero negative mass on raw and conditioned delta series:

- M1 +15: raw exact zero 0/2542; conditioned exact zero 0/2542; +45 zero negative mass raw/conditioned None/None.
- M1 +30: raw exact zero 0/2329; conditioned exact zero 0/2329; +45 zero negative mass raw/conditioned None/None.
- M1 +45: raw exact zero 0/2164; conditioned exact zero 0/2164; +45 zero negative mass raw/conditioned 156/1053.
- M2 +15: raw exact zero 0/2542; conditioned exact zero 0/2542; +45 zero negative mass raw/conditioned None/None.
- M2 +30: raw exact zero 0/2329; conditioned exact zero 0/2329; +45 zero negative mass raw/conditioned None/None.
- M2 +45: raw exact zero 0/2164; conditioned exact zero 0/2164; +45 zero negative mass raw/conditioned 161/1048.

## Decision

Both candidates retain a positive distance-conditioned Q1 gap: M1 conditioned Q1 gap 0.3752 [0.3284, 0.4184]; Q3 between-bin share raw/rank 0.610/0.437; M2 conditioned Q1 gap 0.3589 [0.3147, 0.4012]; Q3 between-bin share raw/rank 0.592/0.440. The Q3 raw-scale shares are above 50%, while both within-cell rank shares are below 50%; the scale and rank readings therefore disagree under the preregistered rule. The registered conclusion is mixed: the frozen distance response does not eliminate the measured persistence, and this comparison cannot assign the remainder to pair identity or a behavioral mechanism. Do not narrate a winner; no pair-intent label program is justified by this evidence. Primary values: M1: conditioned Q1 gap 0.3752 [0.3284, 0.4184]; DIAG5-corrected delta retained fraction 0.8934 [0.8418, 0.9474]; M2: conditioned Q1 gap 0.3589 [0.3147, 0.4012]; DIAG5-corrected delta retained fraction 0.9443 [0.8955, 0.9960].

This remains a descriptive comparison within the ten inspected games. The tracking timebase is ordinal, and the result does not identify a behavioral mechanism.

## Reproduction

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_distance_conditioned_persistence.py --gate-only
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_distance_conditioned_persistence.py
git diff --check
/usr/bin/python3 -B -c 'import ast,pathlib; ast.parse(pathlib.Path("research/nhl-multi-agent-movement-2026-10-23/diagnose_distance_conditioned_persistence.py").read_text())'
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_distance_conditioned_persistence.py --output /tmp/jc-diag6-distance-conditioned-repeat.json --no-report
cmp research/nhl-multi-agent-movement-2026-10-23/results/jc-diag6-distance-conditioned-2026-10-23-v1.json /tmp/jc-diag6-distance-conditioned-repeat.json
```
