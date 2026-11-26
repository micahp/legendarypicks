# Benchmark ladder

[Evaluation home](README.md) · [Current comparisons](MODEL-COMPARISON.md)

The owner-directed [forecasting north star](../STRATEGY-forecasting-north-star-2026-10-10.md) establishes a benchmark ladder: compare the simplest valid prior, established public models, our incumbent/challenger and the market on identical eligible games. Market increment is a stronger distinct claim, not the only definition of a useful consumer forecast.

## NFL historical benchmark (not SLC)

The [October 13 report](../RESULTS-benchmark-ladder-2010-2020-2026-10-13.md) scores 2,633 regular-season games, weeks 2 onward, 2010–2020, no ties.

| Rung | Winner Brier |
|---|---:|
| Coin | .2500 |
| Walk-forward home field only | .2467 |
| 538 Elo | .2193 |
| Frozen v1 points | .2217 |
| De-vigged closing moneyline | .2104 |

V1 versus 538 difference +.0024, paired 95% interval [-.0012, +.0060]. V1 versus market +.0113 [+.0075, +.0150]. 538 was fitted on this historical period; it is a reference, not a prospective forecast. This is **not** an SLC version or comparable with its Week 11 sample.

Use corresponding game and player baselines per league; do not compare prop Brier to winner Brier. See [NFL](../model-cards/nfl.md), [NBA](../model-cards/nba.md), [NHL](../model-cards/nhl.md), [Tennis](../model-cards/tennis.md). A missing timestamped market is an explicit gap, not permission to substitute post-event prices.
