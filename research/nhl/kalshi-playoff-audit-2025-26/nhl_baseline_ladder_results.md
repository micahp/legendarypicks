# NHL statistical baseline ladder: evaluation results

Protocol preregistration SHA-256: `5f68719e1e923c5cf2203108252b19856a39cd318a3b93c578cf0988853fc4db`. See `backtest_preregistration_v1.md` for fixed splits and selection rules.
No market price was used as a model feature. Statistical goals use NHL regulation/overtime goals with the shootout decider removed; moneyline labels use official NHL winners including shootouts.

## Model selection and lock

Validation selected Elo K=10 and home-ice offset=35; recent-form logistic C=100.0; Poisson alphas: `{"combined": 0.01, "elo": 0.01, "goals": 0.01, "xg": 0.01}`.
Validation leaders: moneyline **B3** by Brier; goal distribution **B6** by joint score NLL. Coefficients were then refit only through 2021; all 2022–26 results are held out.

## Score prediction: does xG improve over Elo and historical goals?

Lower is better. Test comparisons use the exact same games; paired intervals resample games. `B3` is the Elo-to-goals mapping, `B4` uses rolling historical goals, `B5` uses rolling 5-on-5 score/venue-adjusted xG, and `B6` combines goals and xG.

| Sample | Model | Games | Goals MAE / team | Total goals MAE | Joint goal NLL |
| --- | --- | ---: | ---: | ---: | ---: |
| 2022–24 aggregate | B3 | 4193 | 1.3972 | 1.8893 | 3.8937 |
| 2022–24 aggregate | B4 | 4193 | 1.4046 | 1.8595 | 3.9005 |
| 2022–24 aggregate | B5 | 4193 | 1.3988 | 1.8483 | 3.8859 |
| 2022–24 aggregate | B6 | 4193 | 1.3981 | 1.8496 | 3.8810 |
| 2025–26 final season | B3 | 1394 | 1.3754 | 1.8643 | 3.8793 |
| 2025–26 final season | B4 | 1394 | 1.3706 | 1.8319 | 3.8673 |
| 2025–26 final season | B5 | 1394 | 1.3627 | 1.8235 | 3.8548 |
| 2025–26 final season | B6 | 1394 | 1.3634 | 1.8220 | 3.8513 |
| 2022 (holdout) | B3 | 1400 | 1.4060 | 1.8931 | 3.8994 |
| 2022 (holdout) | B4 | 1400 | 1.4094 | 1.8451 | 3.8998 |
| 2022 (holdout) | B5 | 1400 | 1.4055 | 1.8279 | 3.8833 |
| 2022 (holdout) | B6 | 1400 | 1.4021 | 1.8275 | 3.8746 |
| 2023 (holdout) | B3 | 1400 | 1.3911 | 1.8943 | 3.8928 |
| 2023 (holdout) | B4 | 1400 | 1.4015 | 1.8628 | 3.9027 |
| 2023 (holdout) | B5 | 1400 | 1.3958 | 1.8591 | 3.8914 |
| 2023 (holdout) | B6 | 1400 | 1.3951 | 1.8568 | 3.8844 |
| 2024 (holdout) | B3 | 1393 | 1.3946 | 1.8805 | 3.8888 |
| 2024 (holdout) | B4 | 1393 | 1.4030 | 1.8706 | 3.8990 |
| 2024 (holdout) | B5 | 1393 | 1.3952 | 1.8579 | 3.8829 |
| 2024 (holdout) | B6 | 1393 | 1.3971 | 1.8645 | 3.8842 |
| 2025 (holdout) | B3 | 1394 | 1.3754 | 1.8643 | 3.8793 |
| 2025 (holdout) | B4 | 1394 | 1.3706 | 1.8319 | 3.8673 |
| 2025 (holdout) | B5 | 1394 | 1.3627 | 1.8235 | 3.8548 |
| 2025 (holdout) | B6 | 1394 | 1.3634 | 1.8220 | 3.8513 |

### Paired xG deltas

Positive loss delta means xG model is worse than comparator; negative means it is better. 95% intervals are game-bootstrap intervals.

| Sample | xG model minus | Metric | Delta | 95% interval | Games |
| --- | --- | --- | ---: | ---: | ---: |
| locked_test_2022_2024 | B4 | per_game_team_goals_mae | -0.00578 | [-0.00987, -0.00151] | 4193 |
| locked_test_2022_2024 | B4 | joint_goal_nll | -0.01468 | [-0.02009, -0.00936] | 4193 |
| locked_test_2022_2024 | B3 | per_game_team_goals_mae | 0.00159 | [-0.00470, 0.00806] | 4193 |
| locked_test_2022_2024 | B3 | joint_goal_nll | -0.00784 | [-0.01577, 0.00042] | 4193 |
| locked_test_2022_2024 | B4 | per_game_team_goals_mae | -0.00652 | [-0.01004, -0.00293] | 4193 |
| locked_test_2022_2024 | B4 | joint_goal_nll | -0.01950 | [-0.02385, -0.01533] | 4193 |
| final_2025_26 | B4 | per_game_team_goals_mae | -0.00788 | [-0.01424, -0.00145] | 1394 |
| final_2025_26 | B4 | joint_goal_nll | -0.01253 | [-0.02021, -0.00474] | 1394 |
| final_2025_26 | B3 | per_game_team_goals_mae | -0.01263 | [-0.02222, -0.00333] | 1394 |
| final_2025_26 | B3 | joint_goal_nll | -0.02456 | [-0.03692, -0.01251] | 1394 |
| final_2025_26 | B4 | per_game_team_goals_mae | -0.00726 | [-0.01253, -0.00175] | 1394 |
| final_2025_26 | B4 | joint_goal_nll | -0.01604 | [-0.02204, -0.00992] | 1394 |

## Moneyline probability and calibration by season

Brier ranges from 0 (perfect) to 1 (worst); 0.25 is the score for constant 50% predictions. Because the NHL home-win rate is not exactly 50%, compare against B1's training-set home-win rate as well. Brier, log loss and ECE are lower-is-better. Calibration slope near 1 and intercept near 0 are ideal. Season metrics and all baselines are in `baseline_metrics_by_season.csv`.

| Season | Model | Games | Brier | Log loss | Cal. intercept | Cal. slope | ECE |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2018 | B0 | 1358 | 0.2500 | 0.6931 | 0.142 | 0.000 | 0.0353 |
| 2018 | B1 | 1358 | 0.2489 | 0.6910 | 0.136 | 0.027 | 0.0134 |
| 2018 | B2 | 1358 | 0.2474 | 0.6879 | -0.008 | 0.786 | 0.0138 |
| 2018 | B3 | 1358 | 0.2446 | 0.6825 | 0.010 | 0.665 | 0.0363 |
| 2018 | B4 | 1358 | 0.2474 | 0.6879 | -0.078 | 1.233 | 0.0122 |
| 2018 | B5 | 1358 | 0.2466 | 0.6862 | -0.179 | 1.776 | 0.0147 |
| 2018 | B6 | 1358 | 0.2460 | 0.6852 | -0.104 | 1.367 | 0.0212 |
| 2019 | B0 | 1212 | 0.2500 | 0.6931 | 0.099 | 0.000 | 0.0248 |
| 2019 | B1 | 1212 | 0.2500 | 0.6931 | 0.095 | 0.019 | 0.0240 |
| 2019 | B2 | 1212 | 0.2487 | 0.6905 | 0.022 | 0.589 | 0.0209 |
| 2019 | B3 | 1212 | 0.2456 | 0.6841 | -0.015 | 0.665 | 0.0379 |
| 2019 | B4 | 1212 | 0.2486 | 0.6903 | -0.104 | 1.135 | 0.0209 |
| 2019 | B5 | 1212 | 0.2476 | 0.6883 | -0.202 | 1.674 | 0.0267 |
| 2019 | B6 | 1212 | 0.2473 | 0.6876 | -0.129 | 1.273 | 0.0225 |
| 2020 | B0 | 952 | 0.2500 | 0.6931 | 0.139 | 0.000 | 0.0347 |
| 2020 | B1 | 952 | 0.2490 | 0.6911 | 0.134 | 0.026 | 0.0141 |
| 2020 | B2 | 952 | 0.2429 | 0.6788 | -0.145 | 1.421 | 0.0246 |
| 2020 | B3 | 952 | 0.2352 | 0.6632 | -0.042 | 0.940 | 0.0217 |
| 2020 | B4 | 952 | 0.2442 | 0.6815 | -0.270 | 2.259 | 0.0151 |
| 2020 | B5 | 952 | 0.2442 | 0.6814 | -0.319 | 2.478 | 0.0247 |
| 2020 | B6 | 952 | 0.2420 | 0.6769 | -0.233 | 2.006 | 0.0453 |
| 2021 | B0 | 1396 | 0.2500 | 0.6931 | 0.161 | 0.000 | 0.0401 |
| 2021 | B1 | 1396 | 0.2485 | 0.6901 | 0.155 | 0.030 | 0.0086 |
| 2021 | B2 | 1396 | 0.2409 | 0.6749 | -0.149 | 1.613 | 0.0317 |
| 2021 | B3 | 1396 | 0.2306 | 0.6535 | -0.026 | 1.003 | 0.0199 |
| 2021 | B4 | 1396 | 0.2436 | 0.6802 | -0.297 | 2.546 | 0.0099 |
| 2021 | B5 | 1396 | 0.2429 | 0.6789 | -0.356 | 2.794 | 0.0180 |
| 2021 | B6 | 1396 | 0.2407 | 0.6744 | -0.250 | 2.224 | 0.0434 |
| 2022 | B0 | 1400 | 0.2500 | 0.6931 | 0.080 | 0.000 | 0.0200 |
| 2022 | B1 | 1400 | 0.2502 | 0.6936 | 0.078 | 0.014 | 0.0246 |
| 2022 | B2 | 1400 | 0.2454 | 0.6837 | -0.122 | 1.147 | 0.0261 |
| 2022 | B3 | 1400 | 0.2368 | 0.6664 | -0.080 | 0.829 | 0.0378 |
| 2022 | B4 | 1400 | 0.2457 | 0.6845 | -0.225 | 1.780 | 0.0357 |
| 2022 | B5 | 1400 | 0.2438 | 0.6805 | -0.312 | 2.153 | 0.0391 |
| 2022 | B6 | 1400 | 0.2426 | 0.6780 | -0.224 | 1.698 | 0.0454 |
| 2023 | B0 | 1400 | 0.2500 | 0.6931 | 0.149 | 0.000 | 0.0371 |
| 2023 | B1 | 1400 | 0.2487 | 0.6905 | 0.144 | 0.026 | 0.0074 |
| 2023 | B2 | 1400 | 0.2441 | 0.6811 | -0.066 | 1.146 | 0.0202 |
| 2023 | B3 | 1400 | 0.2357 | 0.6639 | -0.007 | 0.809 | 0.0248 |
| 2023 | B4 | 1400 | 0.2442 | 0.6813 | -0.171 | 1.786 | 0.0204 |
| 2023 | B5 | 1400 | 0.2429 | 0.6788 | -0.288 | 2.474 | 0.0235 |
| 2023 | B6 | 1400 | 0.2414 | 0.6755 | -0.187 | 1.864 | 0.0274 |
| 2024 | B0 | 1393 | 0.2500 | 0.6931 | 0.261 | 0.000 | 0.0650 |
| 2024 | B1 | 1393 | 0.2462 | 0.6855 | 0.253 | 0.045 | 0.0204 |
| 2024 | B2 | 1393 | 0.2447 | 0.6824 | 0.127 | 0.757 | 0.0302 |
| 2024 | B3 | 1393 | 0.2389 | 0.6706 | 0.134 | 0.683 | 0.0384 |
| 2024 | B4 | 1393 | 0.2447 | 0.6824 | 0.078 | 1.063 | 0.0217 |
| 2024 | B5 | 1393 | 0.2412 | 0.6753 | -0.136 | 2.225 | 0.0289 |
| 2024 | B6 | 1393 | 0.2413 | 0.6756 | -0.023 | 1.602 | 0.0203 |
| 2025 | B0 | 1394 | 0.2500 | 0.6931 | 0.078 | 0.000 | 0.0194 |
| 2025 | B1 | 1394 | 0.2503 | 0.6937 | 0.075 | 0.013 | 0.0252 |
| 2025 | B2 | 1394 | 0.2493 | 0.6917 | -0.047 | 0.667 | 0.0362 |
| 2025 | B3 | 1394 | 0.2517 | 0.6976 | -0.006 | 0.419 | 0.0606 |
| 2025 | B4 | 1394 | 0.2487 | 0.6905 | -0.110 | 1.054 | 0.0260 |
| 2025 | B5 | 1394 | 0.2467 | 0.6865 | -0.262 | 1.859 | 0.0366 |
| 2025 | B6 | 1394 | 0.2466 | 0.6862 | -0.173 | 1.364 | 0.0354 |

## Separate Kalshi playoff comparison

Frozen comparison model: **B3** (chosen on validation Brier). Matched games: **80**. Kalshi probability is the home contract YES midpoint normalized against the away contract YES midpoint; both quotes are from the audited pregame snapshot. No quote was used for fitting or selection.

| Forecast | Games | Brier | Log loss | Cal. intercept | Cal. slope | ECE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 | 80 | 0.2500 | 0.6931 | -0.050 | 0.000 | 0.0125 |
| B1 | 80 | 0.2531 | 0.6994 | -0.048 | -0.009 | 0.0571 |
| B2 | 80 | 0.2503 | 0.6939 | -0.411 | 1.542 | 0.0804 |
| B3 | 80 | 0.2381 | 0.6687 | -0.409 | 1.611 | 0.0796 |
| B4 | 80 | 0.2486 | 0.6904 | -0.569 | 2.639 | 0.0611 |
| B5 | 80 | 0.2455 | 0.6839 | -0.827 | 3.992 | 0.0939 |
| B6 | 80 | 0.2442 | 0.6814 | -0.718 | 3.228 | 0.0635 |
| Kalshi normalized YES midpoints | 80 | 0.2357 | 0.6633 | -0.424 | 1.919 | 0.0882 |

Paired Brier loss difference (frozen model minus Kalshi): 0.00243, 95% game-bootstrap interval [-0.00785, 0.01278]. This 80-game sample is imprecise; it is an evaluation, not proof of a trading edge.

## Limitations and reproducibility

The final season and its Kalshi comparison were excluded from model selection. The statistical test covers the exact feature-ready rows, with model-specific paired metrics. The model uses no goalie or lineup inputs. Kalshi market comparison uses midpoints and evaluates probability accuracy, not executable returns, fees, liquidity, or trading performance.
Prediction rows are in `baseline_predictions_validation.csv` and `baseline_predictions_holdout_2022_2025.csv`; all score and probability metrics are in `baseline_metrics_by_season.csv`; paired deltas are in `baseline_paired_differences.csv`; the separate market sample is in `kalshi_playoff_model_comparison.csv`.
