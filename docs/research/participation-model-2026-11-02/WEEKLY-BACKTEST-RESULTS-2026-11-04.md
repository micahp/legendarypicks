# Week-over-week backtest of the lineup grouping model: results, 2026-11-04

Script: `weekly_backtest.py` (committed before the run, `ef8c1d87`). Output: `outputs/weekly_backtest_2022_2025.json`.
Table: the 2016 to 2025 scrimmage participation table (`build_tables.py --seasons 2016,...,2025 --backfill-dir`).
Exploratory research evidence: 2022 to 2025 have been used in earlier fits, so nothing here is an untouched holdout.
2026 was not read.

## What was forecast

Every offensive snap of 2022 to 2025 (140,177 snaps): the grouping (for example `12-OL6`) given the team, the situation
cell, the previous grouping and the call, from data before that game's week. The scorer reproduces
`participation_field.Field.group_probs` exactly on `field_v4_2022_2025.json` (12,019 sampled 2025 snaps, max difference 0).
Score: log loss of the observed grouping per snap. Lower is better.

## Arms and selected parameters (chosen on 2019 to 2021)

- A0: current table weights, four prior seasons at 1, 0.5, 0.25, 0.125.
- A1: season weight 0.75 ** age over the six prior seasons (decay 0.75, window 6).
- A2: A1 plus the current season's published snap counts (RB with FB, TE and WR per team snap), N0 = 8.
- A3: A1 plus the current season's participation (not available live), N0 = 16.

## Results, 2022 to 2025

| Arm | All | Weeks 1-4 | Weeks 5-9 | Weeks 10-18 | Postseason |
|---|---|---|---|---|---|
| A0 | 1.1666 | 1.1124 | 1.1532 | 1.1952 | 1.2074 |
| A1 | 1.1557 | 1.1056 | 1.1443 | 1.1826 | 1.1851 |
| A2 | 1.1322 | 1.0936 | 1.1145 | 1.1572 | 1.1596 |
| A3 | 1.1329 | 1.1004 | 1.1268 | 1.1502 | 1.1453 |

Differences, with game-clustered 95% intervals (negative: the second arm is better):

| Comparison | All | Weeks 1-4 | Weeks 5-9 | Weeks 10-18 | Postseason |
|---|---|---|---|---|---|
| A1 - A0 | -0.0108 [-0.0125, -0.0092] | -0.0068 | -0.0090 | -0.0126 | -0.0223 |
| A2 - A1 | -0.0235 [-0.0287, -0.0177] | -0.0120 | -0.0298 | -0.0254 | -0.0254 |
| A3 - A1 | -0.0229 [-0.0251, -0.0208] | -0.0052 | -0.0175 | -0.0324 | -0.0398 |
| A3 - A2 | +0.0007 [-0.0049, +0.0058] | +0.0068 | +0.0123 | -0.0070 | -0.0144 |

Every interval for A1 - A0 and A2 - A1 excludes zero, in every part of the season.

By season (all weeks): A0 1.135, 1.144, 1.097, 1.293; A2 1.095, 1.105, 1.065, 1.266 (2022 to 2025). 2025 is the hardest
season for every arm.

## Findings

- Longer history with slower decay beats the current four-season halving weights.
- The current-season update from published snap counts helps in every part of the season, and as much as current-season
  participation overall. Participation does better only late (weeks 10 on and the postseason, not significant); snap
  counts do better early. The live 2026 forecast can use the snap-count update.
- Floored snaps (observed grouping given no probability): A0 465, A1 359, A2 359, A3 310 of 140,177.

## Limits

- The selected window (6) and A3's N0 (16) are at the edge of their pre-declared grids; the optimum may lie beyond.
- Decay and window also change the total count weight, which interacts with the fixed shrinkage strengths (50 and 20
  pseudo-plays). A1's gain is not separated into recency and shrinkage.
- Only the grouping is scored. Player snap shares (the lineup layer's substitutions) are not yet backtested.
- The previous grouping and the call are the observed ones on every snap, not simulated.
