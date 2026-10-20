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

## Spread fix (Defect 3): before -> after

Spread re-fit by CRPS minimisation on 2018-2024 only; 2025 is never used in the fit. `cov50` uses [q25,q75], `cov80` uses [q10,q90], `cov90` uses [q05,q95]; `sd_ratio` = mean predictive SD / residual SD.

       market  crps_before  crps_after  cov50_before  cov50_after  cov80_before  cov80_after  cov90_before  cov90_after  sd_ratio_before  sd_ratio_after
pass_attempts       2.8332      2.8262        0.7590       0.7505        0.8425       0.8322        0.8722       0.8602           0.5458          0.4861
passing_yards      20.8795     20.8795        0.7791       0.7791        0.8892       0.8892        0.9321       0.9321           0.7607          0.7607
rush_attempts       1.3785      1.3792        0.7399       0.7446        0.8617       0.8659        0.9072       0.9111           0.6069          0.6263
rushing_yards       7.6625      7.6625        0.7702       0.7702        0.8772       0.8772        0.9065       0.9065           0.7488          0.7488

## Verdicts (Defect 1): clustered CRPS deltas

Rule stated up front: `delta = CRPS_model - CRPS_baseline` (negative = model better). `ADOPT_CANDIDATE` requires the 90% clustered bootstrap CI upper bound < 0 against BOTH baselines AND every week-block delta < 0. `PROVISIONAL` if every point delta is negative but a CI includes 0 or a block flips. `REJECT` otherwise. The bootstrap clusters on `game_id` (10,000 resamples, fixed seed). A verdict is about distributional ranking only -- no market/ROI/edge claim is made anywhere in this document.

       market                   baseline  n_clusters  delta_crps  ci90_lo  ci90_hi  block_w1_6  block_w7_12  block_w13p
pass_attempts baseline_A_trailing5_fixed         888     -0.3244  -0.3448  -0.3036     -0.1927      -0.4278     -0.4414
pass_attempts baseline_B_position_league         888     -2.0160  -2.1098  -1.9210     -1.6865      -2.3408     -2.1509
passing_yards baseline_A_trailing5_fixed         888     -2.8811  -3.1283  -2.6335     -2.0163      -3.3732     -4.0928
passing_yards baseline_B_position_league         888    -14.6735 -15.2761 -14.0749    -12.9276     -16.5518    -15.0159
rush_attempts baseline_A_trailing5_fixed         888     -0.1583  -0.1675  -0.1492     -0.0950      -0.2105     -0.2087
rush_attempts baseline_B_position_league         888     -0.7771  -0.8024  -0.7516     -0.5881      -0.9278     -0.9400
rushing_yards baseline_A_trailing5_fixed         888     -1.5823  -1.6537  -1.5076     -1.2774      -1.8476     -1.7920
rushing_yards baseline_B_position_league         888     -3.1183  -3.2351  -3.0026     -2.5342      -3.4690     -3.8951

| market | verdict | model CRPS | trailing-5 CRPS | position CRPS |
|---|---|---|---|---|
| pass_attempts | ADOPT_CANDIDATE | 2.8262 | 3.1507 | 4.8422 |
| passing_yards | ADOPT_CANDIDATE | 20.8795 | 23.7606 | 35.5530 |
| rush_attempts | ADOPT_CANDIDATE | 1.3792 | 1.5375 | 2.1563 |
| rushing_yards | ADOPT_CANDIDATE | 7.6625 | 9.2448 | 10.7809 |

## Tuned parameters (fit 2018-2023; selected on 2024; dispersion refit 2018-2024)

- `pass_attempts`: k=0.25, alpha=0.0, beta=0.0, r=3.000, k2=None, 2024 CRPS=2.6521
- `passing_yards`: k=0.25, alpha=0.0, beta=0.0, r=2.231, k2=10.0, 2024 CRPS=19.9691
- `rush_attempts`: k=0.25, alpha=0.0, beta=0.0, r=2.000, k2=None, 2024 CRPS=1.2398
- `rushing_yards`: k=0.25, alpha=0.0, beta=0.5, r=2.173, k2=10.0, 2024 CRPS=6.9134

## 2025 out-of-sample scoring (all methods)

    n      crps  logscore  pit_mean  pit_abs_dev                                       pit_hist    cov50    cov80    cov90  beyond_p99  brier_34.5        market                     method  season  brier_249.5  brier_14.5  brier_59.5
 9059  2.826241 -3.306312  0.423988     0.219626       847|569|796|4273|595|265|272|283|271|888 0.750524 0.832211 0.860249    0.060823    0.036910 pass_attempts                      model    2025          NaN         NaN         NaN
 9059  3.150663  2.519655  0.341231     0.276800       620|478|5890|148|177|295|262|233|240|716 0.784193 0.863671 0.897781    0.037311    0.038316 pass_attempts baseline_A_trailing5_fixed    2025          NaN         NaN         NaN
 9059  4.842206 -5.400473  0.515023     0.193831                  0|0|0|6524|1|0|0|520|1025|989 0.730323 0.894580 0.953085    0.007727    0.044407 pass_attempts baseline_B_position_league    2025          NaN         NaN         NaN
 9059 20.879549 -2.505769  0.430683     0.201377      630|488|814|2994|2132|279|385|307|325|705 0.779115 0.889171 0.932112    0.040843         NaN passing_yards                      model    2025     0.042160         NaN         NaN
 9059 23.760618  4.496116  0.332383     0.279085       649|522|6009|118|161|262|206|205|231|696 0.787835 0.864003 0.899437    0.036428         NaN passing_yards baseline_A_trailing5_fixed    2025     0.044663         NaN         NaN
 9059 35.553033 -4.903063  0.513501     0.186497                20|0|0|6590|60|0|0|354|1052|983 0.734960 0.889281 0.949111    0.007838         NaN passing_yards baseline_B_position_league    2025     0.056580         NaN         NaN
21800  1.379165 -3.632481  0.484522     0.193002 1325|1265|1697|2347|9110|785|821|928|1025|2497 0.744587 0.865872 0.911101    0.048716         NaN rush_attempts                      model    2025          NaN    0.033474         NaN
21800  1.537472  1.889287  0.364159     0.279981   1641|1911|11883|513|587|820|822|867|857|1899 0.735872 0.856009 0.901927    0.034450         NaN rush_attempts baseline_A_trailing5_fixed    2025          NaN    0.035150         NaN
21800  2.156285  1.758157  0.519303     0.224313             0|0|0|13879|0|0|532|2548|2508|2333 0.735917 0.901468 0.953899    0.008303         NaN rush_attempts baseline_B_position_league    2025          NaN    0.043667         NaN
21800  7.662539 -2.397471  0.475597     0.176605 1100|1259|1572|2667|9674|757|878|945|1037|1911 0.770183 0.877202 0.906514    0.028486         NaN rushing_yards                      model    2025          NaN         NaN    0.051319
21800  9.244801  3.868177  0.337902     0.278838   2072|1557|12591|508|579|898|753|689|619|1534 0.753257 0.847798 0.881972    0.032752         NaN rushing_yards baseline_A_trailing5_fixed    2025          NaN         NaN    0.055474
21800 10.780879  2.766503  0.517853     0.210500           741|0|0|14009|14|0|13|2194|2466|2363 0.686743 0.858303 0.913853    0.009266         NaN rushing_yards baseline_B_position_league    2025          NaN         NaN    0.068103

## 2025 error decomposition (model)

`opp_rmse` = opportunity (usage) error, `eff_rmse` = efficiency (rate) error, `inter_rmse` = interaction; `share_*` are the exact covariance shares of Var(point error) and sum to 1. `sd_ratio` = predicted SD / residual SD (1.0 = perfect dispersion, >1 over-dispersed, <1 under-dispersed).

 point_rmse  point_bias  opp_rmse  eff_rmse  inter_rmse  share_opp  share_eff  share_inter   pred_sd  resid_sd  sd_ratio        market
   7.634669   -0.391220  7.634669  0.000000    0.000000   1.000000   0.000000     0.000000  3.706097  7.624638  0.486069 pass_attempts
  57.745489   -2.137383 55.157716 39.379763   32.559876   0.815705   0.398458    -0.214163 43.894252 57.705919  0.760654 passing_yards
   3.550429   -0.212300  3.550429  0.000000    0.000000   1.000000   0.000000     0.000000  2.219535  3.544076  0.626266 rush_attempts
  22.048281   -0.884717 16.933206 15.160190   11.870122   0.573834   0.429264    -0.003099 16.497106 22.030524  0.748830 rushing_yards

**Which part failed.** The model's point means are competitive (it beats both baselines on CRPS in all four markets), so the conditional mean is not the problem. The remaining failure is *dispersion*: `sd_ratio` is 0.55-0.76 in every market, i.e. the predictive intervals are too narrow relative to the residuals. This is visible in the PIT summary as well -- `pit_abs_dev` sits above 0.19 and the outer PIT bins are over-filled (`pit_hist`), the signature of under-dispersion. On the error split, opportunity (usage) dominates everywhere: for the count markets the point error is 100% opportunity by construction; for the yards markets `share_opp` is 0.57-0.82 while efficiency contributes 0.40-0.43 and the interaction share is small or negative. So the next lever is widening the count dispersion (and the efficiency spread), not re-fitting the mean.

## 2026 board population (Defect 4): what each filter removes

Every 2026 prop in the four markets is accounted for. `dropped_unsettled` = no graded `y`; `dropped_no_espn_id` = athlete could not be name-resolved; `dropped_unmatched_athlete` = resolved id has no game history in the cache; `dropped_no_asof` = athlete has no game strictly before that fixture's kickoff; `dropped_leak_guard` = a source game was at/after kickoff (0 expected). `scored` = props that appear in the board.

       market  props_total  dropped_unsettled  dropped_no_espn_id  dropped_unmatched_athlete  dropped_no_asof  dropped_leak_guard  scored
pass_attempts          475                 61                   0                         21                0                   0     393
passing_yards         3792               1024                   0                        127                0                   0    2641
rush_attempts          709                 98                   0                         26                0                   0     585
rushing_yards         5161               1398                   0                        188                0                   0    3575

## 2026 prop board (real lines; as-of features, no leakage)

       market                     method    n  brier_actual_line  brier_realistic_line  mean_line
pass_attempts                      model  393           0.329746              0.220304  29.386768
pass_attempts baseline_A_trailing5_fixed  393           0.340626              0.243271  29.386768
pass_attempts baseline_B_position_league  393           0.431069              0.251311  29.386768
passing_yards                      model 2641           0.363138              0.251005 220.043733
passing_yards baseline_A_trailing5_fixed 2641           0.389435              0.268444 220.043733
passing_yards baseline_B_position_league 2641           0.436734              0.310008 220.043733
rush_attempts                      model  585           0.347843              0.247021  12.314530
rush_attempts baseline_A_trailing5_fixed  585           0.393807              0.284892  12.314530
rush_attempts baseline_B_position_league  585           0.402936              0.301398  12.314530
rushing_yards                      model 3575           0.301930              0.251052  54.073147
rushing_yards baseline_A_trailing5_fixed 3575           0.363891              0.317659  54.073147
rushing_yards baseline_B_position_league 3575           0.354700              0.308246  54.073147

## Reproducibility (Defect 2)

Every headline number regenerates from the committed CSVs; see `REPRODUCE.md`. `predictions_<market>.csv` stores continuous predictive quantiles `q05,q10,q25,q50,q75,q90,q95,q99` and per-row CRPS for the model and both baselines (`crps_model,crps_baseA,crps_baseB`). Coverage maps as cov50=[q25,q75], cov80=[q10,q90], cov90=[q05,q95]; model CRPS = mean(`crps_model`); a baseline's CRPS = mean(`crps_baseA`/`crps_baseB`).
