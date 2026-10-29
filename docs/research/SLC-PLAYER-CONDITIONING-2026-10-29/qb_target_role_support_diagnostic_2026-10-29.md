# QB target-role shrinkage and support diagnostic

The 2024 holdout selects the QB-specific shrinkage strength. The selected value is evaluated unchanged on the 2025 chronological holdout. Positive improvement means lower loss than the named baseline.

| Holdout | Population | Rows | Games | Shrinkage | Log-loss improvement vs team (95% CI) | Brier improvement vs team (95% CI) | Log-loss improvement vs pooled |
|---:|---|---:|---:|---:|---:|---:|---:|
| 2024 | all_targets | 16983 | 272 | 0 | -0.80487 [-0.90825, -0.71008] | -0.03004 [-0.03391, -0.02593] | -0.81102 |
| 2024 | all_targets | 16983 | 272 | 5 | -0.01654 [-0.01960, -0.01365] | -0.00784 [-0.00938, -0.00634] | -0.02268 |
| 2024 | all_targets | 16983 | 272 | 10 | -0.01007 [-0.01212, -0.00797] | -0.00492 [-0.00608, -0.00385] | -0.01622 |
| 2024 | all_targets | 16983 | 272 | 20 | -0.00583 [-0.00744, -0.00437] | -0.00288 [-0.00368, -0.00211] | -0.01198 |
| 2024 | all_targets | 16983 | 272 | 40 | -0.00323 [-0.00417, -0.00229] | -0.00159 [-0.00215, -0.00108] | -0.00937 |
| 2024 | all_targets | 16983 | 272 | 80 | -0.00172 [-0.00232, -0.00113] | -0.00084 [-0.00119, -0.00049] | -0.00787 |
| 2024 | all_targets | 16983 | 272 | 160 | -0.00089 [-0.00124, -0.00053] | -0.00043 [-0.00064, -0.00022] | -0.00704 |
| 2024 | actual_role_in_pregame_depth_chart | 16971 | 272 | 0 | -0.80172 [-0.90181, -0.71297] | -0.02994 [-0.03421, -0.02577] | -0.80757 |
| 2024 | actual_role_in_pregame_depth_chart | 16971 | 272 | 5 | -0.01622 [-0.01937, -0.01338] | -0.00783 [-0.00948, -0.00634] | -0.02208 |
| 2024 | actual_role_in_pregame_depth_chart | 16971 | 272 | 10 | -0.00985 [-0.01214, -0.00770] | -0.00491 [-0.00609, -0.00383] | -0.01571 |
| 2024 | actual_role_in_pregame_depth_chart | 16971 | 272 | 20 | -0.00568 [-0.00715, -0.00429] | -0.00288 [-0.00371, -0.00210] | -0.01154 |
| 2024 | actual_role_in_pregame_depth_chart | 16971 | 272 | 40 | -0.00313 [-0.00418, -0.00220] | -0.00159 [-0.00213, -0.00106] | -0.00899 |
| 2024 | actual_role_in_pregame_depth_chart | 16971 | 272 | 80 | -0.00167 [-0.00234, -0.00107] | -0.00084 [-0.00118, -0.00050] | -0.00753 |
| 2024 | actual_role_in_pregame_depth_chart | 16971 | 272 | 160 | -0.00086 [-0.00123, -0.00053] | -0.00043 [-0.00061, -0.00022] | -0.00672 |
| 2024 | receiver_id_and_role_in_pregame_depth_chart | 16114 | 272 | 0 | -0.79956 [-0.88962, -0.71189] | -0.03003 [-0.03429, -0.02565] | -0.80610 |
| 2024 | receiver_id_and_role_in_pregame_depth_chart | 16114 | 272 | 5 | -0.01664 [-0.02025, -0.01357] | -0.00804 [-0.00970, -0.00642] | -0.02318 |
| 2024 | receiver_id_and_role_in_pregame_depth_chart | 16114 | 272 | 10 | -0.01021 [-0.01256, -0.00798] | -0.00511 [-0.00631, -0.00402] | -0.01674 |
| 2024 | receiver_id_and_role_in_pregame_depth_chart | 16114 | 272 | 20 | -0.00596 [-0.00751, -0.00426] | -0.00304 [-0.00387, -0.00222] | -0.01250 |
| 2024 | receiver_id_and_role_in_pregame_depth_chart | 16114 | 272 | 40 | -0.00334 [-0.00434, -0.00238] | -0.00172 [-0.00228, -0.00114] | -0.00988 |
| 2024 | receiver_id_and_role_in_pregame_depth_chart | 16114 | 272 | 80 | -0.00181 [-0.00249, -0.00117] | -0.00093 [-0.00126, -0.00054] | -0.00834 |
| 2024 | receiver_id_and_role_in_pregame_depth_chart | 16114 | 272 | 160 | -0.00095 [-0.00135, -0.00058] | -0.00048 [-0.00071, -0.00027] | -0.00748 |
| 2025 | all_targets | 16588 | 272 | 0 | -0.88154 [-1.01145, -0.75828] | -0.03160 [-0.03687, -0.02628] | -0.88551 |
| 2025 | all_targets | 16588 | 272 | 5 | -0.01951 [-0.02266, -0.01658] | -0.00881 [-0.01049, -0.00720] | -0.02347 |
| 2025 | all_targets | 16588 | 272 | 10 | -0.01230 [-0.01477, -0.00999] | -0.00577 [-0.00696, -0.00450] | -0.01626 |
| 2025 | all_targets | 16588 | 272 | 20 | -0.00734 [-0.00894, -0.00576] | -0.00355 [-0.00441, -0.00263] | -0.01131 |
| 2025 | all_targets | 16588 | 272 | 40 | -0.00414 [-0.00514, -0.00312] | -0.00205 [-0.00264, -0.00151] | -0.00810 |
| 2025 | all_targets | 16588 | 272 | 80 | -0.00221 [-0.00292, -0.00153] | -0.00111 [-0.00149, -0.00074] | -0.00618 |
| 2025 | all_targets | 16588 | 272 | 160 | -0.00114 [-0.00154, -0.00072] | -0.00058 [-0.00080, -0.00035] | -0.00510 |
| 2025 | actual_role_in_pregame_depth_chart | 16551 | 272 | 0 | -0.87164 [-1.00235, -0.74999] | -0.03167 [-0.03654, -0.02705] | -0.87460 |
| 2025 | actual_role_in_pregame_depth_chart | 16551 | 272 | 5 | -0.01869 [-0.02182, -0.01588] | -0.00882 [-0.01045, -0.00731] | -0.02164 |
| 2025 | actual_role_in_pregame_depth_chart | 16551 | 272 | 10 | -0.01171 [-0.01397, -0.00950] | -0.00578 [-0.00706, -0.00466] | -0.01467 |
| 2025 | actual_role_in_pregame_depth_chart | 16551 | 272 | 20 | -0.00694 [-0.00857, -0.00545] | -0.00356 [-0.00445, -0.00264] | -0.00990 |
| 2025 | actual_role_in_pregame_depth_chart | 16551 | 272 | 40 | -0.00388 [-0.00504, -0.00284] | -0.00205 [-0.00264, -0.00145] | -0.00683 |
| 2025 | actual_role_in_pregame_depth_chart | 16551 | 272 | 80 | -0.00205 [-0.00273, -0.00142] | -0.00111 [-0.00151, -0.00074] | -0.00500 |
| 2025 | actual_role_in_pregame_depth_chart | 16551 | 272 | 160 | -0.00105 [-0.00145, -0.00064] | -0.00058 [-0.00081, -0.00034] | -0.00400 |
| 2025 | receiver_id_and_role_in_pregame_depth_chart | 16437 | 272 | 0 | -0.87787 [-1.01405, -0.74560] | -0.03196 [-0.03726, -0.02735] | -0.88065 |
| 2025 | receiver_id_and_role_in_pregame_depth_chart | 16437 | 272 | 5 | -0.01888 [-0.02207, -0.01580] | -0.00893 [-0.01056, -0.00731] | -0.02166 |
| 2025 | receiver_id_and_role_in_pregame_depth_chart | 16437 | 272 | 10 | -0.01184 [-0.01411, -0.00962] | -0.00586 [-0.00714, -0.00471] | -0.01462 |
| 2025 | receiver_id_and_role_in_pregame_depth_chart | 16437 | 272 | 20 | -0.00702 [-0.00854, -0.00556] | -0.00361 [-0.00450, -0.00272] | -0.00980 |
| 2025 | receiver_id_and_role_in_pregame_depth_chart | 16437 | 272 | 40 | -0.00393 [-0.00496, -0.00287] | -0.00209 [-0.00272, -0.00151] | -0.00670 |
| 2025 | receiver_id_and_role_in_pregame_depth_chart | 16437 | 272 | 80 | -0.00208 [-0.00275, -0.00144] | -0.00113 [-0.00155, -0.00078] | -0.00486 |
| 2025 | receiver_id_and_role_in_pregame_depth_chart | 16437 | 272 | 160 | -0.00106 [-0.00146, -0.00066] | -0.00059 [-0.00082, -0.00036] | -0.00384 |

**2024-selected own-QB shrinkage:** 160 observations.

## Exact-cell QB history support

The following groups use the current 20-observation shrinkage and compare against the team-conditioned baseline on all identified 2025 targets.

| QB/team/situation history rows | Targets | Games | Log-loss improvement | Brier improvement |
|---|---:|---:|---:|---:|
| 0 | 6118 | 230 | -0.00000 | -0.00000 |
| 1-4 | 1195 | 210 | -0.00166 | -0.00045 |
| 5-19 | 2499 | 244 | -0.01977 | -0.00986 |
| 20-49 | 3151 | 240 | -0.01588 | -0.00739 |
| 50+ | 3625 | 230 | -0.00562 | -0.00289 |

## Eligibility and limits

The depth-chart subset renormalizes over role groups listed for that team and date and, in its strictest form, scores only targets whose receiver GSIS ID is present in that chart. It does not reconstruct game-day injuries. 2025 historical injury rows lack `date_modified`; the result is therefore a role-roster proxy, not a complete frozen-roster validation.

The 2024 candidate sweep is tuning evidence. Treat the 2025 result as the chronological test. Neither result establishes full-game calibration or improved scoring/win probabilities.

See the JSON companion for fit and source hashes, row coverage, intervals, support counts and limitations.
