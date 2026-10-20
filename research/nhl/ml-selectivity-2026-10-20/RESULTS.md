# Standalone NHL moneyline selectivity

**Verdict: `NOT_ADOPTED`.** The frozen opening-price policy lost **27.58 units on 886 bets**: **364–522, −3.11% ROI**, selecting 32.99% of 2,686 eligible games. Its 90% season-clustered ROI interval is **[−7.5%, +0.3%]**. Paired profit versus the no-vig market policy was **−1.072 percentage points per eligible game**, with a 90% clustered interval of **[−2.569, +0.000] pp/game**. Neither estimate supports a positive edge.

The price-integrity sensitivity, which refits the expanding models after removing three underround opening-price pairs, is also negative: **−3.44% ROI** and **−1.132 pp/game** versus the market policy. Closing-price sensitivity is worse at **−5.38% ROI**. Closing prices have no timestamped execution record and are not treated as bettable fills.

## Method

The entry point reuses `backtest_matchup_strategy.py` for the canonical loader, Elo replay, B7 Poisson folds and forecasts, team mapping, American-odds profit, moneyline settlement, and season-clustered ROI interval. It joins the committed SBR gzip archive by season, date, and team identity. Prices are aligned to canonical home and away teams, including the one reversed source orientation.

All B7 forecasts are walk-forward. Recalibration and logistic feature weights for each test season use earlier seasons only. The candidate probability uses a logistic model on no-vig market logit, B7 logit, pregame Elo difference, rolling xG matchup difference, rolling goals-for/goals-against difference, and venue. Current-game official goals are used only for the result and settlement, never as predictors. The model uses fixed regularization `C=0.1`; B7 Platt recalibration uses `C=1.0`.

The three-way policy compares each side’s probability to that side’s actual quoted break-even probability. It computes `EV = p × decimal_odds − 1`, shrinks the candidate probability toward the no-vig market over the grid `0, 0.25, 0.50, 0.75, 1.00`, and requires EV to exceed a threshold selected from 0.000 through 0.100 in 0.005 steps. Each season’s threshold and shrink amount maximize prior out-of-sample units per eligible game, subject to at least 50 prior bets or 2% of the prior sample, whichever is larger. Every evaluated game stays in the selection-rate denominator; a pass contributes zero units.

2018–19 supplies the initial forecast history. The policy needs 2019–20 to tune from out-of-sample candidate probabilities, so that season is excluded from the policy score. Policy results cover 2020–21 through 2022–23. The final 2022–23 season is scored once using settings frozen from 2019–20 through 2021–22.

Opening and closing prices are separate experiments. The open-price experiment is primary. Neither quote has an intraday timestamp, so neither establishes an executable historical fill. All confidence intervals below are 90% season-clustered percentile intervals using 5,000 resamples and seed `20261020`.

## Population and price reconciliation

The archive contains 5,132 rows from 2018–19 through 2022–23. The pregame source-date check covered 6,318 feature-complete games in those seasons and found zero features dated on or after their game. Team mapping and canonical matching each had zero unresolved rows. One reversed home/away row was aligned by team identity. Five rows lacked the required pregame feature window; no matched row lacked a walk-forward forecast. This leaves 5,127 forecastable games. Of these, 5,126 available SBR finals agreed with the canonical official winner; one SBR final was missing and the canonical result was used.

| Season | SBR rows | Forecastable games | Open quote pairs | Closing quote pairs |
| --- | ---: | ---: | ---: | ---: |
| 2018–19 | 1,358 | 1,358 | 1,358 | 1,358 |
| 2019–20 | 1,082 | 1,082 | 1,082 | 1,082 |
| 2020–21 | 952 | 952 | 951 | 952 |
| 2021–22 | 1,401 | 1,396 | 1,396 | 1,396 |
| 2022–23 | 339 | 339 | 339 | 339 |
| **Total** | **5,132** | **5,127** | **5,126** | **5,127** |

The opening archive contains three pairs with negative overround. They were retained in the raw opening-price result and reported separately because they cause the market’s own no-vig control to show positive EV. The row-level policy audit found the candidate selected all three, for a combined **+2.800 units**; the market control selected the opposite side on all three, for **+1.20 units**. These three rows are not evidence that either policy has an edge.

| 2021–22 game | Archived open prices (home/away) | Overround | Candidate result / units | Market control result / units |
| --- | ---: | ---: | ---: | ---: |
| Ottawa–Dallas, 2021-10-17 | −181 / +557 | −0.203665 | Away loss / −1.00 | Home win / +0.552 |
| Pittsburgh–Florida, 2022-03-08 | −183 / +480 | −0.180943 | Away win / +4.80 | Home loss / −1.00 |
| Pittsburgh–Carolina, 2022-03-13 | +165 / +162 | −0.240962 | Away loss / −1.00 | Home win / +1.650 |

## Predictor comparison

Metrics are on identical feature-complete games with a prior-season fit: 2019–20 through 2022–23. Brier and log loss are lower when better. `Δ Brier` is predictor Brier minus the no-vig market Brier for that same quote.

### Opening quote, 3,768 games

| Predictor | Brier | Log loss | Δ Brier vs market |
| --- | ---: | ---: | ---: |
| Raw B7 | 0.237302 | 0.667234 | +0.002059 |
| Prior-only logistic B7 | 0.236318 | 0.665195 | +0.001075 |
| No-vig market | **0.235243** | **0.663574** | 0.000000 |
| Prior base rate | 0.248740 | 0.690625 | +0.013497 |
| Market + team features | 0.235347 | 0.663319 | +0.000104 |
| Market + B7 | 0.235278 | 0.663159 | +0.000035 |
| Market + B7 + team features | 0.235342 | 0.663302 | +0.000099 |

### Closing quote, 3,769 games

| Predictor | Brier | Log loss | Δ Brier vs market |
| --- | ---: | ---: | ---: |
| Raw B7 | 0.237312 | 0.667255 | +0.003847 |
| Prior-only logistic B7 | 0.236325 | 0.665210 | +0.002859 |
| No-vig market | **0.233466** | **0.659216** | 0.000000 |
| Prior base rate | 0.248750 | 0.690645 | +0.015284 |
| Market + team features | 0.233837 | 0.660027 | +0.000371 |
| Market + B7 | 0.233778 | 0.659924 | +0.000313 |
| Market + B7 + team features | 0.233838 | 0.660029 | +0.000372 |

Adding the team features did not improve Brier score over the market on either quote. Logistic recalibration improved raw B7, but remained behind the market. The closing market has lower aggregate Brier and log loss than the opening market here; its sample has one additional game because one opening pair is missing.

## Frozen policy settings

The selected probability shrink was zero in each fold. The EV threshold changed only from prior-season out-of-sample results; no probability cutoff such as a fixed 60% rule was used.

| Quote | Scored season | Tuning seasons | Tuning games | Frozen EV threshold | Shrink to market | Prior tuning bets / units |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Open | 2020–21 | 2019–20 | 1,082 | 0.000 | 0.00 | 584 / +38.412 |
| Open | 2021–22 | 2019–20 to 2020–21 | 2,033 | 0.020 | 0.00 | 681 / +32.328 |
| Open | 2022–23 | 2019–20 to 2021–22 | 3,429 | 0.080 | 0.00 | 266 / +57.234 |
| Close | 2020–21 | 2019–20 | 1,082 | 0.000 | 0.00 | 757 / +45.172 |
| Close | 2021–22 | 2019–20 to 2020–21 | 2,034 | 0.000 | 0.00 | 1,320 / +11.429 |
| Close | 2022–23 | 2019–20 to 2021–22 | 3,430 | 0.045 | 0.00 | 615 / +12.671 |

## Policy results

ROI is units divided by bets. Selection rate is bets divided by all eligible games, including passes. Drawdown is maximum peak-to-trough loss in cumulative units. Favorite and underdog controls bet one side on every game. The market’s own policy bets only when its no-vig probability clears the actual quoted break-even price; its very small open-price return is shown as a consistency check, not as evidence.

### Opening prices, raw archive

| Strategy | Games | Bets | W–L | Units | ROI | Selection | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Selective policy | 2,686 | 886 | 364–522 | −27.58 | **−3.11%** | 32.99% | 52.03 |
| Always favorite | 2,686 | 2,686 | 1,665–1,021 | −3.80 | −0.14% | 100.00% | 54.30 |
| Always underdog | 2,686 | 2,686 | 1,021–1,665 | −237.37 | −8.84% | 100.00% | 261.11 |
| Market no-vig control | 2,686 | 3 | 2–1 | +1.20 | +40.08% | 0.11% | 1.00 |

| Season | Strategy | Games | Bets | W–L | Units | ROI | Selection | Max drawdown | Shrink / EV threshold |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2020–21 | Selective policy | 951 | 437 | 173–264 | −27.29 | −6.24% | 45.95% | 43.00 | 0.00 / 0.000 |
| 2020–21 | Always favorite | 951 | 951 | 585–366 | +1.59 | +0.17% | 100.00% | 27.95 | — |
| 2020–21 | Always underdog | 951 | 951 | 366–585 | −87.31 | −9.18% | 100.00% | 99.27 | — |
| 2020–21 | Market no-vig control | 951 | 0 | 0–0 | +0.00 | N/A | 0.00% | 0.00 | — |
| 2021–22 | Selective policy | 1,396 | 446 | 191–255 | +2.71 | +0.61% | 31.95% | 17.72 | 0.00 / 0.020 |
| 2021–22 | Always favorite | 1,396 | 1,396 | 889–507 | +25.65 | +1.84% | 100.00% | 38.79 | — |
| 2021–22 | Always underdog | 1,396 | 1,396 | 507–889 | −160.23 | −11.48% | 100.00% | 165.09 | — |
| 2021–22 | Market no-vig control | 1,396 | 3 | 2–1 | +1.20 | +40.08% | 0.21% | 1.00 | — |
| 2022–23 | Selective policy | 339 | 3 | 0–3 | −3.00 | −100.00% | 0.88% | 3.00 | 0.00 / 0.080 |
| 2022–23 | Always favorite | 339 | 339 | 191–148 | −31.04 | −9.16% | 100.00% | 40.71 | — |
| 2022–23 | Always underdog | 339 | 339 | 148–191 | +10.17 | +3.00% | 100.00% | 24.95 | — |
| 2022–23 | Market no-vig control | 339 | 0 | 0–0 | +0.00 | N/A | 0.00% | 0.00 | — |

Opening policy ROI 90% interval: **[−7.5%, +0.3%]**. The paired delta versus the market control was **−1.072 pp per eligible game**, 90% interval **[−2.569, +0.000] pp/game**. Each interval uses 5,000 season-cluster resamples with seed `20261020`; all three scored seasons contained candidate bets.

### Opening prices, underround-screened sensitivity

This sensitivity removes the three negative-overround opening pairs from every expanding fit and score. It retains 5,123 complete opening quote rows and scores 2,683 games from 2020–21 through 2022–23.

On the 3,765 prior-calibrated screened rows, no-vig market Brier was 0.235188; market plus team features was 0.235320, and market plus B7 and team features was 0.235315. The feature additions still did not improve Brier over the market.

| Strategy | Games | Bets | W–L | Units | ROI | Selection | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Selective policy | 2,683 | 883 | 363–520 | −30.38 | **−3.44%** | 32.91% | 51.03 |
| Always favorite | 2,683 | 2,683 | 1,664–1,019 | −2.35 | −0.09% | 100.00% | 52.30 |
| Always underdog | 2,683 | 2,683 | 1,019–1,664 | −242.82 | −9.05% | 100.00% | 266.56 |
| Market no-vig control | 2,683 | 0 | 0–0 | +0.00 | N/A | 0.00% | 0.00 |

| Season | Selective bets | W–L | Units | ROI | Selection | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2020–21 | 437 | 173–264 | −27.29 | −6.24% | 45.95% | 43.00 |
| 2021–22 | 443 | 190–253 | −0.09 | −0.02% | 31.80% | 18.71 |
| 2022–23 | 3 | 0–3 | −3.00 | −100.00% | 0.88% | 3.00 |

The screened policy’s 90% ROI interval is **[−7.5%, −0.4%]**. Its paired delta versus the market control is **−1.132 pp per eligible game**, with 90% interval **[−2.569, −0.102] pp/game**. Verdict: `NOT_ADOPTED`.

### Closing prices, sensitivity only

| Strategy | Games | Bets | W–L | Units | ROI | Selection | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Selective policy | 2,687 | 1,378 | 564–814 | −74.13 | **−5.38%** | 51.28% | 86.83 |
| Always favorite | 2,687 | 2,687 | 1,689–998 | +48.85 | +1.82% | 100.00% | 36.37 |
| Always underdog | 2,687 | 2,687 | 998–1,689 | −225.30 | −8.39% | 100.00% | 243.09 |
| Market no-vig control | 2,687 | 0 | 0–0 | +0.00 | N/A | 0.00% | 0.00 |

| Season | Strategy | Games | Bets | W–L | Units | ROI | Selection | Max drawdown | Shrink / EV threshold |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2020–21 | Selective policy | 952 | 563 | 222–341 | −33.74 | −5.99% | 59.14% | 52.82 | 0.00 / 0.000 |
| 2020–21 | Always favorite | 952 | 952 | 584–368 | +4.23 | +0.44% | 100.00% | 26.95 | — |
| 2020–21 | Always underdog | 952 | 952 | 368–584 | −67.22 | −7.06% | 100.00% | 83.90 | — |
| 2020–21 | Market no-vig control | 952 | 0 | 0–0 | +0.00 | N/A | 0.00% | 0.00 | — |
| 2021–22 | Selective policy | 1,396 | 804 | 337–467 | −37.32 | −4.64% | 57.59% | 52.16 | 0.00 / 0.000 |
| 2021–22 | Always favorite | 1,396 | 1,396 | 907–489 | +62.44 | +4.47% | 100.00% | 19.66 | — |
| 2021–22 | Always underdog | 1,396 | 1,396 | 489–907 | −166.94 | −11.96% | 100.00% | 174.01 | — |
| 2021–22 | Market no-vig control | 1,396 | 0 | 0–0 | +0.00 | N/A | 0.00% | 0.00 | — |
| 2022–23 | Selective policy | 339 | 11 | 5–6 | −3.06 | −27.82% | 3.24% | 3.06 | 0.00 / 0.045 |
| 2022–23 | Always favorite | 339 | 339 | 198–141 | −17.81 | −5.25% | 100.00% | 30.08 | — |
| 2022–23 | Always underdog | 339 | 339 | 141–198 | +8.85 | +2.61% | 100.00% | 22.14 | — |
| 2022–23 | Market no-vig control | 339 | 0 | 0–0 | +0.00 | N/A | 0.00% | 0.00 | — |

Closing policy ROI 90% interval: **[−6.8%, −4.8%]**. Paired delta versus the market control was **−2.759 pp per eligible game**, 90% interval **[−3.176, −2.095] pp/game**.

## What would change our mind

New pregame information would need to improve prediction quality against the no-vig market on the same games and produce positive out-of-sample return at quoted prices. A future candidate would need a positive season-clustered ROI interval and a positive paired interval against the market control across multiple complete, previously untouched seasons, using prices with a verifiable pregame timestamp. This experiment does not support another threshold search on the same seasons.
