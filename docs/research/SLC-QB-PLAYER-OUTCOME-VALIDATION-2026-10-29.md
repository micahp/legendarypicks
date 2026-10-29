# SLC QB and player outcome holdout validation

Fit cutoff: before 2025 (2022, 2023, 2024); holdout: 2025.
Holdout source rows: 46452; E1-eligible player outcome rows: 34785.

Positive score improvement favors the player/QB model over the pooled baseline. Intervals resample complete NFL games.

| Distribution | Rows | Players | History rows | Log-loss improvement (95% CI) | Brier improvement (95% CI) |
|---|---:|---:|---:|---:|---:|
| qb_action | 19702 | 77 | 12449 | -0.00099 [-0.00212, +0.00015] | -0.00013 [-0.00036, +0.00010] |
| qb_event | 18235 | 77 | 15731 | +0.00016 [-0.00117, +0.00153] | +0.00017 [-0.00053, +0.00081] |
| qb_result_pass_complete | 11030 | 75 | 9594 | -0.00448 [-0.00707, -0.00200] | -0.00075 [-0.00150, -0.00006] |
| qb_result_sack | 1251 | 66 | 1015 | +0.00024 [-0.00930, +0.00856] | +0.00145 [-0.00253, +0.00561] |
| qb_target_role | 16588 | 76 | 10470 | -0.00734 [-0.00889, -0.00572] | -0.00355 [-0.00448, -0.00273] |
| receiver_event | 16320 | 500 | 13981 | +0.00746 [+0.00549, +0.00936] | +0.00602 [+0.00448, +0.00754] |
| receiver_result_pass_complete | 11041 | 474 | 9453 | +0.02066 [+0.01541, +0.02590] | +0.00592 [+0.00428, +0.00757] |
| rusher_event | 13900 | 329 | 11360 | +0.00012 [-0.00074, +0.00097] | +0.00001 [-0.00002, +0.00004] |
| rusher_result_fumble_lost | 69 | 55 | 44 | -0.00109 [-0.01115, +0.00967] | +0.00147 [-0.00375, +0.00655] |
| rusher_result_run | 13831 | 328 | 11295 | +0.00069 [-0.00279, +0.00398] | -0.00064 [-0.00180, +0.00053] |

## Limits

- QB action and target-role scores cover held-out nfl_pbp dropbacks and identified targets; target roles are not conditioned on a reconstructed frozen injury report.
- Player outcome scores use only 2025 rows eligible for the SLC E1 outcome pool and compare marginal player distributions with role-level pooled distributions.
- Scores do not reproduce SLC candidate-cell reweighting, the joint passer-receiver weighting, full-game state feedback, or scoring calibration.
- QB outcomes cover completions, incompletions, interceptions and sacks; this first slice does not model QB progressions, pressure response, throwaways or defensive adaptation.
- Game movement uses yards_gained. Player result distributions and box-score lines use passing_yards, receiving_yards or rushing_yards where present; missing role-specific fields fall back only for emitted box-score lines.

The JSON companion records model versions, source cutoffs, fitted-source hashes, holdout hash, source counts and bootstrap results.
