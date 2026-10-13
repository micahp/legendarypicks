# RESULTS A2: NFL score distribution (task 4.2)

Run 2026-10-11 on the dev DB. Rules, K grid, selection rule and gate: `backend/nfl_score_dist.py` docstring, committed f9b3c33 before this run. Harness: `backend/backtest_nfl_score_dist.py`. Sampler draws n=20000 per game, seed 20261011.

Rows: 3920. Per season: 2010: 240, 2011: 240, 2012: 240, 2013: 240, 2014: 240, 2015: 240, 2016: 240, 2017: 241, 2018: 240, 2019: 240.

## Feature check: the expectations are our own model's, not the line

Spearman-free Pearson correlations, walk-forward v1 projected margin against: the
actual margin, and the closing spread_line.

| rows | n | corr(proj, actual) | corr(proj, spread_line) |
|---|---|---|---|
| rehearsal CSV 2010-2019 (training pool) | 2401 | 0.361 | 0.833 |
| rehearsal CSV 2020-2023 | 1007 | 0.339 | 0.827 |
| dev DB 2024-2025 | 512 | 0.382 | 0.800 |

The line correlates with the projection at about 0.8 in every slice while the
projection correlates with the actual margin at about 0.36 to 0.38, and that is the
same in the historical slice as in the dev-DB slice. The historical expectations
behave like the current model's, and they are not the line relabelled.

## K selection: walk-forward score-pair log loss over 2011-2019 (pool = earlier seasons only)

| K | score-pair log loss | games |
|---|---|---|
| 25 | 3.85916 | 2161 |
| 50 | 4.50380 | 2161 |
| 100 | 5.10883 | 2161 |
| 200 | 5.63557 | 2161 |

Chosen K = 25 (lowest log loss, ties to the smaller K).

## Test seasons 2020-2025, candidate K=25 vs Normal(sigma=13.295)

| season | games | ties | Brier candidate | Brier Normal | score-pair log loss |
|---|---|---|---|---|---|
| 2020 | 240 | 1 | 0.2281 | 0.2194 | 3.87592 |
| 2021 | 256 | 1 | 0.2477 | 0.2356 | 3.87050 |
| 2022 | 255 | 1 | 0.2385 | 0.2292 | 3.86151 |
| 2023 | 256 | 0 | 0.2400 | 0.2353 | 3.86613 |
| 2024 | 256 | 0 | 0.2289 | 0.2225 | 3.86285 |
| 2025 | 256 | 1 | 0.2295 | 0.2288 | 3.85943 |
| pooled | 1519 | 4 | 0.2355 | 0.2285 | 3.86596 |

Pooled Brier difference (candidate minus Normal), 95% bootstrap interval: 0.00700 to 0.00206.

The mean is not the whole story here: most games are close to a coin flip and both models are near 0.5 there, but the candidate is dragged down by the games it gets most wrong. Pooled per-game Brier: candidate mean 0.23553, median 0.19523; Normal mean 0.22853, median 0.19560. The candidate is better on 724 of 1515 games.

## Cover and over calibration (10% bins, bins under 20 games excluded from the sum)

| season | cover SSE candidate | cover SSE Normal | over SSE candidate | over SSE Normal |
|---|---|---|---|---|
| 2020 | 0.0417 | 0.0310 | 0.0707 | 0.0367 |
| 2021 | 0.1714 | 0.2157 | 0.1519 | 0.0872 |
| 2022 | 0.1370 | 0.0641 | 0.0792 | 0.1287 |
| 2023 | 0.1281 | 0.1096 | 0.0945 | 0.1474 |
| 2024 | 0.2165 | 0.0795 | 0.0777 | 0.0160 |
| 2025 | 0.0529 | 0.1220 | 0.3323 | 0.0086 |
| pooled | 0.3105 (8 bins) | 0.2115 (6 bins) | 0.1981 (6 bins) | 0.2260 (6 bins) |

Pooled candidate cover bins (lo, hi, n, covers, rate, flagged):
    (0.0, 0.1, 5, 2.0, 0.4, True)
    (0.1, 0.2, 39, 19.0, 0.48717948717948717, False)
    (0.2, 0.3, 103, 47.0, 0.4563106796116505, False)
    (0.3, 0.4, 246, 113.0, 0.45934959349593496, False)
    (0.4, 0.5, 347, 172.0, 0.4956772334293948, False)
    (0.5, 0.6, 373, 183.0, 0.4906166219839142, False)
    (0.6, 0.7, 263, 124.0, 0.4714828897338403, False)
    (0.7, 0.8, 106, 52.0, 0.49056603773584906, False)
    (0.8, 0.9, 32, 21.0, 0.65625, False)
    (0.9, 1.0, 5, 5.0, 1.0, True)
Pooled candidate over bins:
    (0.0, 0.1, 0, 0, None, True)
    (0.1, 0.2, 12, 5.0, 0.4166666666666667, True)
    (0.2, 0.3, 96, 43.0, 0.4479166666666667, False)
    (0.3, 0.4, 305, 156.0, 0.5114754098360655, False)
    (0.4, 0.5, 350, 184.0, 0.5257142857142857, False)
    (0.5, 0.6, 406, 199.0, 0.49014778325123154, False)
    (0.6, 0.7, 242, 109.0, 0.45041322314049587, False)
    (0.7, 0.8, 89, 41.0, 0.4606741573033708, False)
    (0.8, 0.9, 18, 6.0, 0.3333333333333333, True)
    (0.9, 1.0, 1, 0.0, 0.0, True)

## Ties (reported, no gate)

Pooled 2020-2025: actual ties 4, draws whose tie rate exceeded one half 0. 2017 onward: actual 4 of 1519, predicted 0.

## Probability integral transform of the actual margin (10 bins, flat is good)

    [160, 133, 142, 152, 145, 167, 134, 142, 148, 196]

## Gate

- win Brier no worse than Normal: FAIL (0.2355 vs 0.2285)
- cover calibration better: FAIL (0.3105 vs 0.2115)
- over calibration better: PASS (0.1981 vs 0.2260)

**Verdict: STOP.** The gate fails, so the sampler is not adopted and K is not re-chosen.
