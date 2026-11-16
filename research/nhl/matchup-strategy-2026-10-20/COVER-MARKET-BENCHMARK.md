# Can the model beat the quoted −1.5 price? (market benchmark + selective trading)

ChatGPT's proposed experiment, executed on the archive we already hold. Walk-forward B7
(Elo + xG Poisson) cover probabilities joined to the SBR puck-line prices for the same
games, seasons 2018-19 → 2022-23.

Script: `run_cover_market.py`. Model replay and SBR join reuse this directory's harness
(`fit_fold` per season, prior seasons only; `forecast`, `tri`, canonical key match).

5,123 games carry a |1.5| puck line and both puck prices. 3,765 have a prior-season
calibration fit (2019-20 onward) and are the graded sample below.

## Probability accuracy on identical games

| predictor | Brier | mean p |
| --- | --- | --- |
| raw B7 | 0.2363 | 0.3210 |
| isotonic-recalibrated B7 (prior seasons only) | 0.2343 | 0.3695 |
| no-vig market, de-vigged from both puck prices | **0.2321** | 0.3828 |
| constant historical base rate | 0.2357 | — |

Observed cover rate: 0.3806.

Raw B7 stinks on level — it understates two-goal wins by 6 points, exactly the failure
ChatGPT flagged. Isotonic recalibration closes most of it (0.370 vs 0.381) and buys
0.0020 Brier. It still does not close the gap to the market: **0.2343 vs 0.2321**.

## Selective −1.5 trading (EV threshold tuned on prior seasons, evaluated out of sample)

| probability | bets | record | units | ROI | season-clustered 90% CI |
| --- | --- | --- | --- | --- | --- |
| raw B7 | 151 (2.9%) | 57–94 | +10.60u | +7.02% | [−4.2%, +23.6%] |
| isotonic-recalibrated B7 | 381 (7.4%) | 152–229 | +11.70u | **+3.07%** | **[−0.3%, +6.1%]** |

Recalibrated per season: 2020-21 +11.97u (+7.8%), 2021-22 +0.41u (+0.3%), 2022-23 −0.68u (−0.9%).
The positive number is one season and a monotone decay after it.

Fixed EV buckets from raw B7, no tuning: EV<0 (4,917 bets) −4.29%; EV>0 splits +26.1% (67),
+4.9% (68), +6.8% (41), −5.7% (30). Nothing monotone in the model's disagreement.

The "market's own probability" control places zero bets by construction — a de-vigged
probability cannot clear a positive EV filter against its own price. It is a consistency
check, not an evidence row.

## Reads

1. Calibration was the cheap, real win: Brier 0.2363 → 0.2343, level error 6pp → 1pp.
   It is not, by itself, an edge.
2. After calibration the model still loses to the closing line on the same games. That is
   the thing to fix before any −1.5 policy ships.
3. The selective result (+3.07%, CI touching zero, decaying by season) is consistent with
   "better puck-line predictions are not sufficient to beat the prices." That is outcome A
   in ChatGPT's framing, and the archive supports it.
4. Judge any future margin work against 0.2321 (market no-vig Brier) and against flat −3.04%
   on the unconditionally-bet −1.5 side, not against raw B7.

No production model, gate or threshold was touched.
