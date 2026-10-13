# Market baseline: frozen v1 vs the line, 2010-2025

Run 2026-10-11 by `backend/market_baseline_2010_2025.py` (read-only). Reproduce with
`LP_DB_PATH=<dev db> venv/bin/python market_baseline_2010_2025.py`.

## Method

- Model: frozen v1 walk-forward (half-life 6, cap 14, cap_points off, sigma 13.295), one forecast
  per graded game using only earlier weeks of the same season. 2010 has no prior; 2011 onward uses
  the previous season's final fit.
- Market: de-vigged moneyline (`devig_home_prob`). Spread: `spread_line`, the home team's expected
  margin, compared with the actual margin.
- Brier: paired bootstrap of model minus market, 5,000 resamples, seed fixed.
- Ties and games missing a moneyline or spread are excluded.
- Inputs: nflverse lines and scores as stored in the dev DB. These lines are presumed closing lines
  with no timestamp (see the north star doc, accountability section). This is retrospective, not
  closing-line value and not prospective grading.

## Results

| Season | n | Brier model | Brier market | Model minus market [95%] | Margin MAE model | Margin MAE spread |
|---|---|---|---|---|---|---|
| 2010 | 240 | 0.2398 | 0.2198 | +0.0199 [+0.0049, +0.0351] | 11.637 | 11.065 |
| 2011 | 240 | 0.2055 | 0.2021 | +0.0033 [-0.0094, +0.0157] | 10.620 | 10.369 |
| 2012 | 239 | 0.2150 | 0.2074 | +0.0076 [-0.0034, +0.0188] | 11.468 | 10.843 |
| 2013 | 239 | 0.2114 | 0.2037 | +0.0077 [-0.0042, +0.0200] | 10.200 | 10.031 |
| 2014 | 239 | 0.2170 | 0.2070 | +0.0100 [-0.0013, +0.0212] | 11.798 | 11.496 |
| 2015 | 240 | 0.2297 | 0.2320 | -0.0023 [-0.0152, +0.0107] | 10.424 | 10.177 |
| 2016 | 238 | 0.2293 | 0.2190 | +0.0103 [-0.0000, +0.0209] | 9.723 | 9.147 |
| 2017 | 240 | 0.2207 | 0.1990 | +0.0218 [+0.0087, +0.0344] | 10.650 | 9.910 |
| 2018 | 239 | 0.2265 | 0.2094 | +0.0171 [+0.0045, +0.0293] | 10.560 | 9.914 |
| 2019 | 240 | 0.2242 | 0.2147 | +0.0094 [-0.0033, +0.0227] | 10.437 | 10.065 |
| 2020 | 239 | 0.2194 | 0.2002 | +0.0191 [+0.0078, +0.0307] | 10.321 | 9.996 |
| 2021 | 255 | 0.2356 | 0.2144 | +0.0212 [+0.0074, +0.0349] | 11.514 | 10.688 |
| 2022 | 254 | 0.2292 | 0.2085 | +0.0206 [+0.0089, +0.0326] | 9.235 | 8.742 |
| 2023 | 256 | 0.2353 | 0.2173 | +0.0180 [+0.0058, +0.0304] | 10.602 | 9.818 |
| 2024 | 256 | 0.2210 | 0.2001 | +0.0209 [+0.0070, +0.0350] | 10.456 | 9.648 |
| 2025 | 255 | 0.2288 | 0.2137 | +0.0151 [+0.0043, +0.0257] | 10.671 | 9.971 |
| **2010-2025** | **3,909** | **0.2244** | **0.2105** | **+0.0138 [+0.0107, +0.0169]** | **10.642** | **10.111** |
| 2024-2025 | 511 | 0.2249 | 0.2069 | +0.0180 [+0.0092, +0.0268] | 10.563 | 9.809 |

## What it says

- The model's Brier is worse than the de-vigged market in 15 of 16 seasons. The one exception,
  2015, is -0.0023 with an interval that spans zero.
- The interval excludes zero on the market's side in 9 seasons (2010, 2017, 2018, 2020 to 2025).
  Pooled, the gap is +0.0138 with the interval +0.0107 to +0.0169.
- Margin MAE is worse than the spread in all 16 seasons.
- The 2025 row reproduces the recorded A3 holdout exactly (Brier 0.2288 vs 0.2137, interval
  +0.0043 to +0.0257). The 2025 holdout is one-shot, so this is a reproduction, not a new result.

## What it does not say

- It does not show a betting edge or its absence at obtainable prices. There are no timestamped
  lines in the database.
- Season-by-season intervals are wide, and 16 seasons are not a large sample. The pooled interval is
  the stronger evidence, and it assumes the seasons are comparable.
- A first pass with the default sigma (13.4) gave somewhat different numbers. It was superseded by
  this run, which uses the frozen sigma 13.295 that the A3 holdout used.

## Data version

Pinned by `RESULTS-A3` section 7 and `RESULTS-A9`: the frozen v1 config and the dev DB as of the
2010 to 2023 load. Any rerun on a later DB state should be recorded as a new result with its own date.
