# Results: participation tests (pressure and coverage), 2026-10-12

Both tests were pre-registered before their first run (commit `366d977` for test 1, the definition
and tests of test 2 in commit `2fbf3aa`, before its run). Plan: `docs/PLAN-participation-and-spec-b-2026-10-12.md`.
Both were run against the dev DB (`picks.dev.db`, read-only) with `LP_DB_PATH` set. Neither keep rule was loosened.

## Verdicts

| Test | Feature | Verdict | Why |
|---|---|---|---|
| 1 | `participation_keep`: pressure matchup (sacks count as pressure) | NOT KEPT | pooled 2017-2023 F-B interval is `[-0.0010,+0.0005]`, not entirely below zero; 2024 point `+0.0008` is above zero |
| 2 | `coverage_keep`: man/zone matchup | NOT KEPT | pooled 2019-2023 F-B interval is `[-0.0002,+0.0006]`, not entirely below zero; 2025 point is above zero at full precision (printed `+0.0000`) |

## Test 1: pressure (`--feature participation_keep`)

Command: `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db /root/legendarypicks/backend/venv/bin/python nfl_feature_backtest.py --feature participation_keep`
Runtime 31 seconds, exit 0.

```
participation checks: base rows with no league history before the game (column 0) 0
feature: participation pressure matchup (fit from 2016)
  2017-2023 n=1723 Brier v1 0.2274 B 0.2263 F 0.2260 mkt 0.2092 | F-B -0.0003 [-0.0010,+0.0005] | F-mkt +0.0168 [+0.0124,+0.0214] | B-mkt +0.0171 [+0.0127,+0.0217]
                   margin MAE B 10.401 F 10.385 spread 9.873 | F-B -0.016 [-0.043,+0.012]
  2024      n= 256 Brier v1 0.2210 B 0.2225 F 0.2233 mkt 0.2001 | F-B +0.0008 [-0.0018,+0.0036] | F-mkt +0.0232 [+0.0110,+0.0356] | B-mkt +0.0224 [+0.0098,+0.0351]
                   margin MAE B 10.376 F 10.361 spread 9.648 | F-B -0.015 [-0.111,+0.086]
  2025      n= 255 Brier v1 0.2288 B 0.2296 F 0.2298 mkt 0.2137 | F-B +0.0002 [-0.0019,+0.0025] | F-mkt +0.0161 [+0.0047,+0.0273] | B-mkt +0.0159 [+0.0044,+0.0272]
                   margin MAE B 10.682 F 10.708 spread 9.971 | F-B +0.026 [-0.057,+0.107]
   diagnostic 2017 n=240 F-B +0.0015
   diagnostic 2018 n=239 F-B -0.0000
   diagnostic 2019 n=240 F-B -0.0006
   diagnostic 2020 n=239 F-B -0.0003
   diagnostic 2021 n=255 F-B -0.0016
   diagnostic 2022 n=254 F-B +0.0002
   diagnostic 2023 n=256 F-B -0.0009
   diagnostic 2024 n=256 F-B +0.0008
   diagnostic 2025 n=255 F-B +0.0002
   fitted coef on feature, 2016-2024 fit -14.371 (base proj_margin +0.776)
```

Verdict: NOT KEPT. The pooled interval reaches above zero and the 2024 point is above zero. The fitted
coefficient is negative (the pre-registered expected sign), but the keep rule is about Brier, not sign.

## Test 2: coverage matchup (`--feature coverage_keep`)

Command: `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db /root/legendarypicks/backend/venv/bin/python nfl_feature_backtest.py --feature coverage_keep`
Runtime 33 seconds, exit 0.

```
coverage checks: week-1 rows with column 0 (counted) 0
feature: coverage matchup (fit from 2018)
  2019-2023 n=1244 Brier v1 0.2289 B 0.2284 F 0.2286 mkt 0.2111 | F-B +0.0002 [-0.0002,+0.0006] | F-mkt +0.0175 [+0.0120,+0.0229] | B-mkt +0.0173 [+0.0118,+0.0227]
                   margin MAE B 10.381 F 10.397 spread 9.859 | F-B +0.016 [+0.002,+0.030]
  2024      n= 256 Brier v1 0.2210 B 0.2223 F 0.2223 mkt 0.2001 | F-B -0.0001 [-0.0004,+0.0002] | F-mkt +0.0222 [+0.0096,+0.0350] | B-mkt +0.0222 [+0.0096,+0.0350]
                   margin MAE B 10.373 F 10.367 spread 9.648 | F-B -0.007 [-0.018,+0.005]
  2025      n= 255 Brier v1 0.2288 B 0.2293 F 0.2294 mkt 0.2137 | F-B +0.0000 [-0.0000,+0.0000] | F-mkt +0.0157 [+0.0044,+0.0270] | B-mkt +0.0157 [+0.0044,+0.0269]
                   margin MAE B 10.673 F 10.674 spread 9.971 | F-B +0.000 [-0.000,+0.001]
   diagnostic 2019 n=240 F-B +0.0003
   diagnostic 2020 n=239 F-B +0.0008
   diagnostic 2021 n=255 F-B +0.0000
   diagnostic 2022 n=254 F-B +0.0000
   diagnostic 2023 n=256 F-B -0.0000
   diagnostic 2024 n=256 F-B -0.0001
   diagnostic 2025 n=255 F-B +0.0000
   fitted coef on feature, 2018-2024 fit +0.787 (base proj_margin +0.831)
   keep rule: pooled 2019-2023 F-B +0.0002 [-0.0002,+0.0006] entirely below zero: False; 2024 point -0.0001 not above zero: True; 2025 point +0.0000 not above zero: False
verdict coverage_keep: NOT KEPT
```

Verdict: NOT KEPT. The pooled interval is not entirely below zero, and the 2025 point difference is
above zero at full precision (the code's check `p25 <= 0` is False; the four-decimal print rounds it to `+0.0000`).

Coverage checks, measured:
- The graded rows start at week 2 in every season (`base_rows` has 16 week-2 rows per season 2018 to 2025
  and no week-1 rows). So the week-1 column-0 branch is never reached on graded data; the printed count is 0.
  The branch is exercised only by the hand-built fixture in `backend/test_nfl_participation_features.py`.
- One labelled dropback has null epa and is dropped by the definition: 2019 week 1, `2019_01_PIT_NE`, play 4166,
  zone coverage. No other labelled non-sack dropback has null epa in 2018 to 2025.
- Unlabelled dropbacks (not MAN_COVERAGE or ZONE_COVERAGE) are excluded from the share denominators.
  Labelled non-sack dropbacks with a participation row, per season: 2018 17,510; 2019 17,717; 2020 17,879;
  2021 18,604; 2022 17,979; 2023 19,296; 2024 18,867; 2025 18,528. Of the unlabelled, the NULL
  `defense_man_zone_type` count is 974, 929, 1,010, 1,059, 1,022 for 2018 to 2022 and 0 for 2023 to 2025
  (2023 has 19,360 dropbacks in total, so 64 carry a non-NULL value that is neither label; not broken down further).

## Data table (by season, REG dropbacks, from the plan; measured 2026-10-12)

| Season | pressure flag on sacks | man/zone labelled | man share of labelled | Cover 1 / Cover 3 |
|---|---|---|---|---|
| 2016-2017 | null | 0% | none | none |
| 2018-2022 | null | 88.6 to 89.3% (sacks 0%) | 35.0, 37.2, 34.4, 30.3, 28.8 | about 23-30% / 30-34% |
| 2023 | true | 99.6% (sacks 98.5%) | 41.3 | 32.0 / 18.3 |
| 2024 | true | 99.8% | 48.5 | 36.5 / 17.7 |
| 2025 | true | 99.9% | 31.0 | 22.4 / 27.7 |

Defenders in box (about 6.0) and pass rushers (about 4.25) read the same in all ten seasons.
Team man share, first half vs second half of a season, r = 0.81, 0.72, 0.77, 0.70, 0.65, 0.85, 0.67, 0.62 (2018 to 2025).

## Stored data

Participation is stored as `nfl_hist_participation` (2016 to 2025, one row per play; loaded by
`load_nfl_history.py --source participation`, file rows = stored rows for all 10 seasons, 0 mismatches,
sha256 in `nfl_hist_loads`).
