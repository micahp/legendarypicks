# FBS direct player-prop baseline -- RESULTS

Direct two-stage count model (usage x efficiency), independent of the
Phase 4/5 play-by-play simulator. **Phases 4-6 status is UNCHANGED**: this is a
new parallel prototype and claims nothing about phases 4, 5 or 6.

Model: stage-1 usage is NegBin(predicted COUNT = shrunken trailing-5 rate x team^alpha x opp^beta, dispersion r); stage-2 efficiency is Normal(shrunken yards/attempt, eff_sd); yards markets are the product of the two, sampled by Monte Carlo (count and rate conditionally independent). For the yards markets the stage-1 count is the denominator (attempts / carries), not the yard total. Shrinkage pulls a low-history player toward the position mean; a player with no history is exactly the position mean. Dispersion is method-of-moments (the likelihood fit collapses on the zero-heavy backup population).

Leakage discipline: league priors and dispersion are fit on 2018-2023, the grid is selected on 2024 CRPS, then priors and dispersion are refit on 2018-2024 before 2025 is scored. 2026 props use per-fixture as-of features (source game strictly before kickoff, asserted).

## Coverage (data honesty)

       market            label positions   seasons  player_games  player_games_gt0  distinct_players  distinct_games   mean  median     sd  props_2026  props_2026_settled
pass_attempts passing attempts        QB 2018-2025         74765             18799              4256            6567  5.391     0.0 11.642         475                 414
passing_yards    passing yards        QB 2018-2025         74765             17729              4256            6567 39.511     0.0 89.672        3792                2768
rush_attempts  rushing carries     RB|QB 2018-2025        178748             58302             10392            6567  2.545     0.0  5.067         709                 611
rushing_yards    rushing yards     RB|QB 2018-2025        178748             51191             10392            6567 11.260     0.0 28.566        5161                3763

## Verdicts

| market | verdict | model CRPS | trailing-5 CRPS | position CRPS |
|---|---|---|---|---|
| pass_attempts | ADOPT_CANDIDATE | 2.8332 | 3.1534 | 4.8411 |
| passing_yards | ADOPT_CANDIDATE | 20.8795 | 23.7606 | 35.5530 |
| rush_attempts | ADOPT_CANDIDATE | 1.3785 | 1.5364 | 2.1567 |
| rushing_yards | ADOPT_CANDIDATE | 7.6625 | 9.2448 | 10.7809 |

## Tuned parameters (fit 2018-2023; selected on 2024; dispersion refit 2018-2024)

- `pass_attempts`: k=0.25, alpha=0.0, beta=0.0, r=2.231, k2=None, 2024 CRPS=2.6521
- `passing_yards`: k=0.25, alpha=0.0, beta=0.0, r=2.231, k2=10.0, 2024 CRPS=19.9691
- `rush_attempts`: k=0.25, alpha=0.0, beta=0.0, r=2.197, k2=None, 2024 CRPS=1.2398
- `rushing_yards`: k=0.25, alpha=0.0, beta=0.5, r=2.173, k2=10.0, 2024 CRPS=6.9134

## 2025 out-of-sample scoring (all methods)

    n      crps  logscore  pit_mean  pit_abs_dev                                       pit_hist    cov50    cov80    cov90  beyond_p99  brier_34.5        market                     method  season  brier_249.5  brier_14.5  brier_59.5
 9059  2.833228 -3.436590  0.427765     0.215007       786|465|874|4147|744|295|316|302|276|854 0.759024 0.842477 0.872171    0.056960    0.036970 pass_attempts                      model    2025          NaN         NaN         NaN
 9059  3.153430  2.528646  0.341159     0.276831       623|469|5897|143|193|293|250|232|237|722 0.784855 0.862788 0.898664    0.036980    0.038430 pass_attempts baseline_A_trailing5_fixed    2025          NaN         NaN         NaN
 9059  4.841119 -5.464788  0.514971     0.193815                  0|0|0|6522|3|0|0|515|1035|984 0.730323 0.894911 0.952423    0.007506    0.044411 pass_attempts baseline_B_position_league    2025          NaN         NaN         NaN
 9059 20.879549 -2.505769  0.430683     0.201377      630|488|814|2994|2132|279|385|307|325|705 0.779115 0.889171 0.932112    0.040843         NaN passing_yards                      model    2025     0.042160         NaN         NaN
 9059 23.760618  4.496116  0.332383     0.279085       649|522|6009|118|161|262|206|205|231|696 0.787835 0.864003 0.899437    0.036428         NaN passing_yards baseline_A_trailing5_fixed    2025     0.044663         NaN         NaN
 9059 35.553033 -4.903063  0.513501     0.186497                20|0|0|6590|60|0|0|354|1052|983 0.734960 0.889281 0.949111    0.007838         NaN passing_yards baseline_B_position_league    2025     0.056580         NaN         NaN
21800  1.378477 -3.608202  0.483150     0.194699 1400|1255|1713|2318|9117|747|796|901|1017|2536 0.739908 0.861697 0.907156    0.049908         NaN rush_attempts                      model    2025          NaN    0.033474         NaN
21800  1.536423  1.879508  0.364181     0.279861   1646|1882|11902|523|588|798|861|838|855|1907 0.736376 0.855826 0.902156    0.034037         NaN rush_attempts baseline_A_trailing5_fixed    2025          NaN    0.035151         NaN
21800  2.156731  1.756605  0.519288     0.224312             0|0|0|13879|0|0|569|2492|2518|2342 0.735688 0.900092 0.953440    0.007844         NaN rush_attempts baseline_B_position_league    2025          NaN    0.043679         NaN
21800  7.662539 -2.397471  0.475597     0.176605 1100|1259|1572|2667|9674|757|878|945|1037|1911 0.770183 0.877202 0.906514    0.028486         NaN rushing_yards                      model    2025          NaN         NaN    0.051319
21800  9.244801  3.868177  0.337902     0.278838   2072|1557|12591|508|579|898|753|689|619|1534 0.753257 0.847798 0.881972    0.032752         NaN rushing_yards baseline_A_trailing5_fixed    2025          NaN         NaN    0.055474
21800 10.780879  2.766503  0.517853     0.210500           741|0|0|14009|14|0|13|2194|2466|2363 0.686743 0.858303 0.913853    0.009266         NaN rushing_yards baseline_B_position_league    2025          NaN         NaN    0.068103

## 2025 error decomposition (model)

`opp_rmse` = opportunity (usage) error, `eff_rmse` = efficiency (rate) error, `inter_rmse` = interaction; `share_*` are the exact covariance shares of Var(point error) and sum to 1. `sd_ratio` = predicted SD / residual SD (1.0 = perfect dispersion, >1 over-dispersed, <1 under-dispersed).

 point_rmse  point_bias  opp_rmse  eff_rmse  inter_rmse  share_opp  share_eff  share_inter   pred_sd  resid_sd  sd_ratio        market
   7.634669   -0.391220  7.634669  0.000000    0.000000   1.000000   0.000000     0.000000  4.161742  7.624638  0.545828 pass_attempts
  57.745489   -2.137383 55.157716 39.379763   32.559876   0.815705   0.398458    -0.214163 43.894252 57.705919  0.760654 passing_yards
   3.550429   -0.212300  3.550429  0.000000    0.000000   1.000000   0.000000     0.000000  2.150880  3.544076  0.606894 rush_attempts
  22.048281   -0.884717 16.933206 15.160190   11.870122   0.573834   0.429264    -0.003099 16.497106 22.030524  0.748830 rushing_yards

**Which part failed.** The model's point means are competitive (it beats both baselines on CRPS in all four markets), so the conditional mean is not the problem. The remaining failure is *dispersion*: `sd_ratio` is 0.55-0.76 in every market, i.e. the predictive intervals are too narrow relative to the residuals. This is visible in the PIT summary as well -- `pit_abs_dev` sits above 0.19 and the outer PIT bins are over-filled (`pit_hist`), the signature of under-dispersion. On the error split, opportunity (usage) dominates everywhere: for the count markets the point error is 100% opportunity by construction; for the yards markets `share_opp` is 0.57-0.82 while efficiency contributes 0.40-0.43 and the interaction share is small or negative. So the next lever is widening the count dispersion (and the efficiency spread), not re-fitting the mean.

## 2026 prop board (real lines; as-of features, no leakage)

       market                     method    n  brier_actual_line  brier_realistic_line  mean_line
pass_attempts                      model  393           0.328287              0.218555  29.386768
pass_attempts baseline_A_trailing5_fixed  393           0.340612              0.244743  29.386768
pass_attempts baseline_B_position_league  393           0.430152              0.251396  29.386768
passing_yards                      model 2641           0.363138              0.251005 220.043733
passing_yards baseline_A_trailing5_fixed 2641           0.389435              0.268444 220.043733
passing_yards baseline_B_position_league 2641           0.436734              0.310008 220.043733
rush_attempts                      model  585           0.348431              0.247142  12.314530
rush_attempts baseline_A_trailing5_fixed  585           0.394139              0.285333  12.314530
rush_attempts baseline_B_position_league  585           0.404260              0.301298  12.314530
rushing_yards                      model 3575           0.301930              0.251052  54.073147
rushing_yards baseline_A_trailing5_fixed 3575           0.363891              0.317659  54.073147
rushing_yards baseline_B_position_league 3575           0.354700              0.308246  54.073147
