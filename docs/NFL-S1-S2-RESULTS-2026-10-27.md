# NFL S1 and S2 results: opponent strength and situational variables (2026-10-27)

Status: research, dev only. No production output, forecast, simulator default or frozen snapshot is changed. The 2026
season was not read. Code: `scripts/nfl_sequence/splits/s1_s2_models.py` (tests: `test_s1_s2_models.py`). The run
output is kept under the scratchpad (`results/s1_s2_run.txt`, `results/s1_s2.json`), not committed.

## 1. Windows and labels

| Window | Seasons | Use | Label |
|---|---|---|---|
| Fit | 2010 to 2017 | Calibration maps and S2 weights | Fit |
| Validation | 2018 to 2020 | Choose S1 settings (ridge half-life and penalty) | Selection |
| Test | 2021 to 2025 | Report once | Previously examined. The S0b test was inspected before this run, so these numbers are not an untouched confirmation |
| Holdout | 2026 | Not read | Sealed |

Cohorts:

- **Strict (S).** The S0b rule: both teams have at least 4 earlier games in the season, non-tied, with a moneyline. Every model is scored on exactly these games. Validation n 573, test n 1,037.
- **Ladder (L).** 2010 to 2020, weeks 2 on, the games the benchmark ladder grades (LP v1 backtest rows with a market number and a 538 Elo row). n 2,633. Includes the fit years, so it is descriptive.
- **Full slate, weeks 1 to 4.** 2011 to 2025 with a market number. n 942. Week 1 alone n 236. v1 has no forecast before week 2, so this table compares S1 with home-only and the market only.

## 2. Models

- **S0b** (from `NFL-S0-BASELINE-AUDIT-2026-10-27.md`). Refitted here on the fit window with the same specification.
- **S1, opponent-adjusted team strength.** Margin = home advantage (not at neutral sites) + rating(home) minus rating(away). Ratings are a ridge fit on every regular-season game dated strictly before the target date, with recency weights 0.5 ** (days / (7 * half-life)). Settings were chosen on validation Brier of the calibrated win probability. Chosen: half-life 13 weeks, penalty 2. Win probability = sigmoid(a + b * margin), with a and b fitted on the fit window. Margin distribution = normal, sigma 13.64 points (fit window).
- **S2, S1 plus calendar, rest, travel and division.** A logistic on [1, S1 margin / 10] plus the group's features, fitted on the fit window. Groups: weekday (Thursday, Monday, Saturday; Sunday is the base), kickoff (late afternoon 14:30 to 19:59 ET, primetime 20:00 or later; early is the base), rest (home minus away rest, clipped at plus or minus 7 days; short rest of 5 days or fewer for each team), travel (away team's time-zone crossings east and west, 0 at neutral sites), division.
- **LP v1 points.** The frozen walk-forward backtest (`nfl_backtest.backtest_season`, read-only, unchanged). Its own parameters were set earlier on this 2010 to 2020 history (see limitations).
- **Market.** De-vigged closing moneyline from the schedule. Evaluation only, never an input.
- **538 Elo** (ladder only, 2010 to 2020). **Home only** uses the walk-forward home-win rate from the benchmark ladder, except where the table says fit-window constant.

**Harness check.** On the ladder cohort, the replay reproduces the repo's existing benchmark numbers exactly to four places: home 0.2467, 538 Elo 0.2193, LP v1 0.2217, closing market 0.2104 (`docs/RESULTS-benchmark-ladder-2010-2020-2026-10-13.md`).

## 3. Results on identical games

### Strict cohort (every model on the same games)

| Model | Validation 2018 to 2020, n 573: Brier | Log loss | Slope | Test 2021 to 2025, n 1,037: Brier | Log loss | Slope |
|---|---|---|---|---|---|---|
| Coin flip | 0.2500 | 0.6931 | n/a | 0.2500 | 0.6931 | n/a |
| Home only (walk-forward rate) | 0.2483 | 0.6898 | unstable | 0.2480 | 0.6892 | unstable |
| S0b | 0.2200 | 0.6304 | 0.964 | 0.2259 | 0.6431 | 0.862 |
| LP v1 points | 0.2212 | 0.6322 | 0.987 | 0.2230 | 0.6380 | 0.929 |
| Closing market | 0.2079 | 0.6035 | 1.045 | 0.2080 | 0.6027 | 1.061 |
| S1 | 0.2194 | 0.6287 | 0.943 | 0.2228 | 0.6373 | 0.868 |
| S2, weekday | 0.2192 | 0.6280 | 0.941 | 0.2230 | 0.6378 | 0.859 |
| S2, kickoff | 0.2193 | 0.6285 | 0.942 | 0.2230 | 0.6376 | 0.862 |
| S2, rest | 0.2201 | 0.6298 | 0.928 | 0.2231 | 0.6380 | 0.855 |
| S2, travel | 0.2197 | 0.6295 | 0.934 | 0.2233 | 0.6384 | 0.857 |
| S2, division | 0.2189 | 0.6275 | 0.952 | 0.2229 | 0.6375 | 0.865 |
| S2, all groups | 0.2193 | 0.6280 | 0.933 | 0.2236 | 0.6390 | 0.841 |

Margin scores (normal distribution, identical games). CRPS in points, lower is better; MAE in points.

| Model | Validation CRPS | Validation MAE | Test CRPS | Test MAE |
|---|---|---|---|---|
| S0b | 7.621 | 10.595 | 7.385 | 10.309 |
| LP v1 points | 7.572 | 10.519 | 7.391 | 10.268 |
| S1 | 7.532 | 10.452 | 7.343 | 10.229 |
| S2, all groups | 7.508 | 10.411 | 7.360 | 10.236 |

The market has no margin distribution in this table. The "home only" slope is unstable because its forecasts move little over time.

### Paired Brier differences (negative means the first model is better; week-block 95% interval)

| Comparison | Validation | Test (previously examined) |
|---|---|---|
| S1 minus S0b | -0.0006 [-0.0062, +0.0049] | -0.0030 [-0.0066, +0.0005] |
| S1 minus LP v1 | -0.0018 [-0.0048, +0.0013] | -0.0002 [-0.0023, +0.0021] |
| LP v1 minus S0b | +0.0012 [-0.0056, +0.0078] | -0.0028 [-0.0072, +0.0014] |
| Market minus S1 | -0.0114 [-0.0189, -0.0039] | -0.0149 [-0.0196, -0.0097] |
| Market minus S0b | -0.0121 [-0.0213, -0.0039] | -0.0179 [-0.0237, -0.0121] |

## 4. Which situational variables improve out-of-sample predictions

Each row adds one group to S1. Negative means the group helps; every interval includes zero.

| Added to S1 | Validation difference [interval] | Test difference [interval] | Verdict |
|---|---|---|---|
| Weekday | -0.0002 [-0.0015, +0.0012] | +0.0002 [-0.0008, +0.0012] | No effect |
| Kickoff window | -0.0000 [-0.0008, +0.0007] | +0.0001 [-0.0003, +0.0005] | No effect |
| Rest | +0.0007 [-0.0009, +0.0024] | +0.0003 [-0.0008, +0.0014] | No gain; slightly worse in both windows |
| Travel | +0.0003 [-0.0003, +0.0010] | +0.0005 [-0.0001, +0.0011] | No gain; slightly worse in both windows |
| Division | -0.0004 [-0.0013, +0.0005] | +0.0001 [-0.0005, +0.0007] | No effect |
| All five | -0.0001 [-0.0022, +0.0021] | +0.0008 [-0.0009, +0.0025] | No effect |

**Result: none of the situational variables improved out-of-sample Brier on the validation window or on the test window.** Rest and travel nudged the score in the wrong direction in both windows, with intervals that include zero. We report this as a null result. The S2 weights (fit window) are kept in the JSON, and no group is kept on the basis of this table.

Splits (strict, validation and test pooled, S1 minus S0b and S2 minus S1). Every interval includes zero.

| Split | Level | n | S1 minus S0b | S2 minus S1 |
|---|---|---|---|---|
| Weekday | Sunday | 1,327 | -0.0013 [-0.0049, +0.0025] | +0.0002 [-0.0008, +0.0013] |
| Weekday | Monday | 107 | -0.0085 [-0.0190, +0.0018] | -0.0030 [-0.0096, +0.0032] |
| Weekday | Thursday | 112 | -0.0053 [-0.0157, +0.0048] | +0.0018 [-0.0096, +0.0133] |
| Weekday | Saturday | 54 | -0.0097 [-0.0250, +0.0026] | +0.0058 [-0.0004, +0.0143] |
| Kickoff | early | 838 | -0.0031 [-0.0072, +0.0010] | +0.0003 [-0.0008, +0.0015] |
| Kickoff | late afternoon | 446 | +0.0002 [-0.0058, +0.0065] | +0.0012 [-0.0010, +0.0035] |
| Kickoff | primetime | 326 | -0.0031 [-0.0085, +0.0024] | -0.0003 [-0.0051, +0.0044] |
| Roof | dome | 485 | -0.0016 [-0.0064, +0.0035] | -0.0009 [-0.0032, +0.0016] |
| Roof | outdoors | 1,125 | -0.0024 [-0.0060, +0.0015] | +0.0010 [-0.0005, +0.0027] |

Season by season, S1 minus S0b ranged from -0.0057 (2024) to +0.0040 (2025), with no consistent sign. Thursday, Monday and Saturday subgroups are small, and their intervals are wide. Tuesday and Wednesday (3 games each) and Friday (4 games) are not interpreted.

## 5. Ladder cohort: S1 and LP v1 against 538 Elo and the market (2010 to 2020, descriptive)

| Model | Brier | Log loss | Slope |
|---|---|---|---|
| Coin flip | 0.2500 | 0.6931 | n/a |
| Home only | 0.2467 | 0.6866 | 0.052 |
| 538 Elo | 0.2193 | 0.6278 | 0.941 |
| LP v1 points | 0.2217 | 0.6325 | 0.927 |
| Closing market | 0.2104 | 0.6082 | 1.066 |
| S1 | 0.2193 | 0.6277 | 0.927 |
| S2, all groups | 0.2190 | 0.6269 | 0.921 |

Paired differences (negative means the first model is better):

- S1 minus 538 Elo: +0.0001 [-0.0033, +0.0034]. Tie.
- S1 minus LP v1: -0.0023 [-0.0038, -0.0008]. S1 is better. This window includes the fit years and the validation years, which were used to set calibration and S1 settings. Treat it as descriptive.
- LP v1 minus 538 Elo: +0.0024 [-0.0010, +0.0057].
- Market minus S1: -0.0089 [-0.0125, -0.0054]. Market is better.
- Market minus LP v1: -0.0113 [-0.0148, -0.0075].
- 538 Elo minus home only: -0.0274 [-0.0333, -0.0216].

538 Elo is a flattering bar: its constants were fit on this history (`benchmark_ladder_2010_2020.py` says so).

## 6. Early season and the preseason prior (Weeks 1 to 4)

| Cohort | Model | Brier | Log loss | Slope |
|---|---|---|---|---|
| Ladder, weeks 2 to 4, n 513 | LP v1 points | 0.2429 | 0.6795 | 0.512 |
| | S1 | 0.2348 | 0.6620 | 0.674 |
| | S2, all groups | 0.2352 | 0.6631 | 0.658 |
| | Closing market | 0.2241 | 0.6361 | 0.870 |
| Full slate, weeks 1 to 4, 2011 to 2025, n 942 | Coin flip | 0.2500 | 0.6931 | n/a |
| | Home only | 0.2476 | 0.6883 | unstable |
| | S1 with prior-season ratings | 0.2331 | 0.6584 | 0.817 |
| | Closing market | 0.2219 | 0.6327 | 0.988 |
| Full slate, week 1 only, n 236 | Home only | 0.2506 | 0.6943 | unstable |
| | S1 with prior-season ratings | 0.2253 | 0.6424 | 1.532 |
| | Closing market | 0.2183 | 0.6261 | 1.219 |

Paired differences:

- Weeks 2 to 4: S1 minus LP v1 = -0.0081 [-0.0133, -0.0033]. S1 is clearly better early. Its prior-season ratings are the reason.
- Weeks 2 to 4: market minus S1 = -0.0107 [-0.0202, -0.0014]. Market is better.
- Weeks 1 to 4, full slate: S1 minus home only = -0.0145 [-0.0233, -0.0053]. The preseason prior beats home-only forecasts.

**Result: the prior-season prior gives Weeks 1 to 4 a real forecast, and it beats home-only and LP v1 early.** The early calibration is weak (slopes 0.67 to 0.82). Week 1 slopes rest on 236 games.

## 7. Calibration

- Validation slopes are 0.94 for S1 and 0.96 for S0b, inside the plan's 0.9 to 1.1 band.
- Test slopes are 0.87 for S1 and 0.86 for S0b, below the 0.9 floor. Both models are over-confident on the test window. This was not corrected on the test window. A recalibration fitted on the validation window is the next step (see section 9).
- The market's test slope is 1.06.

## 8. Limitations and what is still open

1. **S1 uses final scores only.** The verified box-score fields (passing and rushing yards, passing attempts) are not yet inputs. The first step after this run is an opponent-adjusted yardage variant on those fields.
2. **The chosen half-life (13 weeks) is the smallest value in the pre-declared grid.** A shorter half-life might do better. The grid was not extended after looking at validation.
3. **LP v1's own parameters (half-life 6, cap 14, sigma 13.295) were set on this 2010 to 2020 history earlier.** Its numbers in this report are the frozen v1 as it stands, not a fresh out-of-sample test. S1's calibration and settings were set on 2010 to 2017 and 2018 to 2020, which are part of the ladder cohort.
4. **The market is a de-vigged moneyline with no timestamp.** It is treated as a closing line for evaluation only.
5. **Two situational groups show no benefit, and the weekday and kickoff effects are small.** Rest and travel are mildly negative in both windows, and the intervals include zero. This does not show that these conditions have no effect in the league. It shows that, with these encodings, the score-based model does not gain from them out of sample.
6. **Travel uses home-city time zones.** Neutral and international games get 0. The encoding is coarse.
7. **Margin CRPS assumes normal margins** with one sigma per model. It is comparable across models on the same games, not an absolute score.
8. **v1+Elo (the stacked model in the ladder) is not evaluated here.** It needs the `nfl_feature_backtest` stacked features, which were not run in this pass.
9. **538 Elo is not available after 2020.** The test window has no Elo rung.

## 9. Next steps (not done in this pass)

1. Recalibrate S1 and S0b on the validation window only, then score the test window once and label it as a second look at the same years.
2. Add opponent-adjusted yardage (verified passing and rushing fields) as an S1 variant, on the same cohort.
3. Run v1+Elo through the same identical-games harness.
4. Keep the attendance and capacity fields out of S1 and S2. The capacity dispute does not block these models, because neither model uses capacity.
5. For the preseason prior, test a shrinkage version with a prior-season anchor, and a version that uses the previous season's final ratings with a fixed carry-over weight, on validation.

## 10. Summary of the question

Does adding situational conditions lower the game-winner Brier score in this research set?

- Weekday, kickoff window, rest, travel and division: no improvement on validation or test. Rest and travel are slightly worse. Null results.
- Opponent-adjusted team strength (S1): matches LP v1 and 538 Elo within noise on the identical games, and beats S0b on the test window by 0.0030 (interval includes zero).
- Preseason prior: real improvement for Weeks 1 to 4 against v1 and home-only.
- Closing market: better than every model in every window reported here. The gap to S1 runs from 0.007 (week 1) to 0.015 (test), and the gap to S0b from 0.012 (validation) to 0.018 (test).
